"""
NutriAI — Nutrition Intelligence & Personalization Engine
Handles deterministic calculations, authenticated user context retrieval,
intent detection, evidence-backed food recommendations, and meal plan generation.
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from database import get_db

# ==============================================================================
# 1. DETERMINISTIC NUTRITION CALCULATIONS (PYTHON ARITHMETIC)
# ==============================================================================

def calculate_daily_nutrition(meal_rows: List[Dict[str, Any]], calorie_target: Optional[int] = None) -> Dict[str, Any]:
    """
    Performs deterministic arithmetic on logged meals for a specific date.
    Calculates exact totals, remaining budgets, and detects missing values.
    """
    total_calories = 0.0
    total_protein = 0.0
    total_carbs = 0.0
    total_fat = 0.0
    categories = {"breakfast": [], "lunch": [], "snack": [], "dinner": []}
    has_missing_data = False

    for meal in meal_rows:
        cal = meal.get("calories")
        prot = meal.get("protein") or 0.0
        crb = meal.get("carbs") or 0.0
        ft = meal.get("fat") or 0.0

        if cal is None:
            has_missing_data = True
            cal = 0.0
        
        total_calories += float(cal)
        total_protein += float(prot)
        total_carbs += float(crb)
        total_fat += float(ft)

        cat = (meal.get("meal_category") or "snack").lower()
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(meal)

    total_calories = round(total_calories, 1)
    total_protein = round(total_protein, 1)
    total_carbs = round(total_carbs, 1)
    total_fat = round(total_fat, 1)

    result = {
        "meal_count": len(meal_rows),
        "total_calories": total_calories,
        "total_protein_g": total_protein,
        "total_carbs_g": total_carbs,
        "total_fat_g": total_fat,
        "categories": categories,
        "has_missing_data": has_missing_data,
        "calorie_target": calorie_target,
        "remaining_calories": round(calorie_target - total_calories, 1) if calorie_target else None,
        "progress_percent": min(100.0, round((total_calories / calorie_target) * 100, 1)) if calorie_target and calorie_target > 0 else None,
    }
    return result

def calculate_water_summary(water_rows: List[Dict[str, Any]], target_ml: Optional[int] = 2500) -> Dict[str, Any]:
    """
    Calculates total water consumption and comparison against daily goal.
    """
    total_ml = sum(int(r.get("amount_ml") or 0) for r in water_rows)
    target = target_ml or 2500
    glasses = round(total_ml / 250.0, 1)
    target_glasses = round(target / 250.0, 1)
    remaining_ml = max(0, target - total_ml)
    progress_percent = min(100.0, round((total_ml / target) * 100, 1)) if target > 0 else 0.0

    return {
        "total_ml": total_ml,
        "target_ml": target,
        "glasses": glasses,
        "target_glasses": target_glasses,
        "remaining_ml": remaining_ml,
        "progress_percent": progress_percent,
        "target_reached": total_ml >= target
    }

def calculate_weight_trends(weight_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyzes historical weight entries to determine trajectory, delta, and averages.
    """
    if not weight_rows:
        return {
            "count": 0,
            "trend": "no_data",
            "message": "No weight measurements recorded yet."
        }

    latest = float(weight_rows[-1]["weight_kg"])
    earliest = float(weight_rows[0]["weight_kg"])
    delta_kg = round(latest - earliest, 1)
    avg_kg = round(sum(float(r["weight_kg"]) for r in weight_rows) / len(weight_rows), 1)

    if len(weight_rows) == 1:
        trend = "single_entry"
        trend_desc = "Single recorded measurement. Log more entries over time to observe progress."
    elif delta_kg <= -0.5:
        trend = "losing_weight"
        trend_desc = f"Down {abs(delta_kg)} kg since first recorded entry ({earliest} kg)."
    elif delta_kg >= 0.5:
        trend = "gaining_weight"
        trend_desc = f"Up {delta_kg} kg since first recorded entry ({earliest} kg)."
    else:
        trend = "stable"
        trend_desc = f"Stable weight within ±0.5 kg of initial entry ({earliest} kg)."

    return {
        "count": len(weight_rows),
        "latest_kg": latest,
        "earliest_kg": earliest,
        "delta_kg": delta_kg,
        "average_kg": avg_kg,
        "trend": trend,
        "trend_description": trend_desc,
        "recent_entries": [dict(r) for r in weight_rows[-5:]]
    }

def calculate_serving_nutrition(food_item: Dict[str, Any], serving_multiplier: float = 1.0) -> Dict[str, float]:
    """
    Computes exact nutrition for a given portion multiplier using database food data.
    """
    mult = max(0.01, float(serving_multiplier))
    return {
        "calories": round(float(food_item.get("calories", 0.0)) * mult, 1),
        "protein": round(float(food_item.get("protein", 0.0)) * mult, 1),
        "carbs": round(float(food_item.get("carbs", 0.0)) * mult, 1),
        "fat": round(float(food_item.get("fat", 0.0)) * mult, 1),
    }

