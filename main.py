import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import init_db, get_db
from security import (
    validate_email,
    validate_password,
    hash_password,
    verify_and_migrate_password,
    create_session,
    revoke_session,
    set_session_cookie,
    clear_session_cookie,
    get_current_user,
    get_optional_user,
    require_admin,
    rate_limit,
)
from models import (
    SignupRequest,
    LoginRequest,
    ProfileUpdateRequest,
    MealCreateRequest,
    WaterCreateRequest,
    WeightCreateRequest,
    PlanSaveRequest,
    ConversationCreateRequest,
    ChatMessageRequest,
)
from ai_service import (
    generate_nutrition_reply,
    get_available_ollama_model,
    diagnose_ollama,
)

logger = logging.getLogger("nutriai.main")

# Initialize database schema on startup
init_db()

app = FastAPI(
    title="NutriAI Platform API",
    description="Enterprise-grade AI Nutritionist & Health Intelligence Platform",
    version="2.1.0"
)

# CORS configuration: trusted specific origins
ALLOWED_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# --- 1. HEALTH & SYSTEM DIAGNOSTICS ---

@app.get("/api/health")
def health_check():
    """Health check endpoint reporting DB connectivity and Ollama diagnostics."""
    db_ok = False
    try:
        with get_db() as conn:
            conn.execute("SELECT 1;").fetchone()
            db_ok = True
    except Exception:
        db_ok = False

    ai_diag = diagnose_ollama()
    is_healthy = db_ok and ai_diag.get("status") == "online"

    return {
        "status": "healthy" if is_healthy else "degraded",
        "database": "connected" if db_ok else "error",
        "ai_engine": ai_diag,
        "active_model": ai_diag.get("active_model"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# --- 2. AUTHENTICATION SERVICE & ENDPOINTS ---

def service_signup(req: SignupRequest, response: Response) -> dict:
    """Core registration business logic separated from route handlers."""
    clean_email = validate_email(req.email)
    valid_password = validate_password(req.password)
    clean_name = req.name.strip()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?;", (clean_email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

        hashed_pw = hash_password(valid_password)
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role)
            VALUES (?, ?, ?, 'user');
        """, (clean_name, clean_email, hashed_pw))
        user_id = cursor.lastrowid

        # Bootstrap default user profile
        cursor.execute("""
            INSERT OR IGNORE INTO user_profiles (user_id, daily_calorie_target, daily_water_target_ml)
            VALUES (?, 2000, 2500);
        """, (user_id,))

    session_token = create_session(user_id)
    set_session_cookie(response, session_token)

    return {
        "message": "Registration successful.",
        "token": session_token,
        "user": {
            "id": user_id,
            "name": clean_name,
            "email": clean_email,
            "role": "user"
        }
    }

def service_login(req: LoginRequest, response: Response) -> dict:
    """Core login and password verification logic with transparent Argon2 migration."""
    clean_email = validate_email(req.email)
    candidate_password = req.password

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, email, password_hash, password, role
            FROM users 
            WHERE email = ?;
        """, (clean_email,))
        user_row = cursor.fetchone()

        if not user_row:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        is_valid = verify_and_migrate_password(
            conn=conn,
            user_id=user_row["id"],
            candidate_password=candidate_password,
            password_hash=user_row["password_hash"],
            legacy_plain=user_row["password"]
        )

        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        user_id = user_row["id"]
        user_name = user_row["name"]
        user_role = user_row["role"] or "user"

    session_token = create_session(user_id)
    set_session_cookie(response, session_token)

    return {
        "message": "Login successful.",
        "token": session_token,
        "user": {
            "id": user_id,
            "name": user_name,
            "email": clean_email,
            "role": user_role
        }
    }

@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))])
def api_signup(req: SignupRequest, response: Response):
    return service_signup(req, response)

@app.post("/api/auth/login", dependencies=[Depends(rate_limit(max_requests=15, window_seconds=60))])
def api_login(req: LoginRequest, response: Response):
    return service_login(req, response)

