# NutriAI — Intelligence-Powered Nutrition & Diet Platform

**NutriAI** is an enterprise-grade, full-stack nutrition assistant platform featuring a **FastAPI** backend, secure **SQLite** persistence, and private local LLM intelligence powered by **Ollama**.

Built specifically to support Indian and global dietary patterns, NutriAI delivers context-aware nutrition consultations, real database-backed meal and macro tracking, water logging, weight analytics, and user account security.

---

## 🌟 Key Capabilities & Implemented Features

### 1. 🧠 Personalized AI Nutrition Intelligence Engine
- **Hybrid Intelligence Architecture**: Combines deterministic SQLite data retrieval, Python-driven arithmetic, evidence-based recommendation logic, and local Ollama LLM reasoning.
- **Context-Aware Dialogue**: Automatically retrieves the authenticated user's profile metrics (age, height, weight, activity level, health goals, dietary preferences, explicit allergies), today's logged meals and macro totals, today's water status, and chronological weight trajectory.
- **Deterministic Arithmetic (No LLM Math)**: All calorie sums, macro breakdowns, remaining budgets, water glasses, and weight trends are computed with reliable Python arithmetic rather than relying on language model hallucination.
- **Evidence-Based Food Recommendations**: Recommends verified foods based on dietary compatibility (vegetarian, vegan, eggetarian, non-veg), strict allergy exclusions (dairy, nuts, gluten, soy, eggs), and user goals (muscle gain protein density vs fat loss satiety).
- **Personalized Daily Meal Plans**: Generates structured, validated daily meal plans (`🎯 Goal`, `🥣 Breakfast`, `🍛 Lunch`, `☕ Evening Snack`, `🌙 Dinner`, `💧 Water Intake`, `🏃 Exercise Tip`, `⚠️ Important Note`) with Python-calculated macro totals and 1-click dashboard saving.
- **Graceful Offline Fallback**: If Ollama is offline or times out, analytical queries (calories eaten today, water intake, weight progress, food recommendations, meal plans) automatically fall back to the deterministic data engine with zero user disruption.
- **Clinical Boundaries & Safety**: Clearly tags approximate values with `[Approximate AI Estimate]` and verified database items with `[Verified Database Record]`. Strictly refuses crash diets (<1200 kcal for women, <1500 kcal for men), and routes clinical conditions to healthcare professionals.

### 2. 🔐 Enterprise-Grade Security & Authentication
- **Argon2 Password Hashing**: Passwords are encrypted using OWASP-recommended Argon2id (`argon2-cffi`).
- **Legacy Account Migration**: Transparently verifies and migrates legacy plaintext accounts to Argon2 upon first login, automatically clearing plaintext fields.
- **Cryptographic Bearer Sessions**: Server-side session tokens stored in a dedicated `sessions` table with expiration, `HttpOnly`/`SameSite` cookies, and instant revocation on logout.
- **100% User Isolation**: Every database query is strictly scoped to `user_id`. Users cannot view or tamper with other users' meals, chats, plans, or metrics.
- **Protected Admin Directory**: The `/users` and `/api/admin/users` endpoints require an `admin` role; unauthorized users receive `403 Forbidden`.
- **Sliding-Window Rate Limiting**: Built-in sliding-window rate limiting on authentication and AI chat endpoints.

### 3. 📊 Real Nutrition Dashboard & Tracking (No Mock Data)
- **Meal & Macro Tracker**: Log meals across 4 daily categories with portion multipliers.
- **Verified Food Composition Database**: 34+ staple Indian and global foods with verified calories, protein, carbs, fat, dietary tags, and allergen metadata.
- **Water Consumption Tracker**: Track daily hydration with quick-add buttons (+250ml glass, +500ml bottle) and daily target progress bars.
- **Weight Progress & Interactive Chart**: Record weight measurements over time and visualize progress on an interactive SVG trend chart.
- **Profile & Target Customization**: Configure personal goals (fat loss, muscle gain), daily calorie target, and daily water target.

---

## 📁 Project Architecture & Structure

```
NutriAI/
├── main.py              # FastAPI application, CORS, static routes, and REST endpoints
├── database.py          # SQLite connection manager (WAL mode), migrations & food seeding
├── security.py          # Argon2 hashing, legacy migration, Bearer tokens, rate limiter
├── models.py            # Validated Pydantic v2 schemas
├── ai_service.py        # Ollama client, system prompts, and diet plan formatting
├── index.html           # Unified web application interface (Landing & Dashboard)
├── chat.html            # Clean redirect wrapper into full-featured chat workspace
├── users.html           # Protected administrative user directory (XSS-safe DOM)
├── script.js            # Client-side state, API communication, SVG charts & DOM logic
├── style.css            # Cohesive, modern, accessible design system & dark theme
├── users.db             # SQLite database file
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
├── .gitignore           # Git ignore rules for caches, venvs, and secrets
└── tests/
    └── test_nutriai.py  # Automated pytest suite (11 comprehensive integration tests)
```