# ==============================================================================
# 2. CONTEXT ENGINE (AUTHENTICATED & USER-SCOPED DATA SOURCE)
# ==============================================================================

class UserNutritionContext:
    """Encapsulates all relevant, authenticated user context for a request."""
    def __init__(
        self,
        user_id: int,
        user_name: str,
        user_email: str,
        profile: Dict[str, Any],
        today_date: str,
        today_meals: List[Dict[str, Any]],
        today_nutrition: Dict[str, Any],
        recent_meals: List[Dict[str, Any]],
        today_water: Dict[str, Any],
        weight_trends: Dict[str, Any],
        saved_plans: List[Dict[str, Any]],
        missing_fields: List[str]
    ):
        self.user_id = user_id
        self.user_name = user_name
        self.user_email = user_email
        self.profile = profile
        self.today_date = today_date
        self.today_meals = today_meals
        self.today_nutrition = today_nutrition
        self.recent_meals = recent_meals
        self.today_water = today_water
        self.weight_trends = weight_trends
        self.saved_plans = saved_plans
        self.missing_fields = missing_fields

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "profile": self.profile,
            "today_date": self.today_date,
            "today_nutrition": self.today_nutrition,
            "today_water": self.today_water,
            "weight_trends": self.weight_trends,
            "saved_plans_count": len(self.saved_plans),
            "missing_fields": self.missing_fields
        }

def build_user_nutrition_context(user_id: int, target_date: Optional[str] = None) -> UserNutritionContext:
    """
    Safely retrieves authenticated user metrics, daily meals, water, weight, and plans.
    Strictly isolated to user_id. Separates today's records from historical entries.
    """
    today_str = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. User Account
        cursor.execute("SELECT id, name, email FROM users WHERE id = ?;", (user_id,))
        user_row = cursor.fetchone()
        user_name = user_row["name"] if user_row else "User"
        user_email = user_row["email"] if user_row else ""

        # 2. User Profile
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?;", (user_id,))
        prof_row = cursor.fetchone()
        profile = dict(prof_row) if prof_row else {}

        # 3. Today's Meal Logs
        cursor.execute("""
            SELECT id, log_date, meal_category, food_name, serving_size, calories, protein, carbs, fat
            FROM meal_logs 
            WHERE user_id = ? AND log_date = ?
            ORDER BY id ASC;
        """, (user_id, today_str))
        today_meals = [dict(r) for r in cursor.fetchall()]

        # 4. Recent Historical Meal Logs (past 7 days, excluding today)
        cursor.execute("""
            SELECT id, log_date, meal_category, food_name, serving_size, calories, protein, carbs, fat
            FROM meal_logs 
            WHERE user_id = ? AND log_date != ?
            ORDER BY log_date DESC, id DESC LIMIT 15;
        """, (user_id, today_str))
        recent_meals = [dict(r) for r in cursor.fetchall()]

        # 5. Today's Water Logs
        cursor.execute("""
            SELECT id, amount_ml, created_at
            FROM water_logs 
            WHERE user_id = ? AND log_date = ?
            ORDER BY id ASC;
        """, (user_id, today_str))
        today_water_rows = [dict(r) for r in cursor.fetchall()]

        # 6. Weight Logs (chronological)
        cursor.execute("""
            SELECT id, log_date, weight_kg, notes
            FROM weight_logs 
            WHERE user_id = ? 
            ORDER BY log_date ASC, id ASC;
        """, (user_id,))
        weight_rows = [dict(r) for r in cursor.fetchall()]

        # 7. Saved Diet Plans
        cursor.execute("""
            SELECT id, title, plan_content, created_at
            FROM diet_plans 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT 5;
        """, (user_id,))
        saved_plans = [dict(r) for r in cursor.fetchall()]

    # Calculate metrics
    calorie_target = profile.get("daily_calorie_target")
    water_target = profile.get("daily_water_target_ml") or 2500

    today_nutrition = calculate_daily_nutrition(today_meals, calorie_target)
    today_water = calculate_water_summary(today_water_rows, water_target)
    weight_trends = calculate_weight_trends(weight_rows)

    # Detect missing critical profile data
    missing_fields = []
    if not profile.get("goal"): missing_fields.append("health goal")
    if not profile.get("age"): missing_fields.append("age")
    if not profile.get("weight_kg"): missing_fields.append("weight")
    if not profile.get("height_cm"): missing_fields.append("height")
    if not profile.get("dietary_preference"): missing_fields.append("dietary preference")

    return UserNutritionContext(
        user_id=user_id,
        user_name=user_name,
        user_email=user_email,
        profile=profile,
        today_date=today_str,
        today_meals=today_meals,
        today_nutrition=today_nutrition,
        recent_meals=recent_meals,
        today_water=today_water,
        weight_trends=weight_trends,
        saved_plans=saved_plans,
        missing_fields=missing_fields
    )

