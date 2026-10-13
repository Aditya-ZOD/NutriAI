import os
import shutil
import sqlite3
import pytest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from main import app
from database import get_db, init_db, DB_PATH
from security import hash_password

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    init_db()

# --- 1. Startup & Health Check ---
def test_application_startup_and_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["healthy", "degraded"]
    assert data["database"] == "connected"
    assert "ai_engine" in data

# --- 2. Signup & Duplicate Prevention ---
def test_signup_validation_and_duplicate_prevention():
    test_email = "audit_stage2_user@example.com"

    # Cleanup before test
    with get_db() as conn:
        conn.cursor().execute("DELETE FROM users WHERE email = ?;", (test_email,))

    # Weak password (<8 chars)
    weak_res = client.post("/api/auth/signup", json={
        "name": "Audit User",
        "email": test_email,
        "password": "short"
    })
    assert weak_res.status_code == 400

    # Invalid email format
    bad_email_res = client.post("/api/auth/signup", json={
        "name": "Audit User",
        "email": "not-valid-email",
        "password": "ValidPassword2026!"
    })
    assert bad_email_res.status_code == 400

    # Successful signup
    valid_res = client.post("/api/auth/signup", json={
        "name": "Audit User",
        "email": test_email,
        "password": "ValidPassword2026!"
    })
    assert valid_res.status_code == 201
    assert "token" in valid_res.json()
    assert valid_res.json()["user"]["email"] == test_email

    # Duplicate signup must be rejected
    dup_res = client.post("/api/auth/signup", json={
        "name": "Audit User",
        "email": test_email,
        "password": "ValidPassword2026!"
    })
    assert dup_res.status_code == 400