---

## 🛠️ Prerequisites

1. **Python**: Python 3.10+ (tested on Python 3.13 and Python 3.14 on Windows).
2. **Ollama**: Installed and running locally ([ollama.com](https://ollama.com)).
   - Pull at least one model:
     ```powershell
     ollama pull llama3.2:3b
     # Or for higher capacity:
     ollama pull qwen3:8b
     ```

---

## 🚀 Installation & Startup (Windows / PowerShell)

### 1. Clone or Navigate to the Workspace
```powershell
cd "c:\Users\adity\Coding\AI ML Project\NutriAI"
```

### 2. Install Python Dependencies
```powershell
python -m pip install -r requirements.txt
```

### 3. Ensure Ollama is Running
In a separate terminal or background process:
```powershell
ollama serve
```

### 4. Start the NutriAI Backend Server
```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 5. Access the Web Application
Open your browser and navigate to:
```
http://127.0.0.1:8000
```
*(The backend serves the frontend files directly. You can also open `index.html` via VS Code Live Server at port 5500).*

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` if custom configuration is needed:

| Variable | Default Value | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama service endpoint |
| `OLLAMA_MODEL` | `llama3.2:3b` | Target local model (auto-detected if omitted) |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Trusted CORS origins |
| `NUTRI_DB_PATH` | `users.db` | Path to SQLite database file |

---

## 📡 REST API Reference

### Health & Auth
- `GET /api/health` — Check server, SQLite connection, and Ollama status.
- `POST /api/auth/signup` — Create a new account with Argon2 password hashing.
- `POST /api/auth/login` — Authenticate and obtain Bearer session token.
- `POST /api/auth/logout` — Revoke session token.
- `GET /api/auth/me` — Get current user identity.

### Nutrition & Tracking
- `GET /api/foods?query=` — Search verified food composition database with dietary tags and allergens.
- `GET /api/meals?date=YYYY-MM-DD` — Get daily meals and macro totals vs targets.
- `POST /api/meals` — Log a meal entry.
- `DELETE /api/meals/{id}` — Delete a meal entry.
- `GET /api/water?date=YYYY-MM-DD` — Get water intake vs target.
- `POST /api/water` — Log water intake (+250ml, +500ml).
- `DELETE /api/water/reset?date=YYYY-MM-DD` — Reset daily water log.
- `GET /api/weight` — Retrieve chronological weight history for charts.
- `POST /api/weight` — Log new weight measurement.

### AI Intelligence, Recommendations & Plans
- `GET /api/recommendations?category=` — Get personalized food recommendations matching goals and dietary preferences with strict allergy exclusion.
- `POST /api/plans/generate` — Generate a personalized daily meal plan with verified foods and Python-calculated macro totals.
- `GET /api/plans` — List saved diet plans.
- `POST /api/plans` — Save an AI diet plan to the dashboard.
- `DELETE /api/plans/{id}` — Delete a saved diet plan.
- `GET /api/conversations` — List user's isolated consultations.
- `POST /api/conversations` — Start a new consultation.
- `GET /api/conversations/{id}` — Retrieve conversation messages.
- `DELETE /api/conversations/{id}` — Delete consultation.
- `POST /api/conversations/{id}/messages` — Send message and receive context-grounded AI response (with deterministic offline fallback).

### Profile & Admin
- `GET /api/profile` & `PUT /api/profile` — Manage user metrics, dietary restrictions, and goals.
- `GET /api/admin/users` — Admin-only user directory (requires `role: 'admin'`).

---

## 🧪 Automated Testing

NutriAI includes an automated test suite containing **32 tests** verifying all security boundaries, database migrations, deterministic calculations, context retrieval, personalization ranking, conversational memory, and AI fallbacks.

Run the entire test suite using `pytest`:
```powershell
python -m pytest tests/ -v
```

### Test Suite Structure (32 Tests Executed & Passed):
1. **Core Platform & Security Suite (`tests/test_nutriai.py` — 15 Tests)**:
   - `test_application_startup_and_health`: Health diagnostics and DB connectivity.
   - `test_signup_validation_and_duplicate_prevention`: Password rules and duplicate prevention.
   - `test_database_migration_against_copy`: Verifies legacy password migration and plaintext clearing against a copy.
   - `test_unauthorized_endpoints`: Verifies 401 Unauthorized boundary on protected endpoints.
   - `test_admin_access_control`: Verifies 403 Forbidden on admin directory.
   - `test_user_data_isolation`: Confirms multi-tenant isolation (User A cannot view User B).
   - `test_session_revocation_on_logout`: Server-side token revocation and cookie clearing.
   - `test_guest_chat_validation_and_capping`: Empty input rejection and 500-char guest capping.
   - `test_chat_reset_endpoints`: Resets consultation for authenticated sessions and guests.
   - `test_ai_service_deterministic_mock_and_failures`: Mocked Ollama success, timeout, and connection errors.
   - `test_legacy_route_rate_limiting`: 429 rate limit enforcement on `/login` and `/chat`.
   - `test_meal_lifecycle_and_totals`: Meal logging, macro sums, and deletions.
   - `test_water_tracking`: Water logging and resets.
   - `test_weight_tracking`: Chronological weight metrics.
   - `test_profile_update_and_conversation`: Profile syncing and conversation persistence.

2. **Advanced AI Intelligence & Personalization Suite (`tests/test_ai_intelligence.py` — 17 Tests)**:
   - `test_context_retrieval_and_user_isolation`: Authenticated user context retrieval and multi-tenant scoping.
   - `test_context_date_boundary_separation`: Date boundary isolation (today vs historical meals).
   - `test_missing_profile_fields_handling`: Graceful handling of missing fields without hallucinating fake data.
   - `test_daily_nutrition_calculations`: Exact Python arithmetic for calories, protein, carbs, fat, and targets.
   - `test_missing_nutrition_values_handling`: Handling meals with missing values transparently.
   - `test_water_and_weight_trend_calculations`: Water glasses and multi-entry weight trajectory detection.
   - `test_serving_size_conversions`: Exact portion multiplier scaling.
   - `test_recommendation_dietary_preference_filtering`: Vegetarian strictly excludes poultry/eggs; vegan excludes dairy.
   - `test_recommendation_allergy_exclusion`: Strict allergen filtering (dairy, nuts, gluten, soy, eggs).
   - `test_recommendation_goal_ranking`: Muscle gain vs fat loss evidence-based ranking.
   - `test_intent_detection_patterns`: Intent detection regex and keyword routing.
   - `test_conversational_follow_up_persistence`: Resolves follow-up queries ("another option", "more protein").
   - `test_personalized_meal_plan_generation`: Plan structure validation and Python-calculated day totals.
   - `test_meal_plan_generation_api_endpoint`: `/api/plans/generate` endpoint and dashboard save flow.
   - `test_ollama_offline_fallback_to_deterministic_calculations`: Offline Ollama fallback to exact daily calculations.
   - `test_ollama_timeout_fallback_to_recommendations`: Timeout fallback to verified food recommendations.
   - `test_general_query_offline_guidance`: Friendly guidance to start Ollama for open-ended queries.

---

## 🔧 Troubleshooting Guide

| Issue | Cause | Solution |
|---|---|---|
| `Ollama is not responding` | Ollama daemon is offline | Run `ollama serve` in a terminal window. |
| `Model not found` | Desired model not downloaded | Run `ollama pull llama3.2:3b`. |
| `Port 8000 already in use` | Another process is using port 8000 | Run `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess` or run uvicorn on `--port 8001`. |
| `401 Unauthorized` in frontend | Session expired or token missing | Log in again through the Login modal. |
| `403 Forbidden` on `/users.html` | Account role is not admin | Standard user accounts are blocked by design. Set `role = 'admin'` in `users` table for administrators. |

---

## 🛡️ Security Limitations & Best Practices

## 🔒 Safe Handling of Databases & Migrations

- **Clean Initialization**: Fresh installations automatically initialize a pristine SQLite database containing all schemas and the 34 verified food items on first launch. No manual SQL scripts required.
- **Demo Data Workflow**: To seed a test account for offline evaluation without real data:
  ```powershell
  $env:SEED_DEMO="1"
  python database.py
  ```
  *(Creates `demo@nutriai.local` with password `DemoNutri2026!` and a sample fitness profile).*
- **Legacy Database Migration**: If upgrading an existing `users.db`:
  - Existing account rows, meal logs, and metrics are preserved intact.
  - When legacy accounts log in with their old plaintext password, NutriAI validates the password, computes an Argon2 hash, saves it to `password_hash`, and immediately clears the plaintext `password` column (`password = NULL`).
- **Data Protection**: Live databases (`users.db`, `*.db`) are ignored in `.gitignore` and excluded from distributable archives to guarantee zero credential exposure.

---

## 🛡️ Security Limitations & Best Practices

- **Session Tokens**: Uses cryptographically secure 32-byte tokens (`secrets.token_urlsafe(32)`) stored with timestamps in SQLite.
- **Cookie Security in Production**: In production, set `ENVIRONMENT=production` in `.env` to automatically enforce the `Secure` flag on cookies:
  ```ini
  ENVIRONMENT=production
  COOKIE_SECURE=true
  ```
- **CSRF Defense**: State-changing requests using cookie authentication enforce `Sec-Fetch-Site` validation. Frontend API requests communicate using `Authorization: Bearer <token>` headers, which are inherently protected against CSRF.
- **Database Backup**: Keep regular backups of `users.db`. The database operates in SQLite WAL mode for concurrency safety.