# Legacy alias endpoints with explicit rate limiting
@app.post("/signup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))])
def legacy_signup(req: SignupRequest, response: Response):
    return service_signup(req, response)

@app.post("/login", dependencies=[Depends(rate_limit(max_requests=15, window_seconds=60))])
def legacy_login(req: LoginRequest, response: Response):
    return service_login(req, response)

@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    """Revokes session token and clears auth cookie."""
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    elif "session_token" in request.cookies:
        token = request.cookies.get("session_token")

    if token:
        revoke_session(token)

    clear_session_cookie(response)
    return {"message": "Logged out successfully."}

@app.get("/api/auth/me")
def api_current_user(current_user: dict = Depends(get_current_user)):
    """Returns profile info for currently authenticated user."""
    return {"user": current_user}

# Protected admin endpoints
@app.get("/api/admin/users")
def get_all_users_admin(admin: dict = Depends(require_admin)):
    """Admin-only endpoint to inspect user accounts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role, created_at FROM users ORDER BY id ASC;")
        users = [dict(row) for row in cursor.fetchall()]
        return {"users": users, "total": len(users)}

@app.get("/users")
def get_users_protected(user: dict = Depends(get_current_user)):
    """Protected user directory endpoint requiring administrator role."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Administrator privilege required.")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role, created_at FROM users ORDER BY id ASC;")
        return {"users": [dict(r) for r in cursor.fetchall()]}

# --- 3. USER PROFILE & TARGETS ---

@app.get("/api/profile")
def get_profile(current_user: dict = Depends(get_current_user)):
    """Fetches user metrics, dietary restrictions, and daily targets."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?;", (current_user["id"],))
        profile_row = cursor.fetchone()
        if not profile_row:
            cursor.execute("""
                INSERT INTO user_profiles (user_id, daily_calorie_target, daily_water_target_ml)
                VALUES (?, 2000, 2500);
            """, (current_user["id"],))
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?;", (current_user["id"],))
            profile_row = cursor.fetchone()
        return {"profile": dict(profile_row), "user": current_user}

@app.put("/api/profile")
def update_profile(req: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Updates user goals, calories, water targets, and dietary preferences."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return {"message": "No fields to update."}

    fields = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [datetime.now(timezone.utc).isoformat(), current_user["id"]]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE user_profiles 
            SET {fields}, updated_at = ?
            WHERE user_id = ?;
        """, values)

    return {"message": "Profile updated successfully.", "updated_fields": list(updates.keys())}

# --- 4. FOOD DATABASE & MEAL TRACKING ---

@app.get("/api/foods")
def search_foods(query: Optional[str] = "", current_user: dict = Depends(get_current_user)):
    """Searches verified food composition dataset with source attribution."""
    with get_db() as conn:
        cursor = conn.cursor()
        if query and query.strip():
            search_term = f"%{query.strip()}%"
            cursor.execute("""
                SELECT *, 'Verified Composition Dataset' as attribution FROM food_items 
                WHERE name LIKE ? OR category LIKE ? 
                ORDER BY name ASC LIMIT 25;
            """, (search_term, search_term))
        else:
            cursor.execute("SELECT *, 'Verified Composition Dataset' as attribution FROM food_items ORDER BY category, name ASC LIMIT 50;")
        return {"foods": [dict(r) for r in cursor.fetchall()]}

@app.get("/api/meals")
def get_meals(date: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Returns meals logged by user for specified date alongside daily target progress."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM meal_logs 
            WHERE user_id = ? AND log_date = ?
            ORDER BY id ASC;
        """, (current_user["id"], target_date))
        meal_rows = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT daily_calorie_target FROM user_profiles WHERE user_id = ?;", (current_user["id"],))
        profile_row = cursor.fetchone()
        calorie_target = profile_row["daily_calorie_target"] if profile_row else 2000

    categories = {"breakfast": [], "lunch": [], "snack": [], "dinner": []}
    total_calories = 0.0
    total_protein = 0.0
    total_carbs = 0.0
    total_fat = 0.0

    for m in meal_rows:
        cat = m["meal_category"].lower()
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(m)

        total_calories += m["calories"]
        total_protein += m["protein"]
        total_carbs += m["carbs"]
        total_fat += m["fat"]

    return {
        "date": target_date,
        "meals_by_category": categories,
        "all_meals": meal_rows,
        "totals": {
            "calories": round(total_calories, 1),
            "protein_g": round(total_protein, 1),
            "carbs_g": round(total_carbs, 1),
            "fat_g": round(total_fat, 1),
            "calorie_target": calorie_target,
            "progress_percent": min(100.0, round((total_calories / calorie_target) * 100, 1)) if calorie_target > 0 else 0
        }
    }

@app.post("/api/meals", status_code=status.HTTP_201_CREATED)
def add_meal(req: MealCreateRequest, current_user: dict = Depends(get_current_user)):
    """Logs a new meal entry for the user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO meal_logs 
            (user_id, log_date, meal_category, food_name, serving_size, calories, protein, carbs, fat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            current_user["id"],
            req.log_date,
            req.meal_category.lower(),
            req.food_name.strip(),
            req.serving_size,
            req.calories,
            req.protein,
            req.carbs,
            req.fat
        ))
        meal_id = cursor.lastrowid

    return {"message": "Meal logged successfully.", "meal_id": meal_id}

