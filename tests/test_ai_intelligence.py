"""
NutriAI — Automated Test Suite for Advanced AI Intelligence & Personalization
Tests context engine retrieval, deterministic calculations, recommendation ranking,
dietary & allergy safety, conversational memory, meal plan validation, and Ollama failure fallbacks.
"""

import pytest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient

from main import app
from database import get_db, init_db
from security import _rate_limit_store
from nutrition_engine import (
    build_user_nutrition_context,
    calculate_daily_nutrition,
    calculate_water_summary,
    calculate_weight_trends,
    calculate_serving_nutrition,
    detect_intent,
    recommend_foods,
    generate_personalized_meal_plan,
    generate_deterministic_response,
    format_context_for_prompt,
    UserNutritionContext
)

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Clears in-memory rate limiting store before and after each test."""
    _rate_limit_store.clear()
    yield
    _rate_limit_store.clear()

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    init_db()

@pytest.fixture(scope="module")
def auth_user_pair():
    """Provisions two isolated test users with distinct dietary goals."""
    _rate_limit_store.clear()
    email_a = "ai_test_alice_veg@example.com"
    email_b = "ai_test_bob_meat@example.com"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE email IN (?, ?);", (email_a, email_b))

    res_a = client.post("/api/auth/signup", json={"name": "Alice Veg", "email": email_a, "password": "AlicePassword123!"})
    token_a = res_a.json()["token"]
    id_a = res_a.json()["user"]["id"]

    res_b = client.post("/api/auth/signup", json={"name": "Bob Meat", "email": email_b, "password": "BobPassword123!"})
    token_b = res_b.json()["token"]
    id_b = res_b.json()["user"]["id"]

    # Configure User A: Vegetarian, Muscle Gain, Dairy Allergy
    client.put("/api/profile", json={
        "age": 28,
        "weight_kg": 65.0,
        "height_cm": 172.0,
        "goal": "muscle_gain",
        "dietary_preference": "vegetarian",
        "allergies": "dairy",
        "daily_calorie_target": 2200,
        "daily_water_target_ml": 3000
    }, headers={"Authorization": f"Bearer {token_a}"})

    # Configure User B: Non-veg, Fat Loss, Nut Allergy
    client.put("/api/profile", json={
        "age": 35,
        "weight_kg": 85.0,
        "height_cm": 180.0,
        "goal": "fat_loss",
        "dietary_preference": "non_veg",
        "allergies": "nuts, peanuts",
        "daily_calorie_target": 1800,
        "daily_water_target_ml": 2500
    }, headers={"Authorization": f"Bearer {token_b}"})

    return {
        "user_a": {"id": id_a, "email": email_a, "token": token_a},
        "user_b": {"id": id_b, "email": email_b, "token": token_b}
    }

# ==============================================================================
# 1. CONTEXT ENGINE & MULTI-TENANT ISOLATION TESTS
# ==============================================================================

def test_context_retrieval_and_user_isolation(auth_user_pair):
    user_a = auth_user_pair["user_a"]
    user_b = auth_user_pair["user_b"]
    today = "2026-10-15"

    # User A logs meal and water
    client.post("/api/meals", json={
        "log_date": today,
        "meal_category": "breakfast",
        "food_name": "Oats with Berries",
        "serving_size": 1.0,
        "calories": 250.0,
        "protein": 8.0,
        "carbs": 45.0,
        "fat": 4.0
    }, headers={"Authorization": f"Bearer {user_a['token']}"})

    client.post("/api/water", json={"log_date": today, "amount_ml": 500}, headers={"Authorization": f"Bearer {user_a['token']}"})

    # Build context for User A
    ctx_a = build_user_nutrition_context(user_a["id"], target_date=today)
    assert ctx_a.user_id == user_a["id"]
    assert ctx_a.profile["goal"] == "muscle_gain"
    assert ctx_a.profile["dietary_preference"] == "vegetarian"
    assert len(ctx_a.today_meals) >= 1
    assert any(m["food_name"] == "Oats with Berries" for m in ctx_a.today_meals)
    assert ctx_a.today_water["total_ml"] >= 500

    # Build context for User B (must have 0 meals and 0 water from User A)
    ctx_b = build_user_nutrition_context(user_b["id"], target_date=today)
    assert ctx_b.user_id == user_b["id"]
    assert ctx_b.profile["goal"] == "fat_loss"
    assert len(ctx_b.today_meals) == 0
    assert ctx_b.today_nutrition["total_calories"] == 0.0
    assert ctx_b.today_water["total_ml"] == 0

def test_context_date_boundary_separation(auth_user_pair):
    user_a = auth_user_pair["user_a"]
    test_today = "2026-10-20"
    test_yesterday = "2026-10-19"

    # Log meal today
    client.post("/api/meals", json={
        "log_date": test_today,
        "meal_category": "lunch",
        "food_name": "Today Paneer Sabzi",
        "serving_size": 1.0,
        "calories": 300.0,
        "protein": 15.0,
        "carbs": 10.0,
        "fat": 15.0
    }, headers={"Authorization": f"Bearer {user_a['token']}"})

    # Log meal yesterday
    client.post("/api/meals", json={
        "log_date": test_yesterday,
        "meal_category": "dinner",
        "food_name": "Yesterday Moong Dal",
        "serving_size": 1.0,
        "calories": 180.0,
        "protein": 10.0,
        "carbs": 25.0,
        "fat": 3.0
    }, headers={"Authorization": f"Bearer {user_a['token']}"})

    ctx = build_user_nutrition_context(user_a["id"], target_date=test_today)
    # Yesterday's meal must NOT be included in today's total calories
    assert all(m["log_date"] == test_today for m in ctx.today_meals)
    assert any(m["food_name"] == "Yesterday Moong Dal" for m in ctx.recent_meals)
    assert ctx.today_nutrition["total_calories"] == 300.0

def test_missing_profile_fields_handling():
    # User with empty profile
    ctx = UserNutritionContext(
        user_id=9999,
        user_name="Incomplete User",
        user_email="inc@example.com",
        profile={},
        today_date="2026-10-15",
        today_meals=[],
        today_nutrition={"total_calories": 0.0, "total_protein_g": 0.0, "total_carbs_g": 0.0, "total_fat_g": 0.0},
        recent_meals=[],
        today_water={"total_ml": 0, "target_ml": 2500, "glasses": 0.0, "target_glasses": 10.0},
        weight_trends={"count": 0, "trend": "no_data"},
        saved_plans=[],
        missing_fields=["health goal", "age", "weight", "height"]
    )
    prompt_str = format_context_for_prompt(ctx)
    assert "Not provided" in prompt_str
    assert "None logged yet today" in prompt_str
    assert "0.0 kcal consumed so far" in prompt_str

# ==============================================================================
# 2. DETERMINISTIC NUTRITION CALCULATIONS TESTS
# ==============================================================================

def test_daily_nutrition_calculations():
    meals = [
        {"food_name": "Roti", "calories": 104.0, "protein": 3.1, "carbs": 20.0, "fat": 0.9, "meal_category": "lunch"},
        {"food_name": "Dal", "calories": 148.0, "protein": 9.2, "carbs": 22.0, "fat": 2.5, "meal_category": "lunch"},
        {"food_name": "Apple", "calories": 95.0, "protein": 0.5, "carbs": 25.0, "fat": 0.3, "meal_category": "snack"},
    ]
    calc = calculate_daily_nutrition(meals, calorie_target=2000)
    assert calc["meal_count"] == 3
    assert calc["total_calories"] == 347.0
    assert calc["total_protein_g"] == 12.8
    assert calc["total_carbs_g"] == 67.0
    assert calc["total_fat_g"] == 3.7
    assert calc["remaining_calories"] == 1653.0
    assert calc["progress_percent"] in [17.3, 17.4]
    assert calc["has_missing_data"] is False

def test_missing_nutrition_values_handling():
    meals = [
        {"food_name": "Salad", "calories": None, "protein": 2.0, "carbs": 5.0, "fat": 0.0},
        {"food_name": "Soup", "calories": 80.0, "protein": 4.0, "carbs": 12.0, "fat": 1.0}
    ]
    calc = calculate_daily_nutrition(meals, calorie_target=1500)
    assert calc["has_missing_data"] is True
    assert calc["total_calories"] == 80.0
    assert calc["total_protein_g"] == 6.0

def test_water_and_weight_trend_calculations():
    # Water calculation
    water_rows = [{"amount_ml": 250}, {"amount_ml": 500}, {"amount_ml": 250}]
    w = calculate_water_summary(water_rows, target_ml=2000)
    assert w["total_ml"] == 1000
    assert w["glasses"] == 4.0
    assert w["remaining_ml"] == 1000
    assert w["progress_percent"] == 50.0
    assert w["target_reached"] is False

    # Weight trend: multiple entries
    weight_rows = [
        {"log_date": "2026-10-01", "weight_kg": 75.0},
        {"log_date": "2026-10-08", "weight_kg": 74.2},
        {"log_date": "2026-10-15", "weight_kg": 73.5}
    ]
    wt = calculate_weight_trends(weight_rows)
    assert wt["count"] == 3
    assert wt["latest_kg"] == 73.5
    assert wt["earliest_kg"] == 75.0
    assert wt["delta_kg"] == -1.5
    assert wt["trend"] == "losing_weight"

def test_serving_size_conversions():
    food = {"name": "Paneer", "calories": 265.0, "protein": 18.3, "carbs": 3.0, "fat": 20.8}
    half_portion = calculate_serving_nutrition(food, 0.5)
    assert half_portion["calories"] == 132.5
    assert half_portion["protein"] == 9.2
    assert half_portion["carbs"] == 1.5
    assert half_portion["fat"] == 10.4

    double_portion = calculate_serving_nutrition(food, 2.0)
    assert double_portion["calories"] == 530.0
    assert double_portion["protein"] == 36.6

# ==============================================================================
# 3. PERSONALIZATION & FOOD RECOMMENDATION TESTS
# ==============================================================================

def test_recommendation_dietary_preference_filtering(auth_user_pair):
    user_a = auth_user_pair["user_a"]  # Vegetarian
    user_b = auth_user_pair["user_b"]  # Non-veg

    ctx_a = build_user_nutrition_context(user_a["id"])
    ctx_b = build_user_nutrition_context(user_b["id"])

    recs_a = recommend_foods(ctx_a, top_n=10)
    recs_b = recommend_foods(ctx_b, top_n=10)

    # Vegetarian user must NEVER get Chicken or Egg (if eggetarian is not selected)
    food_names_a = [r["name"] for r in recs_a]
    assert "Chicken Breast (Cooked / Grilled)" not in food_names_a
    assert "Egg (Whole Boiled)" not in food_names_a

    # Non-veg user can receive chicken
    food_names_b = [r["name"] for r in recs_b]
    assert any("Chicken" in n for n in food_names_b)

def test_recommendation_allergy_exclusion(auth_user_pair):
    user_a = auth_user_pair["user_a"]  # Dairy allergy
    user_b = auth_user_pair["user_b"]  # Nut allergy

    ctx_a = build_user_nutrition_context(user_a["id"])
    ctx_b = build_user_nutrition_context(user_b["id"])

    recs_a = recommend_foods(ctx_a, top_n=10)
    recs_b = recommend_foods(ctx_b, top_n=10)

    # Dairy allergic user must NOT receive paneer, curd, yogurt, milk, or whey protein
    food_names_a = [r["name"].lower() for r in recs_a]
    assert not any("paneer" in n for n in food_names_a)
    assert not any("curd" in n for n in food_names_a)
    assert not any("yogurt" in n for n in food_names_a)
    assert not any("milk" in n for n in food_names_a)
    assert not any("whey" in n for n in food_names_a)

    # Nut allergic user must NOT receive almonds, walnuts, or peanut butter
    food_names_b = [r["name"].lower() for r in recs_b]
    assert not any("almond" in n for n in food_names_b)
    assert not any("walnut" in n for n in food_names_b)
    assert not any("peanut" in n for n in food_names_b)

def test_recommendation_goal_ranking(auth_user_pair):
    user_a = auth_user_pair["user_a"]  # Muscle Gain
    ctx_a = build_user_nutrition_context(user_a["id"])

    recs = recommend_foods(ctx_a, top_n=4)
    # For muscle gain, high-protein plant staples (e.g. Soy Chunks, Tofu) should be prioritized
    assert any(r["protein"] >= 15.0 for r in recs)
    # Each recommendation must include an evidence rationale
    assert all("rationale" in r and len(r["rationale"]) > 10 for r in recs)

# ==============================================================================
# 4. INTENT DETECTION & CONVERSATIONAL MEMORY TESTS
# ==============================================================================

def test_intent_detection_patterns():
    assert detect_intent("How many calories have I eaten today?") == "daily_nutrition_summary"
    assert detect_intent("What are my macros today?") == "daily_nutrition_summary"
    assert detect_intent("How much water did I drink today?") == "water_intake_summary"
    assert detect_intent("Am I making progress with my weight?") == "weight_progress"
    assert detect_intent("What should I eat for dinner?") == "food_recommendation"
    assert detect_intent("Recommend a high protein snack") == "food_recommendation"
    assert detect_intent("Generate a daily meal plan for me") == "meal_plan_generation"
    assert detect_intent("Can you suggest another option?") == "follow_up"
    assert detect_intent("Make it higher in protein") == "follow_up"
    assert detect_intent("What about a vegetarian version?") == "follow_up"
    assert detect_intent("Tell me the calories in cooked brown rice") == "food_nutrition_lookup"
    assert detect_intent("What did I eat yesterday?") == "meal_history"

def test_conversational_follow_up_persistence(auth_user_pair):
    user_a = auth_user_pair["user_a"]

    # Create conversation
    conv_res = client.post("/api/conversations", json={"title": "Test Follow Up"}, headers={"Authorization": f"Bearer {user_a['token']}"})
    conv_id = conv_res.json()["conversation_id"]

    # Send message with mocked LLM
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {"role": "assistant", "content": "I recommend Sprouted Moong Salad for your evening snack."}
        }
        res1 = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"message": "Suggest a high protein evening snack"},
            headers={"Authorization": f"Bearer {user_a['token']}"}
        )
        assert res1.status_code == 200

    # Send follow-up: "Can you suggest another option?"
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {"role": "assistant", "content": "Another excellent choice is Roasted Chana or Tofu cubes."}
        }
        res2 = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"message": "Can you suggest another option?"},
            headers={"Authorization": f"Bearer {user_a['token']}"}
        )
        assert res2.status_code == 200
        assert res2.json()["intent"] == "follow_up"

    # Verify messages in conversation
    hist = client.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {user_a['token']}"}).json()
    assert len(hist["messages"]) == 4

# ==============================================================================
# 5. PERSONALIZED MEAL PLAN GENERATION TESTS
# ==============================================================================

def test_personalized_meal_plan_generation(auth_user_pair):
    user_a = auth_user_pair["user_a"]
    ctx = build_user_nutrition_context(user_a["id"])

    plan = generate_personalized_meal_plan(ctx)
    assert plan["status"] == "valid"
    assert len(plan["meals"]) == 4  # Breakfast, Lunch, Snack, Dinner
    assert plan["total_calories"] > 0
    assert plan["total_protein_g"] > 0
    assert plan["total_carbs_g"] > 0
    assert plan["total_fat_g"] > 0

    # Verify that total calories equals the exact sum of meal calories (Python arithmetic)
    meal_sum_cals = round(sum(m["calories"] for m in plan["meals"]), 1)
    assert plan["total_calories"] == meal_sum_cals

    # Verify structured template format
    text = plan["formatted_text"]
    assert "🎯 Goal:" in text
    assert "🥣 Breakfast:" in text
    assert "🍛 Lunch:" in text
    assert "☕ Evening Snack:" in text
    assert "🌙 Dinner:" in text
    assert "💧 Water Intake:" in text

def test_meal_plan_generation_api_endpoint(auth_user_pair):
    user_a = auth_user_pair["user_a"]
    res = client.post("/api/plans/generate", headers={"Authorization": f"Bearer {user_a['token']}"})
    assert res.status_code == 200
    plan_data = res.json()["plan"]
    assert plan_data["status"] == "valid"
    assert "formatted_text" in plan_data

    # Save the generated plan to dashboard
    save_res = client.post("/api/plans", json={
        "title": "Automated Personalized Day Plan",
        "plan_content": plan_data["formatted_text"]
    }, headers={"Authorization": f"Bearer {user_a['token']}"})
    assert save_res.status_code == 201

    # Verify plan belongs to user_a
    plans = client.get("/api/plans", headers={"Authorization": f"Bearer {user_a['token']}"}).json()["plans"]
    assert any(p["title"] == "Automated Personalized Day Plan" for p in plans)

# ==============================================================================
# 6. AI SERVICE RESILIENCE & DETERMINISTIC FALLBACK TESTS
# ==============================================================================

def test_ollama_offline_fallback_to_deterministic_calculations(auth_user_pair):
    """
    When Ollama is offline (ConnectError), asking about today's calories or water
    must immediately return exact database calculations instead of failing.
    """
    from datetime import datetime, timezone
    user_a = auth_user_pair["user_a"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Log a meal for the current date
    client.post("/api/meals", json={
        "log_date": today_str,
        "meal_category": "lunch",
        "food_name": "Tofu Stir Fry",
        "serving_size": 1.0,
        "calories": 220.0,
        "protein": 18.0,
        "carbs": 12.0,
        "fat": 8.0
    }, headers={"Authorization": f"Bearer {user_a['token']}"})

    conv_res = client.post("/api/conversations", json={"title": "Offline Fallback Test"}, headers={"Authorization": f"Bearer {user_a['token']}"})
    conv_id = conv_res.json()["conversation_id"]

    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = httpx.ConnectError("Ollama daemon is offline")

        res = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"message": "How many calories have I eaten today?"},
            headers={"Authorization": f"Bearer {user_a['token']}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "deterministic_offline"
        # Must include the exact calculated totals and verified database record tag
        assert "Verified Database Record" in data["reply"]
        assert "Calories:" in data["reply"]
        assert "220.0 kcal" in data["reply"]
        assert "Ollama LLM is currently offline" in data["reply"]

def test_ollama_timeout_fallback_to_recommendations(auth_user_pair):
    """
    When Ollama times out during a food recommendation query,
    NutriAI falls back to verified database food recommendations.
    """
    user_a = auth_user_pair["user_a"]
    conv_res = client.post("/api/conversations", json={"title": "Timeout Test"}, headers={"Authorization": f"Bearer {user_a['token']}"})
    conv_id = conv_res.json()["conversation_id"]

    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = httpx.TimeoutException("Read timed out after 30s")

        res = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"message": "What should I eat for dinner?"},
            headers={"Authorization": f"Bearer {user_a['token']}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "deterministic_timeout"
        assert "Personalized Food Recommendations" in data["reply"]
        assert "Verified Dataset" in data["reply"]

def test_general_query_offline_guidance():
    """
    When Ollama is offline for an open-ended general chat query that cannot be computed
    deterministically, return the friendly diagnostic guidance to start Ollama.
    """
    with patch("ai_service.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = httpx.ConnectError("Ollama daemon is offline")
        unauth_client = TestClient(app, cookies={})
        res = unauth_client.post("/chat", json={"message": "Tell me a story about ancient nutrition"})
        assert res.status_code == 200
        assert "NutriAI local intelligence engine is currently offline" in res.json()["reply"]
        assert "ollama serve" in res.json()["reply"]
