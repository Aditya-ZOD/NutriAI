import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from fastapi import Request, Response, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from database import get_db

ph = PasswordHasher()
security_bearer = HTTPBearer(auto_error=False)

# Environment and Cookie Security Configuration
IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() in ["production", "prod"]
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() in ["1", "true", "yes"]

# Email validation regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Rate limiting store: ip -> list of timestamps
_rate_limit_store = defaultdict(list)

def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    """Dependency to enforce rate limits per client IP address."""
    def dependency(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        timestamps = _rate_limit_store[client_ip]
        # Retain only timestamps within the rolling window
        valid_timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(valid_timestamps) >= max_requests:
            retry_after = int(window_seconds - (now - valid_timestamps[0]))
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please wait {max(retry_after, 1)} seconds before retrying."
            )
        valid_timestamps.append(now)
        _rate_limit_store[client_ip] = valid_timestamps
    return dependency

def validate_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not cleaned or not EMAIL_REGEX.match(cleaned):
        raise HTTPException(status_code=400, detail="Invalid email address format.")
    return cleaned

def validate_password(password: str) -> str:
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long."
        )
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain both letters and at least one number."
        )
    return password

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_and_migrate_password(conn, user_id: int, candidate_password: str, password_hash: Optional[str], legacy_plain: Optional[str]) -> bool:
    """
    Verifies user password. If user has legacy plaintext password, verifies it,
    hashes it with Argon2, updates the database, and clears the plaintext password field.
    """
    # 1. Argon2 verification
    if password_hash and password_hash.startswith("$argon2"):
        try:
            ph.verify(password_hash, candidate_password)
            return True
        except VerifyMismatchError:
            return False

    # 2. Legacy plaintext verification with safe migration
    if legacy_plain:
        if secrets.compare_digest(legacy_plain, candidate_password):
            new_hash = hash_password(candidate_password)
            cursor = conn.cursor()
            # Explicitly set password_hash and clear the plaintext password to NULL
            cursor.execute("""
                UPDATE users 
                SET password_hash = ?, password = NULL 
                WHERE id = ?
            """, (new_hash, user_id))
            conn.commit()
            return True
        return False

    return False

def create_session(user_id: int, days_valid: int = 7) -> str:
    """Creates a cryptographically secure session token stored in SQLite."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days_valid)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sessions (token, user_id, expires_at)
            VALUES (?, ?, ?)
        """, (token, user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
    return token

def revoke_session(token: str):
    """Revokes session token upon logout."""
    if not token:
        return
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))

def set_session_cookie(response: Response, token: str):
    """Attaches a secure session cookie to the response."""
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=7 * 86400
    )

def clear_session_cookie(response: Response):
    """Clears session cookie upon logout."""
    response.delete_cookie(
        key="session_token",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax"
    )

def extract_token_from_request(request: Optional[Request] = None, auth: Optional[Any] = None) -> tuple[Optional[str], bool]:
    """Safely extracts session token from HTTPBearer, headers, or cookies."""
    token = None
    is_cookie_auth = False

    # Check if auth is a valid HTTPAuthorizationCredentials instance (not a FastAPI Depends marker)
    if isinstance(auth, HTTPAuthorizationCredentials) and auth.credentials:
        token = auth.credentials
    elif request:
        auth_hdr = request.headers.get("authorization", "") if hasattr(request, "headers") else ""
        if auth_hdr and auth_hdr.lower().startswith("bearer "):
            token = auth_hdr.split(" ", 1)[1]
        elif hasattr(request, "headers") and "x-session-token" in request.headers:
            token = request.headers.get("x-session-token")
        elif hasattr(request, "cookies") and "session_token" in request.cookies:
            token = request.cookies.get("session_token")
            is_cookie_auth = True

    return token, is_cookie_auth

def get_optional_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    request: Request = None
) -> Optional[dict]:
    """Returns authenticated user if a valid token is present; otherwise returns None."""
    token, is_cookie_auth = extract_token_from_request(request, auth)
    if not token:
        return None

    # CSRF defense: If request relies on cookies for state mutation, check Sec-Fetch-Site
    if is_cookie_auth and request and hasattr(request, "method") and request.method in ["POST", "PUT", "DELETE"]:
        sec_fetch = request.headers.get("sec-fetch-site")
        if sec_fetch and sec_fetch == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site cookie request forbidden.")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.name, u.email, u.role
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
        """, (token, now_str))
        user_row = cursor.fetchone()
        return dict(user_row) if user_row else None

def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    request: Request = None
) -> dict:
    """Dependency to retrieve authenticated user; raises 401 if not authenticated."""
    user = get_optional_user(auth, request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in."
        )
    return user

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Restricts endpoint access to administrators."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Administrator privilege required."
        )
    return user