# ==============================================================================
# 3. INTENT DETECTION & INTELLIGENT ROUTER
# ==============================================================================

def detect_intent(message: str, recent_history: Optional[List[Dict[str, str]]] = None) -> str:
    """
    Classifies user intent using deterministic keyword & regex patterns.
    Recognizes tracking, calculation, recommendation, plan generation, and follow-ups.
    """
    msg = message.strip().lower()

    # 1. Follow-up intent checks (if conversation history is available)
    follow_up_patterns = [
        r"^(can you )?suggest another( option)?",
        r"^what about (a )?vegetarian( version)?",
        r"^make it (higher|more) (in )?protein",
        r"^(explain|tell me more about) that",
        r"^compare (it )?with (my )?previous",
        r"^give me another",
        r"^different (option|choice|meal)",
        r"^change that",
        r"^replace the",
        r"^what else"
    ]
    for pattern in follow_up_patterns:
        if re.search(pattern, msg):
            return "follow_up"

    # 2. Daily nutrition / Calories / Macros consumed today
    if any(k in msg for k in [
        "how many calories have i eaten",
        "how many calories did i eat",
        "calories today",
        "calories have i had",
        "my macros today",
        "how much protein have i eaten",
        "protein today",
        "carbs today",
        "fat today",
        "daily summary",
        "nutrition summary today",
        "remaining calories",
        "calorie budget today",
        "what did i eat today"
    ]):
        return "daily_nutrition_summary"

    # 3. Water Intake summary
    if any(k in msg for k in [
        "water intake",
        "water today",
        "how much water",
        "glasses of water",
        "hydration today",
        "water goal",
        "did i drink enough water"
    ]):
        return "water_intake_summary"

    # 4. Weight tracking & progress
    if any(k in msg for k in [
        "am i making progress",
        "my progress",
        "weight trend",
        "how is my weight",
        "weight progress",
        "how much weight have i lost",
        "weight change",
        "weight history",
        "am i losing weight",
        "am i gaining weight"
    ]):
        return "weight_progress"

    # 5. Meal plan generation
    if any(k in msg for k in [
        "generate a meal plan",
        "create a meal plan",
        "give me a meal plan",
        "daily meal plan",
        "diet plan for",
        "plan my meals",
        "create a diet plan",
        "make a meal plan",
        "full day meal plan",
        "generate diet plan"
    ]):
        return "meal_plan_generation"

    # 6. Food Recommendation
    if any(k in msg for k in [
        "what should i eat",
        "what can i eat",
        "recommend a meal",
        "recommend food",
        "dinner ideas",
        "lunch ideas",
        "breakfast ideas",
        "snack ideas",
        "high protein snack",
        "healthy dinner",
        "healthy lunch",
        "meal options",
        "food recommendation"
    ]):
        return "food_recommendation"

    # 7. Food Nutrition Lookup
    if any(k in msg for k in ["calories in", "nutrition of", "macros in", "how many calories in", "nutritional value of"]):
        return "food_nutrition_lookup"

    # 8. Meal logging & history
    if any(k in msg for k in ["what did i eat yesterday", "recent meals", "past meals", "meal log", "logged meals"]):
        return "meal_history"

    # 9. Allergy & restriction safety
    if any(k in msg for k in ["allergic to", "allergy", "can i eat", "is it safe to eat", "lactose", "gluten free"]):
        return "dietary_allergy"

    return "general_nutrition"

# ==============================================================================
# 4. EVIDENCE-BASED FOOD RECOMMENDATION SERVICE
# ==============================================================================