@app.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int, current_user: dict = Depends(get_current_user)):
    """Deletes an existing meal entry owned by authenticated user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM meal_logs WHERE id = ? AND user_id = ?;", (meal_id, current_user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Meal entry not found or unauthorized.")
    return {"message": "Meal entry deleted successfully."}

# --- 5. WATER TRACKING ---

@app.get("/api/water")
def get_water(date: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Returns total water intake for date alongside daily target."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(amount_ml) as total_ml FROM water_logs 
            WHERE user_id = ? AND log_date = ?;
        """, (current_user["id"], target_date))
        total_ml = cursor.fetchone()["total_ml"] or 0

        cursor.execute("SELECT daily_water_target_ml FROM user_profiles WHERE user_id = ?;", (current_user["id"],))
        profile_row = cursor.fetchone()
        water_target = profile_row["daily_water_target_ml"] if profile_row else 2500

    return {
        "date": target_date,
        "total_ml": total_ml,
        "target_ml": water_target,
        "glasses": round(total_ml / 250.0, 1),
        "target_glasses": round(water_target / 250.0, 1),
        "progress_percent": min(100.0, round((total_ml / water_target) * 100, 1)) if water_target > 0 else 0
    }

@app.post("/api/water", status_code=status.HTTP_201_CREATED)
def add_water(req: WaterCreateRequest, current_user: dict = Depends(get_current_user)):
    """Records water consumption."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO water_logs (user_id, log_date, amount_ml)
            VALUES (?, ?, ?);
        """, (current_user["id"], req.log_date, req.amount_ml))
        log_id = cursor.lastrowid
    return {"message": "Water intake logged.", "log_id": log_id}

@app.delete("/api/water/reset")
def reset_water_today(date: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Clears water logs for specified date."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM water_logs WHERE user_id = ? AND log_date = ?;", (current_user["id"], target_date))
    return {"message": "Water log reset for the day."}

# --- 6. WEIGHT & PROGRESS TRACKING ---

@app.get("/api/weight")
def get_weight_history(current_user: dict = Depends(get_current_user)):
    """Returns chronological list of recorded weight measurements for charts."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, log_date, weight_kg, notes 
            FROM weight_logs 
            WHERE user_id = ? 
            ORDER BY log_date ASC, id ASC;
        """, (current_user["id"],))
        rows = [dict(r) for r in cursor.fetchall()]

    return {"history": rows, "count": len(rows)}

@app.post("/api/weight", status_code=status.HTTP_201_CREATED)
def add_weight(req: WeightCreateRequest, current_user: dict = Depends(get_current_user)):
    """Records a new weight measurement."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO weight_logs (user_id, log_date, weight_kg, notes)
            VALUES (?, ?, ?, ?);
        """, (current_user["id"], req.log_date, req.weight_kg, req.notes or ""))
        log_id = cursor.lastrowid

        cursor.execute("""
            UPDATE user_profiles 
            SET weight_kg = ?, updated_at = ?
            WHERE user_id = ?;
        """, (req.weight_kg, datetime.now(timezone.utc).isoformat(), current_user["id"]))

    return {"message": "Weight measurement recorded.", "log_id": log_id}

# --- 7. SAVED DIET PLANS & MEAL PLAN GENERATION ---