# --- 3. Database Migration & Plaintext Clearance Against DB Copy ---
def test_database_migration_against_copy(tmp_path):
    test_db_copy = tmp_path / "test_migration_copy.db"
    
    # Create legacy schema and user in test database
    conn = sqlite3.connect(test_db_copy)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT
        );
    """)
    legacy_email = "legacy_copy_user@example.com"
    plain_password = "PlainSecret123!"
    c.execute("INSERT INTO users (name, email, password) VALUES ('Legacy User', ?, ?);", (legacy_email, plain_password))
    conn.commit()
    conn.close()

    # Apply migration logic from database.py to the copy
    from database import init_db
    with patch("database.DB_PATH", str(test_db_copy)):
        init_db()

        # Check columns after migration
        conn = sqlite3.connect(test_db_copy)
        c = conn.cursor()
        c.execute("PRAGMA table_info(users);")
        col_names = [r[1] for r in c.fetchall()]
        assert "password_hash" in col_names
        assert "role" in col_names
        assert "created_at" in col_names

        # Verify plaintext exists before login
        c.execute("SELECT password, password_hash FROM users WHERE email = ?;", (legacy_email,))
        row = c.fetchone()
        assert row[0] == plain_password
        assert row[1] is None

        # Execute migration verification
        from security import verify_and_migrate_password
        is_valid = verify_and_migrate_password(conn, user_id=1, candidate_password=plain_password, password_hash=row[1], legacy_plain=row[0])
        assert is_valid is True

        # Verify plaintext password was cleared to NULL and password_hash starts with $argon2
        c.execute("SELECT password, password_hash FROM users WHERE email = ?;", (legacy_email,))
        migrated_row = c.fetchone()
        assert migrated_row[0] is None, "Plaintext password column must be cleared to NULL after migration"
        assert migrated_row[1].startswith("$argon2id$")
        conn.close()

# --- 4. Unauthorized Access Rejection ---
def test_unauthorized_endpoints():
    unauth_client = TestClient(app, cookies={})
    endpoints = [
        ("GET", "/api/meals"),
        ("POST", "/api/meals"),
        ("GET", "/api/water"),
        ("POST", "/api/water"),
        ("GET", "/api/weight"),
        ("POST", "/api/weight"),
        ("GET", "/api/plans"),
        ("GET", "/api/profile"),
        ("PUT", "/api/profile"),
        ("GET", "/api/conversations"),
        ("POST", "/api/conversations")
    ]
    for method, path in endpoints:
        if method == "GET":
            res = unauth_client.get(path)
        elif method == "PUT":
            res = unauth_client.put(path, json={})
        else:
            res = unauth_client.post(path, json={})
        assert res.status_code == 401, f"{method} {path} should require authentication"

# --- 5. Admin Access Control ---
def test_admin_access_control():
    # Login as regular user
    user_res = client.post("/api/auth/login", json={
        "email": "audit_stage2_user@example.com",
        "password": "ValidPassword2026!"
    })
    token = user_res.json()["token"]

    # Non-admin accounts must receive 403 Forbidden
    admin_api = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert admin_api.status_code == 403

    users_page_api = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert users_page_api.status_code == 403

# --- 6. User Data Isolation ---
def test_user_data_isolation():
    email_a = "user_iso_a@example.com"
    email_b = "user_iso_b@example.com"

    with get_db() as conn:
        conn.cursor().execute("DELETE FROM users WHERE email IN (?, ?);", (email_a, email_b))

    token_a = client.post("/api/auth/signup", json={"name": "User A", "email": email_a, "password": "UserPass123!"}).json()["token"]
    token_b = client.post("/api/auth/signup", json={"name": "User B", "email": email_b, "password": "UserPass123!"}).json()["token"]

    # User A logs meal
    client.post("/api/meals", json={
        "log_date": "2026-10-14",
        "meal_category": "lunch",
        "food_name": "Tofu Bowl",
        "serving_size": 1.0,
        "calories": 280.0,
        "protein": 20.0,
        "carbs": 15.0,
        "fat": 10.0
    }, headers={"Authorization": f"Bearer {token_a}"})

    # User B should see 0 meals
    res_b = client.get("/api/meals?date=2026-10-14", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert len(res_b["all_meals"]) == 0
    assert res_b["totals"]["calories"] == 0.0

    # User A sees their meal
    res_a = client.get("/api/meals?date=2026-10-14", headers={"Authorization": f"Bearer {token_a}"}).json()
    assert len(res_a["all_meals"]) == 1
    assert res_a["totals"]["calories"] == 280.0

# --- 7. Session Revocation on Logout ---
def test_session_revocation_on_logout():
    login_res = client.post("/api/auth/login", json={
        "email": "audit_stage2_user@example.com",
        "password": "ValidPassword2026!"
    })
    token = login_res.json()["token"]

    # Verify session is valid
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200

    # Perform logout
    logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200

    # Session token must now be rejected
    subsequent_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert subsequent_res.status_code == 401

# --- 8. Guest Chat Length Capping & Input Validation ---
def test_guest_chat_validation_and_capping():
    unauth_client = TestClient(app, cookies={})

    # Empty message
    empty_res = unauth_client.post("/chat", json={"message": "   "})
    assert empty_res.status_code == 400

    # Overly long message (>500 characters) to prevent anonymous resource exhaustion
    long_msg = "A" * 501
    capped_res = unauth_client.post("/chat", json={"message": long_msg})
    assert capped_res.status_code == 400
    assert "limited to 500 characters" in capped_res.json()["detail"]

# --- 9. Chat Reset Behavior ---
def test_chat_reset_endpoints():
    unauth_client = TestClient(app, cookies={})
    guest_reset = unauth_client.post("/chat/reset")
    assert guest_reset.status_code == 200
    assert "Guest consultation reset" in guest_reset.json()["message"]

    # Authenticated reset
    auth_res = client.post("/api/auth/login", json={
        "email": "audit_stage2_user@example.com",
        "password": "ValidPassword2026!"
    })
    token = auth_res.json()["token"]
    auth_reset = client.post("/chat/reset", headers={"Authorization": f"Bearer {token}"})
    assert auth_reset.status_code == 200
    assert "conversation_id" in auth_reset.json()

# --- 10. AI Service Deterministic Mocking & Failure Handling ---
def test_ai_service_deterministic_mock_and_failures():
    # 1. Deterministic Mock Response Test
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": "🎯 Goal: Fat Loss\n🥣 Breakfast: Oats with Almond Milk [Approximate AI Estimate]"
            }
        }
        from ai_service import generate_nutrition_reply
        result = generate_nutrition_reply(messages=[{"role": "user", "content": "Suggest a breakfast"}])
        assert result["status"] == "success"
        assert "Goal: Fat Loss" in result["reply"]

    # 2. Timeout Failure Handling (simulating slow CPU / timeout without raw stack trace)
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = httpx.TimeoutException("Read timed out")
        result = generate_nutrition_reply(messages=[{"role": "user", "content": "Suggest a plan"}])
        assert result["status"] == "timeout"
        assert "timed out" in result["reply"]
        assert "Traceback" not in result["reply"]

    # 3. Connection Refused Handling (simulating Ollama offline)
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = httpx.ConnectError("Connection refused")
        result = generate_nutrition_reply(messages=[{"role": "user", "content": "Suggest a plan"}])
        assert result["status"] == "offline"
        assert "ollama serve" in result["reply"]
        assert "Traceback" not in result["reply"]

# --- 11. Legacy Route Rate Limiting ---
def test_legacy_route_rate_limiting():
    from security import _rate_limit_store
    _rate_limit_store.clear()
    unauth_client = TestClient(app, cookies={})
    hit_limit = False
    for _ in range(25):
        res = unauth_client.post("/login", json={"email": "nonexistent@example.com", "password": "WrongPassword1!"})
        if res.status_code == 429:
            hit_limit = True
            break
    assert hit_limit is True, "Rate limit should trigger on repeated login attempts"
    # Reset store so subsequent tests in this session are not rate limited
    _rate_limit_store.clear()

# --- 12. Meals Lifecycle & Nutrition Totals ---
def test_meal_lifecycle_and_totals():
    token = client.post("/api/auth/login", json={"email": "audit_stage2_user@example.com", "password": "ValidPassword2026!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    date_str = "2026-10-15"

    # Add Breakfast
    b_res = client.post("/api/meals", json={
        "log_date": date_str,
        "meal_category": "breakfast",
        "food_name": "Oats with Milk",
        "serving_size": 1.0,
        "calories": 250.0,
        "protein": 10.0,
        "carbs": 40.0,
        "fat": 5.0
    }, headers=headers)
    assert b_res.status_code == 201
    meal_id = b_res.json()["meal_id"]

    # Verify Totals
    get_res = client.get(f"/api/meals?date={date_str}", headers=headers).json()
    assert get_res["totals"]["calories"] == 250.0
    assert get_res["totals"]["protein_g"] == 10.0

    # Delete Meal
    del_res = client.delete(f"/api/meals/{meal_id}", headers=headers)
    assert del_res.status_code == 200

    # Verify updated totals
    updated_res = client.get(f"/api/meals?date={date_str}", headers=headers).json()
    assert updated_res["totals"]["calories"] == 0.0

# --- 13. Water Tracking ---
def test_water_tracking():
    token = client.post("/api/auth/login", json={"email": "audit_stage2_user@example.com", "password": "ValidPassword2026!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    date_str = "2026-10-15"

    # Add water
    client.post("/api/water", json={"log_date": date_str, "amount_ml": 500}, headers=headers)
    client.post("/api/water", json={"log_date": date_str, "amount_ml": 250}, headers=headers)

    w_res = client.get(f"/api/water?date={date_str}", headers=headers).json()
    assert w_res["total_ml"] == 750
    assert w_res["glasses"] == 3.0

    # Reset
    client.delete(f"/api/water/reset?date={date_str}", headers=headers)
    w_reset = client.get(f"/api/water?date={date_str}", headers=headers).json()
    assert w_reset["total_ml"] == 0

# --- 14. Weight History ---
def test_weight_tracking():
    token = client.post("/api/auth/login", json={"email": "audit_stage2_user@example.com", "password": "ValidPassword2026!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/weight", json={"log_date": "2026-10-10", "weight_kg": 75.0, "notes": "Baseline"}, headers=headers)
    client.post("/api/weight", json={"log_date": "2026-10-15", "weight_kg": 74.2, "notes": "Down 0.8kg"}, headers=headers)

    res = client.get("/api/weight", headers=headers).json()
    assert res["count"] >= 2
    weights = [entry["weight_kg"] for entry in res["history"]]
    assert 75.0 in weights
    assert 74.2 in weights

# --- 15. Profile Update & Conversation Persistence Mocked ---
def test_profile_update_and_conversation():
    token = client.post("/api/auth/login", json={"email": "audit_stage2_user@example.com", "password": "ValidPassword2026!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update profile
    update_res = client.put("/api/profile", json={
        "age": 29,
        "daily_calorie_target": 2150,
        "goal": "muscle_gain",
        "dietary_preference": "vegetarian"
    }, headers=headers)
    assert update_res.status_code == 200

    prof = client.get("/api/profile", headers=headers).json()["profile"]
    assert prof["age"] == 29
    assert prof["daily_calorie_target"] == 2150

    # Create conversation and send message with mock
    conv_res = client.post("/api/conversations", json={"title": "High Protein Consult"}, headers=headers)
    conv_id = conv_res.json()["conversation_id"]

    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {"content": "For a vegetarian aiming for muscle gain, include paneer, soya chunks, and dal."}
        }
        msg_res = client.post(f"/api/conversations/{conv_id}/messages", json={"message": "Suggest protein foods"}, headers=headers)
        assert msg_res.status_code == 200
        assert "paneer" in msg_res.json()["reply"].lower()

    # Verify message persistence
    msgs = client.get(f"/api/conversations/{conv_id}", headers=headers).json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"