def recommend_foods(
    user_context: Optional[UserNutritionContext] = None,
    category: Optional[str] = None,
    meal_type: Optional[str] = None,
    top_n: int = 4
) -> List[Dict[str, Any]]:
    """
    Recommends verified foods based on:
    1. Dietary preference (vegetarian, vegan, eggetarian, non_veg).
    2. Explicit allergies (exclusions).
    3. User goal (muscle gain -> protein density, fat loss -> satiety/calories).
    4. Variety (deprioritizes foods eaten today).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM food_items ORDER BY name ASC;")
        foods = [dict(r) for r in cursor.fetchall()]

    if not foods:
        return []

    # Extract user parameters if available
    diet_pref = "vegetarian"
    user_allergies = []
    goal = "healthy_lifestyle"
    eaten_today = set()

    if user_context:
        diet_pref = (user_context.profile.get("dietary_preference") or "vegetarian").lower()
        goal = (user_context.profile.get("goal") or "healthy_lifestyle").lower()
        allergies_str = user_context.profile.get("allergies") or ""
        user_allergies = [a.strip().lower() for a in re.split(r"[,;/]+", allergies_str) if a.strip()]
        for m in user_context.today_meals:
            eaten_today.add(m.get("food_name", "").strip().lower())

    filtered_foods = []
    for f in foods:
        tags = (f.get("dietary_tags") or "").lower()
        allergens = (f.get("allergens") or "").lower()
        food_name = f["name"].lower()

        # 1. Dietary preference filtering
        if diet_pref == "vegetarian":
            if "vegetarian" not in tags and "vegan" not in tags:
                continue
        elif diet_pref == "vegan":
            if "vegan" not in tags:
                continue
        elif diet_pref == "eggetarian":
            if "vegetarian" not in tags and "vegan" not in tags and "eggetarian" not in tags:
                continue

        # 2. Strict allergy exclusion
        excluded_by_allergy = False
        for allergen in user_allergies:
            if not allergen:
                continue
            # Match against explicit database allergens
            if allergen in allergens:
                excluded_by_allergy = True
                break
            # Synonym & common term expansion
            if allergen in ["dairy", "lactose", "milk"] and ("dairy" in allergens or "milk" in food_name or "paneer" in food_name or "curd" in food_name or "yogurt" in food_name or "whey" in food_name):
                excluded_by_allergy = True
                break
            if allergen in ["gluten", "wheat"] and ("gluten" in allergens or "roti" in food_name or "wheat" in food_name or "upma" in food_name):
                excluded_by_allergy = True
                break
            if allergen in ["nut", "nuts", "peanut", "peanuts", "almond"] and ("nuts" in allergens or "peanut" in allergens or "almond" in food_name or "walnut" in food_name):
                excluded_by_allergy = True
                break
            if allergen in ["egg", "eggs"] and ("eggs" in allergens or "egg" in food_name):
                excluded_by_allergy = True
                break
            if allergen in ["soy", "soya"] and ("soy" in allergens or "tofu" in food_name or "soy" in food_name):
                excluded_by_allergy = True
                break

        if excluded_by_allergy:
            continue

        # 3. Category / meal_type filter if requested
        if category and f["category"].lower() != category.lower():
            continue

        # 4. Scoring & ranking
        score = 0.0
        calories = float(f.get("calories", 100.0))
        protein = float(f.get("protein", 0.0))
        carbs = float(f.get("carbs", 0.0))
        fat = float(f.get("fat", 0.0))

        # Goal-based scoring
        if "muscle" in goal:
            # Prioritize high protein density per calorie
            score += (protein / max(calories, 1.0)) * 100.0
            if f["category"] in ["Poultry", "Eggs", "Dairy", "Soy / Vegan", "Supplements"]:
                score += 10.0
        elif "fat_loss" in goal or "weight_loss" in goal:
            # High protein, moderate calorie, high fiber and lean protein
            protein_density = (protein / max(calories, 1.0)) * 80.0
            calorie_penalty = calories * 0.04
            score += (protein_density - calorie_penalty)
            if f["category"] in ["Salads", "Vegetables", "Legumes", "Poultry", "Eggs"]:
                score += 10.0
        else:
            # Balanced distribution
            score += (protein * 1.5) - (fat * 0.5)

        # Variety bonus: slight penalty for foods already logged today
        if food_name in eaten_today:
            score -= 10.0

        f_copy = dict(f)
        f_copy["score"] = score
        f_copy["rationale"] = generate_food_rationale(f, goal, diet_pref)
        filtered_foods.append(f_copy)

    # Sort descending by score
    filtered_foods.sort(key=lambda x: x["score"], reverse=True)
    return filtered_foods[:top_n]

def generate_food_rationale(food: Dict[str, Any], goal: str, diet_pref: str) -> str:
    """Explains why a food was chosen based on actual verified nutritional properties."""
    prot = food.get("protein", 0.0)
    cals = food.get("calories", 0.0)
    unit = food.get("serving_unit", "serving")

    if "muscle" in goal and prot >= 10.0:
        return f"Rich source of protein ({prot}g per {unit}) to support muscle synthesis and recovery."
    elif ("fat_loss" in goal or "weight_loss" in goal) and cals <= 160.0:
        return f"Nutrient-dense with only {cals} kcal per {unit}, supporting your calorie deficit while keeping you full."
    elif prot >= 8.0:
        return f"Provides {prot}g protein and balanced micronutrients suited for {diet_pref} nutrition."
    else:
        return f"Wholesome staple ({cals} kcal per {unit}) providing steady energy and satiety."

# ==============================================================================
# 5. DETERMINISTIC MEAL PLAN GENERATION
# ==============================================================================

def generate_personalized_meal_plan(user_context: UserNutritionContext) -> Dict[str, Any]:
    """
    Creates a complete, verified daily meal plan tailored to the authenticated user.
    Calculates exact totals in Python without delegating arithmetic to the LLM.
    """
    goal = user_context.profile.get("goal") or "healthy_lifestyle"
    diet = user_context.profile.get("dietary_preference") or "vegetarian"
    cal_target = user_context.profile.get("daily_calorie_target") or 2000
    water_target = user_context.profile.get("daily_water_target_ml") or 2500

    # Retrieve recommendations for each meal slot
    breakfast_candidates = recommend_foods(user_context, category=None, top_n=8)
    lunch_candidates = recommend_foods(user_context, category=None, top_n=8)
    snack_candidates = recommend_foods(user_context, category=None, top_n=8)
    dinner_candidates = recommend_foods(user_context, category=None, top_n=8)

    # Filter by appropriate meal items
    breakfast_items = [f for f in breakfast_candidates if f["category"] in ["Breakfast", "Eggs", "Dairy", "Fruits"]] or breakfast_candidates[:2]
    lunch_items = [f for f in lunch_candidates if f["category"] in ["Grains", "Legumes", "Curry", "Dairy", "Poultry", "Main Course"]] or lunch_candidates[:2]
    snack_items = [f for f in snack_candidates if f["category"] in ["Salads", "Nuts & Seeds", "Fruits", "Beverage", "Spreads"]] or snack_candidates[:2]
    dinner_items = [f for f in dinner_candidates if f["category"] in ["Grains", "Legumes", "Curry", "Main Course", "Vegetables"]] or dinner_candidates[:2]

    # Select meal components
    b_food = breakfast_items[0] if breakfast_items else {"name": "Oats with fruit", "calories": 180, "protein": 6, "carbs": 30, "fat": 3, "serving_unit": "bowl"}
    
    # Lunch: Grain + Protein/Legume
    l_food1 = lunch_items[0] if lunch_items else {"name": "Roti", "calories": 104, "protein": 3.1, "carbs": 20, "fat": 0.9, "serving_unit": "2 pieces"}
    l_food2 = lunch_items[1] if len(lunch_items) > 1 else {"name": "Dal", "calories": 148, "protein": 9.2, "carbs": 22, "fat": 2.5, "serving_unit": "katori"}

    s_food = snack_items[0] if snack_items else {"name": "Raw Almonds", "calories": 164, "protein": 6, "carbs": 6, "fat": 14, "serving_unit": "handful"}
    
    d_food1 = dinner_items[0] if dinner_items else {"name": "Cooked Brown Rice", "calories": 168, "protein": 3.8, "carbs": 35, "fat": 1.4, "serving_unit": "bowl"}
    d_food2 = dinner_items[1] if len(dinner_items) > 1 else {"name": "Mixed Vegetable Sabzi", "calories": 120, "protein": 2.8, "carbs": 14, "fat": 5.5, "serving_unit": "katori"}

    # Structured plan components
    breakfast_plan = {
        "title": "Breakfast",
        "items": [f"{b_food['name']} ({b_food['serving_unit']})"],
        "calories": round(b_food["calories"], 1),
        "protein": round(b_food["protein"], 1),
        "carbs": round(b_food["carbs"], 1),
        "fat": round(b_food["fat"], 1),
    }

    lunch_plan = {
        "title": "Lunch",
        "items": [f"{l_food1['name']} ({l_food1['serving_unit']})", f"{l_food2['name']} ({l_food2['serving_unit']})"],
        "calories": round(l_food1["calories"] + l_food2["calories"], 1),
        "protein": round(l_food1["protein"] + l_food2["protein"], 1),
        "carbs": round(l_food1["carbs"] + l_food2["carbs"], 1),
        "fat": round(l_food1["fat"] + l_food2["fat"], 1),
    }

    snack_plan = {
        "title": "Evening Snack",
        "items": [f"{s_food['name']} ({s_food['serving_unit']})"],
        "calories": round(s_food["calories"], 1),
        "protein": round(s_food["protein"], 1),
        "carbs": round(s_food["carbs"], 1),
        "fat": round(s_food["fat"], 1),
    }

    dinner_plan = {
        "title": "Dinner",
        "items": [f"{d_food1['name']} ({d_food1['serving_unit']})", f"{d_food2['name']} ({d_food2['serving_unit']})"],
        "calories": round(d_food1["calories"] + d_food2["calories"], 1),
        "protein": round(d_food1["protein"] + d_food2["protein"], 1),
        "carbs": round(d_food1["carbs"] + d_food2["carbs"], 1),
        "fat": round(d_food1["fat"] + d_food2["fat"], 1),
    }

    # Python calculated day totals
    day_calories = round(breakfast_plan["calories"] + lunch_plan["calories"] + snack_plan["calories"] + dinner_plan["calories"], 1)
    day_protein = round(breakfast_plan["protein"] + lunch_plan["protein"] + snack_plan["protein"] + dinner_plan["protein"], 1)
    day_carbs = round(breakfast_plan["carbs"] + lunch_plan["carbs"] + snack_plan["carbs"] + dinner_plan["carbs"], 1)
    day_fat = round(breakfast_plan["fat"] + lunch_plan["fat"] + snack_plan["fat"] + dinner_plan["fat"], 1)

    # Goal explanation
    goal_title = goal.replace("_", " ").title()
    diet_title = diet.replace("_", " ").title()
    
    if "fat_loss" in goal or "weight_loss" in goal:
        explanation = f"Calorie-controlled ({day_calories} kcal) with high protein ({day_protein}g) and fiber to preserve lean muscle while promoting fat loss."
    elif "muscle" in goal:
        explanation = f"Protein-dense ({day_protein}g) to support resistance training recovery and muscle protein synthesis."
    else:
        explanation = f"Balanced macronutrient distribution ({day_carbs}g carbs, {day_protein}g protein, {day_fat}g fat) providing steady daily energy."

    # Format text for UI diet-plan card
    formatted_text = f"""🎯 Goal: {goal_title} ({diet_title})