@app.get("/api/plans")
def get_saved_plans(current_user: dict = Depends(get_current_user)):
    """Lists saved diet plans for user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, plan_content, created_at 
            FROM diet_plans 
            WHERE user_id = ? 
            ORDER BY id DESC;
        """, (current_user["id"],))
        plans = [dict(r) for r in cursor.fetchall()]
    return {"plans": plans}

@app.post("/api/plans", status_code=status.HTTP_201_CREATED)
def save_diet_plan(req: PlanSaveRequest, current_user: dict = Depends(get_current_user)):
    """Saves an AI-generated or custom diet plan."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO diet_plans (user_id, title, plan_content)
            VALUES (?, ?, ?);
        """, (current_user["id"], req.title.strip(), req.plan_content.strip()))
        plan_id = cursor.lastrowid
    return {"message": "Diet plan saved.", "plan_id": plan_id}

@app.post("/api/plans/generate")
def api_generate_meal_plan(current_user: dict = Depends(get_current_user)):
    """
    Generates a personalized daily meal plan with verified foods and Python-calculated macros.
    Validates meal composition against user dietary preference and allergies.
    """
    from nutrition_engine import build_user_nutrition_context, generate_personalized_meal_plan
    user_ctx = build_user_nutrition_context(current_user["id"])
    plan = generate_personalized_meal_plan(user_ctx)
    return {"plan": plan}