🥣 Breakfast: {', '.join(breakfast_plan['items'])} (~{breakfast_plan['calories']} kcal, {breakfast_plan['protein']}g protein) [Verified Database]
🍛 Lunch: {', '.join(lunch_plan['items'])} (~{lunch_plan['calories']} kcal, {lunch_plan['protein']}g protein) [Verified Database]
☕ Evening Snack: {', '.join(snack_plan['items'])} (~{snack_plan['calories']} kcal, {snack_plan['protein']}g protein) [Verified Database]
🌙 Dinner: {', '.join(dinner_plan['items'])} (~{dinner_plan['calories']} kcal, {dinner_plan['protein']}g protein) [Verified Database]
💧 Water Intake: {water_target} ml (~{round(water_target/250, 1)} glasses daily)
🏃 Exercise Tip: Combine with 30-45 minutes of moderate movement or strength training.
⚠️ Important Note: {explanation} Adjust portions to match your exact hunger cues and medical guidance."""

    return {
        "status": "valid",
        "goal": goal_title,
        "dietary_preference": diet_title,
        "total_calories": day_calories,
        "total_protein_g": day_protein,
        "total_carbs_g": day_carbs,
        "total_fat_g": day_fat,
        "calorie_target": cal_target,
        "formatted_text": formatted_text,
        "meals": [breakfast_plan, lunch_plan, snack_plan, dinner_plan],
        "explanation": explanation
    }

# ==============================================================================
# 6. DETERMINISTIC RESPONSE GENERATOR (OFFLINE / FALLBACK HANDLER)
# ==============================================================================

def generate_deterministic_response(intent: str, user_context: Optional[UserNutritionContext], query: str) -> str:
    """
    Generates exact, reliable data-driven responses when language-model generation
    is offline or when answering structured tracking inquiries.
    """
    if not user_context:
        return (
            "You are currently viewing NutriAI in guest mode. "
            "Please sign up or log in to track meals, review water intake, and receive personalized nutrition intelligence."
        )

    # 1. Daily nutrition summary
    if intent == "daily_nutrition_summary":
        nuts = user_context.today_nutrition
        target = nuts.get("calorie_target")
        meals = user_context.today_meals

        if not meals:
            target_str = f"Your daily target is {target} kcal." if target else "You have not set a daily calorie target yet."
            return (
                f"📊 **Daily Nutrition Summary for Today ({user_context.today_date})**\n\n"
                f"You have not logged any meals yet today.\n"
                f"{target_str}\n\n"
                f"💡 *Tip:* Use the **Meals & Food Tracker** tab to record your breakfast, lunch, or snack!"
            )

        meal_list_str = "\n".join([
            f"- **{m.get('meal_category', 'Meal').title()}:** {m.get('food_name')} ({m.get('calories')} kcal, {m.get('protein', 0)}g protein)"
            for m in meals
        ])

        target_info = ""
        if target:
            rem = nuts.get("remaining_calories", 0)
            pct = nuts.get("progress_percent", 0)
            target_info = f"\n- **Target:** {target} kcal ({pct}% reached, **{rem} kcal remaining**)"

        missing_note = "\n*(Note: Some logged meals lack full macro breakdown.)*" if nuts.get("has_missing_data") else ""

        return (
            f"📊 **Logged Nutrition for Today ({user_context.today_date})** [Verified Database Record]\n\n"
            f"**Totals Consumed:**\n"
            f"- **Calories:** **{nuts['total_calories']} kcal**{target_info}\n"
            f"- **Protein:** **{nuts['total_protein_g']} g**\n"
            f"- **Carbohydrates:** **{nuts['total_carbs_g']} g**\n"
            f"- **Fat:** **{nuts['total_fat_g']} g**\n\n"
            f"**Meals Logged ({nuts['meal_count']}):**\n"
            f"{meal_list_str}{missing_note}"
        )

    # 2. Water intake summary
    if intent == "water_intake_summary":
        w = user_context.today_water
        target = w["target_ml"]
        total = w["total_ml"]
        pct = w["progress_percent"]
        glasses = w["glasses"]

        if total == 0:
            return (
                f"💧 **Hydration Status for Today ({user_context.today_date})**\n\n"
                f"You haven't logged any water today yet.\n"
                f"- **Target:** {target} ml ({w['target_glasses']} glasses)\n\n"
                f"💡 Click the quick-add buttons (+250ml / +500ml) on the dashboard to log your hydration!"
            )

        status_msg = "🎉 Great job! You have reached your hydration goal for the day." if w["target_reached"] else f"Keep going! You have **{w['remaining_ml']} ml** left to reach your target."

        return (
            f"💧 **Today's Hydration Record ({user_context.today_date})** [Verified Tracking Record]\n\n"
            f"- **Water Consumed:** **{total} ml** ({glasses} glasses)\n"
            f"- **Daily Target:** {target} ml ({w['target_glasses']} glasses)\n"
            f"- **Progress:** {pct}% completed\n\n"
            f"{status_msg}"
        )

    # 3. Weight tracking and progress
    if intent == "weight_progress":
        wt = user_context.weight_trends
        if wt["count"] == 0:
            return (
                "⚖️ **Weight Tracking & Progress Analysis**\n\n"
                "You have not recorded any weight measurements yet.\n"
                "To track your trajectory, record your morning weight on the **Weight Analytics** tab."
            )
        elif wt["count"] == 1:
            return (
                f"⚖️ **Weight Progress**\n\n"
                f"- **Current Recorded Weight:** **{wt['latest_kg']} kg**\n"
                f"You have only 1 recorded measurement. Log your weight weekly under consistent conditions (morning, before breakfast) to observe trends."
            )
        else:
            delta = wt["delta_kg"]
            delta_sign = "+" if delta > 0 else ""
            return (
                f"⚖️ **Weight Progress & Trend Analysis** [Verified Records]\n\n"
                f"- **Current Weight:** **{wt['latest_kg']} kg**\n"
                f"- **Starting Recorded Weight:** {wt['earliest_kg']} kg\n"
                f"- **Net Change:** **{delta_sign}{delta} kg**\n"
                f"- **Average Recorded Weight:** {wt['average_kg']} kg across {wt['count']} entries\n"
                f"- **Trajectory:** {wt['trend_description']}\n\n"
                f"*(Note: Day-to-day water retention and sodium intake cause normal fluctuations. Focus on the weekly moving average.)*"
            )

    # 4. Food Recommendation
    if intent == "food_recommendation":
        recs = recommend_foods(user_context, top_n=4)
        if not recs:
            return "No verified food items matching your dietary criteria were found in the database."

        rec_lines = []
        for i, r in enumerate(recs, 1):
            rec_lines.append(
                f"{i}. **{r['name']}** ({r['serving_unit']})\n"
                f"   - **Nutrients:** {r['calories']} kcal | {r['protein']}g protein | {r['carbs']}g carbs | {r['fat']}g fat [Verified Dataset]\n"
                f"   - **Why it fits:** {r['rationale']}"
            )

        goal = (user_context.profile.get("goal") or "healthy lifestyle").replace("_", " ").title()
        diet = (user_context.profile.get("dietary_preference") or "vegetarian").title()

        return (
            f"🥗 **Personalized Food Recommendations** (Goal: {goal} | Diet: {diet})\n\n"
            + "\n\n".join(rec_lines) +
            "\n\n*(Values are verified from the NutriAI Food Composition Dataset.)*"
        )

    # 5. Meal plan generation
    if intent == "meal_plan_generation":
        plan_dict = generate_personalized_meal_plan(user_context)
        return plan_dict["formatted_text"]

    # 6. Food nutrition lookup
    if intent == "food_nutrition_lookup":
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM food_items;")
            all_foods = [dict(r) for r in cursor.fetchall()]

        # Find best match in query
        matched = []
        q_clean = query.lower()
        for f in all_foods:
            f_name = f["name"].lower()
            if any(part in q_clean for part in f_name.split() if len(part) > 3):
                matched.append(f)

        if matched:
            f = matched[0]
            return (
                f"🔍 **Nutritional Facts for {f['name']}** [Verified Composition Record]\n\n"
                f"- **Standard Portion:** {f['serving_unit']}\n"
                f"- **Calories:** {f['calories']} kcal\n"
                f"- **Protein:** {f['protein']} g\n"
                f"- **Carbohydrates:** {f['carbs']} g\n"
                f"- **Fat:** {f['fat']} g\n"
                f"- **Dietary Classification:** {f.get('dietary_tags', 'Standard')}\n"
                + (f"- **Known Allergens:** {f['allergens']}\n" if f.get('allergens') else "")
            )
        else:
            return (
                f"I could not locate an exact verified database record matching '{query}'. "
                f"You can search the **Verified Foods** list in the Meals Tracker or ask about common staples like roti, dal, paneer, brown rice, or eggs."
            )

    # Default fallback
    return (
        f"Hello {user_context.user_name}! I have access to your live NutriAI dashboard metrics. "
        f"You can ask me:\n"
        f"- 'How many calories have I eaten today?'\n"
        f"- 'How is my water intake today?'\n"
        f"- 'Am I making weight progress?'\n"
        f"- 'Recommend high protein snacks'\n"
        f"- 'Generate a personalized daily meal plan'"
    )

# ==============================================================================
# 7. GROUNDED CONTEXT INJECTION FOR OLLAMA PROMPT
# ==============================================================================

def format_context_for_prompt(user_context: Optional[UserNutritionContext]) -> str:
    """
    Assembles a verified, factual context snippet to inject into the LLM system prompt.
    Explicitly instructs the LLM not to perform calculations and not to fabricate missing values.
    """
    if not user_context:
        return "GUEST CONTEXT: No authenticated profile or logged data available. Ask follow-up questions to understand their health goals."

    prof = user_context.profile
    nuts = user_context.today_nutrition
    w = user_context.today_water
    wt = user_context.weight_trends

    # Build known profile lines
    lines = [
        f"- User Name: {user_context.user_name}",
        f"- Goal: {prof.get('goal', 'healthy_lifestyle')}",
        f"- Dietary Preference: {prof.get('dietary_preference', 'vegetarian')}",
        f"- Allergies / Restrictions: {prof.get('allergies') or 'None specified'}",
        f"- Age: {prof.get('age') or 'Not provided'}",
        f"- Gender: {prof.get('gender') or 'Not provided'}",
        f"- Height: {prof.get('height_cm')} cm" if prof.get('height_cm') else "- Height: Not provided",
        f"- Current Recorded Weight: {wt.get('latest_kg') or prof.get('weight_kg') or 'Not provided'} kg",
        f"- Daily Calorie Target: {nuts.get('calorie_target') or 'Not configured'} kcal",
        f"- Daily Water Target: {w.get('target_ml')} ml ({w.get('target_glasses')} glasses)",
    ]

    # Today's verified nutrition
    if user_context.today_meals:
        meal_names = ", ".join([f"{m.get('food_name')} ({m.get('calories')} kcal)" for m in user_context.today_meals])
        lines.append(f"- Today's Logged Meals: {meal_names}")
        lines.append(
            f"- Today's Verified Totals: {nuts['total_calories']} kcal consumed, "
            f"{nuts['total_protein_g']}g protein, {nuts['total_carbs_g']}g carbs, {nuts['total_fat_g']}g fat. "
            f"Remaining budget: {nuts.get('remaining_calories', 'N/A')} kcal."
        )
    else:
        lines.append("- Today's Logged Meals: None logged yet today (0.0 kcal consumed so far).")

    # Today's water status
    lines.append(f"- Today's Water: {w['total_ml']} ml consumed of {w['target_ml']} ml goal ({w['glasses']} glasses).")

    # Weight trend
    if wt["count"] > 1:
        lines.append(f"- Weight Progress: Initial {wt['earliest_kg']} kg -> Current {wt['latest_kg']} kg (Net change: {wt['delta_kg']} kg, {wt['trend_description']}).")
    elif wt["count"] == 1:
        lines.append(f"- Weight Progress: 1 measurement recorded ({wt['latest_kg']} kg).")
    else:
        lines.append("- Weight Progress: No weight logs recorded yet.")

    # Saved plans
    if user_context.saved_plans:
        plan_titles = ", ".join([p["title"] for p in user_context.saved_plans])
        lines.append(f"- Saved Plans on Dashboard: {plan_titles}")

    context_str = "\n".join(lines)
    return (
        f"\nVERIFIED USER CONTEXT & REAL DATABASE METRICS (DATE: {user_context.today_date}):\n"
        f"{context_str}\n\n"
        "STRICT CONTEXT INSTRUCTIONS:\n"
        "1. Always use the verified figures above when answering queries about today's calories, protein, water, or weight progress. DO NOT calculate different totals.\n"
        "2. If the user asks what they have eaten today or how many calories they have left, cite the exact numbers from the verified totals above.\n"
        "3. Respect explicit allergies and dietary preferences strictly. Never suggest meat or eggs to a vegetarian or vegan.\n"
        "4. If a metric is marked as 'Not provided', state that it is unknown instead of fabricating a number."
    )