@app.delete("/api/plans/{plan_id}")
def delete_diet_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Deletes a saved diet plan."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM diet_plans WHERE id = ? AND user_id = ?;", (plan_id, current_user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Diet plan not found or unauthorized.")
    return {"message": "Diet plan deleted."}

@app.get("/api/recommendations")
def get_food_recommendations(category: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """
    Provides evidence-based food recommendations matching user goals,
    dietary preferences, and excluding known allergens.
    """
    from nutrition_engine import build_user_nutrition_context, recommend_foods
    user_ctx = build_user_nutrition_context(current_user["id"])
    recs = recommend_foods(user_ctx, category=category, top_n=6)
    return {
        "recommendations": recs,
        "goal": user_ctx.profile.get("goal"),
        "dietary_preference": user_ctx.profile.get("dietary_preference")
    }

# --- 8. AI NUTRITIONIST & CHAT CONVERSATIONS ---

@app.get("/api/conversations")
def list_conversations(current_user: dict = Depends(get_current_user)):
    """Returns conversation list belonging to current user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, created_at, updated_at 
            FROM conversations 
            WHERE user_id = ? 
            ORDER BY updated_at DESC;
        """, (current_user["id"],))
        rows = [dict(r) for r in cursor.fetchall()]
    return {"conversations": rows}

@app.post("/api/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(req: ConversationCreateRequest, current_user: dict = Depends(get_current_user)):
    """Creates a new isolated conversation."""
    conv_id = str(uuid.uuid4())
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?);
        """, (conv_id, current_user["id"], req.title or "Nutrition Consultation", now_str, now_str))

    return {"conversation_id": conv_id, "title": req.title}

@app.get("/api/conversations/{conversation_id}")
def get_conversation_messages(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """Loads all messages for the specified conversation."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title FROM conversations 
            WHERE id = ? AND user_id = ?;
        """, (conversation_id, current_user["id"]))
        conv = cursor.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found or unauthorized.")

        cursor.execute("""
            SELECT id, role, content, created_at 
            FROM messages 
            WHERE conversation_id = ? AND user_id = ? 
            ORDER BY id ASC;
        """, (conversation_id, current_user["id"]))
        messages = [dict(r) for r in cursor.fetchall()]

    return {"conversation": dict(conv), "messages": messages}

@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    """Deletes conversation and associated message history."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?;", (conversation_id, current_user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found or unauthorized.")
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?;", (conversation_id,))
    return {"message": "Conversation deleted."}

@app.post("/api/conversations/{conversation_id}/messages", dependencies=[Depends(rate_limit(max_requests=25, window_seconds=60))])
def send_message(conversation_id: str, req: ChatMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    Sends message to Ollama within user conversation context.
    Grounds response with authenticated user metrics, meal logs, and verified database items.
    Persists user message and assistant reply to database.
    """
    from nutrition_engine import build_user_nutrition_context

    clean_msg = req.message.strip()
    if not clean_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM conversations WHERE id = ? AND user_id = ?;", (conversation_id, current_user["id"]))
        conv = cursor.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        cursor.execute("""
            SELECT role, content FROM messages 
            WHERE conversation_id = ? AND user_id = ? 
            ORDER BY id ASC;
        """, (conversation_id, current_user["id"]))
        history = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?;", (current_user["id"],))
        profile_row = cursor.fetchone()
        profile_data = dict(profile_row) if profile_row else None

        cursor.execute("""
            INSERT INTO messages (conversation_id, user_id, role, content)
            VALUES (?, ?, 'user', ?);
        """, (conversation_id, current_user["id"], clean_msg))

        if conv["title"] in ["New Nutrition Consultation", "Nutrition Consultation", "New Plan"]:
            short_title = clean_msg[:40] + ("..." if len(clean_msg) > 40 else "")
            cursor.execute("UPDATE conversations SET title = ? WHERE id = ?;", (short_title, conversation_id))

    history.append({"role": "user", "content": clean_msg})

    # Retrieve live authenticated nutrition context
    user_context = build_user_nutrition_context(current_user["id"])

    ai_result = generate_nutrition_reply(
        messages=history,
        profile=profile_data,
        user_context=user_context
    )
    reply_content = ai_result["reply"]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO messages (conversation_id, user_id, role, content)
            VALUES (?, ?, 'assistant', ?);
        """, (conversation_id, current_user["id"], reply_content))
        cursor.execute("""
            UPDATE conversations 
            SET updated_at = ? 
            WHERE id = ?;
        """, (now_str, conversation_id))

    return {
        "reply": reply_content,
        "model": ai_result.get("model", "llama3.2:3b"),
        "status": ai_result.get("status", "success"),
        "intent": ai_result.get("intent", "general_nutrition")
    }

# Rate-limited single endpoint /chat supporting authenticated session or strictly-capped guest mode
@app.post("/chat", dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))])
def legacy_chat(req: ChatMessageRequest, user: Optional[dict] = Depends(get_optional_user)):
    """
    Backwards compatibility endpoint for the hero chat preview and legacy requests.
    Supports authenticated users with isolated memory, or strictly capped guest inquiries.
    """
    clean_text = req.message.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if user:
        # Authenticated flow: use active conversation
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1;", (user["id"],))
            row = cursor.fetchone()
            if row:
                conv_id = row["id"]
            else:
                conv_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO conversations (id, user_id, title)
                    VALUES (?, ?, ?);
                """, (conv_id, user["id"], "General Consultation"))
        return send_message(conv_id, req, current_user=user)
    else:
        # Anonymous Guest flow: enforce strict length check to avoid resource exhaustion
        if len(clean_text) > 500:
            raise HTTPException(
                status_code=400,
                detail="Guest inquiries are limited to 500 characters. Please sign up or log in for unlimited consultations."
            )
        ai_res = generate_nutrition_reply(messages=[{"role": "user", "content": clean_text}])
        return {
            "reply": ai_res["reply"],
            "model": ai_res.get("model", "llama3.2:3b"),
            "attribution": "Approximate AI Estimate"
        }

@app.post("/chat/reset")
def legacy_chat_reset(user: Optional[dict] = Depends(get_optional_user)):
    """
    Properly resets conversational state for authenticated users by provisioning a fresh consultation,
    or signals clean state for guest callers.
    """
    if user:
        new_conv_id = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, 'New Consultation', ?, ?);
            """, (new_conv_id, user["id"], now_str, now_str))
        return {
            "message": "Consultation history reset. New session started.",
            "conversation_id": new_conv_id
        }

    return {"message": "Guest consultation reset."}

# --- 9. STATIC WEB APPLICATION ROUTING ---

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

@app.get("/chat.html")
def serve_chat_html():
    return FileResponse(os.path.join(os.path.dirname(__file__), "chat.html"))

@app.get("/users.html")
def serve_users_html():
    return FileResponse(os.path.join(os.path.dirname(__file__), "users.html"))

# Mount directory for CSS, JS, and static assets
app.mount("/", StaticFiles(directory=os.path.dirname(__file__), html=True), name="static")