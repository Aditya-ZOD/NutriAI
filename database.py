import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("NUTRI_DB_PATH", os.path.join(os.path.dirname(__file__), "users.db"))

@contextmanager
def get_db():
    """Context manager for thread-safe SQLite connection with WAL mode."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initializes and migrates the SQLite database schema cleanly."""
    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Users table (support legacy schema and migrations)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT,
                password_hash TEXT,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Check existing columns in users for safe schema migration
        cursor.execute("PRAGMA table_info(users);")
        user_cols = [row["name"] for row in cursor.fetchall()]
        if "password_hash" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT;")
        if "role" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user';")
        if "created_at" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP;")

        # 2. Sessions table for server-side token management
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")

        # 3. User Profiles table (for personalized AI context & dashboard goals)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                age INTEGER DEFAULT 25,
                gender TEXT DEFAULT 'other',
                height_cm REAL DEFAULT 170.0,
                weight_kg REAL DEFAULT 70.0,
                activity_level TEXT DEFAULT 'moderate',
                goal TEXT DEFAULT 'healthy_lifestyle',
                dietary_preference TEXT DEFAULT 'vegetarian',
                allergies TEXT DEFAULT '',
                daily_calorie_target INTEGER DEFAULT 2000,
                daily_water_target_ml INTEGER DEFAULT 2500,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # 4. Conversations table (user-isolated chat sessions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);")

        # 5. Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);")

        # 6. Meal Logs table (with estimated calories and macros)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                meal_category TEXT NOT NULL,
                food_name TEXT NOT NULL,
                serving_size REAL DEFAULT 1.0,
                calories REAL NOT NULL,
                protein REAL DEFAULT 0.0,
                carbs REAL DEFAULT 0.0,
                fat REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meal_logs(user_id, log_date);")

        # 7. Water Logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS water_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                amount_ml INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_water_user_date ON water_logs(user_id, log_date);")

        # 8. Weight Logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weight_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_weight_user ON weight_logs(user_id, log_date);")

        # 9. Saved Diet Plans table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diet_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                plan_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_plans_user ON diet_plans(user_id);")

        # 10. Verified Food Items dataset
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS food_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                serving_unit TEXT NOT NULL,
                default_serving REAL NOT NULL,
                calories REAL NOT NULL,
                protein REAL NOT NULL,
                carbs REAL NOT NULL,
                fat REAL NOT NULL,
                dietary_tags TEXT DEFAULT '',
                allergens TEXT DEFAULT ''
            );
        """)

        # Safe schema migration for food_items
        cursor.execute("PRAGMA table_info(food_items);")
        food_cols = [row["name"] for row in cursor.fetchall()]
        if "dietary_tags" not in food_cols:
            cursor.execute("ALTER TABLE food_items ADD COLUMN dietary_tags TEXT DEFAULT '';")
        if "allergens" not in food_cols:
            cursor.execute("ALTER TABLE food_items ADD COLUMN allergens TEXT DEFAULT '';")

        # Seed or refresh verified food composition dataset
        seed_foods(cursor)

def seed_foods(cursor):
    """Populates verified nutrition data for Indian & global staple foods with dietary tags and allergens."""
    foods = [
        # name, category, serving_unit, default_serving, calories, protein, carbs, fat, dietary_tags, allergens
        ("Roti (Whole Wheat Chapati)", "Grains", "piece (35g)", 1.0, 104.0, 3.1, 20.0, 0.9, "vegetarian,vegan", "gluten"),
        ("Cooked White Rice (Basmati)", "Grains", "bowl (150g)", 1.0, 195.0, 4.0, 43.0, 0.4, "vegetarian,vegan,gluten_free", ""),
        ("Cooked Brown Rice", "Grains", "bowl (150g)", 1.0, 168.0, 3.8, 35.0, 1.4, "vegetarian,vegan,gluten_free", ""),
        ("Dal (Cooked Yellow Toor/Moong)", "Legumes", "katori (150g)", 1.0, 148.0, 9.2, 22.0, 2.5, "vegetarian,vegan,gluten_free", ""),
        ("Paneer (Raw Indian Cottage Cheese)", "Dairy", "serving (100g)", 1.0, 265.0, 18.3, 3.0, 20.8, "vegetarian,gluten_free", "dairy"),
        ("Tofu (Firm)", "Soy / Vegan", "serving (100g)", 1.0, 144.0, 17.3, 2.8, 8.7, "vegetarian,vegan,gluten_free", "soy"),
        ("Chicken Breast (Cooked / Grilled)", "Poultry", "serving (100g)", 1.0, 165.0, 31.0, 0.0, 3.6, "non_veg,gluten_free", ""),
        ("Egg (Whole Boiled)", "Eggs", "large egg", 1.0, 78.0, 6.3, 0.6, 5.3, "eggetarian,gluten_free", "eggs"),
        ("Egg White (Boiled)", "Eggs", "large egg white", 1.0, 17.0, 3.6, 0.2, 0.1, "eggetarian,gluten_free", "eggs"),
        ("Oats (Cooked in Water)", "Breakfast", "bowl (200g)", 1.0, 142.0, 5.0, 25.0, 2.5, "vegetarian,vegan", ""),
        ("Plain Curd / Dahi (Low Fat)", "Dairy", "katori (100g)", 1.0, 60.0, 3.5, 4.7, 3.1, "vegetarian,gluten_free", "dairy"),
        ("Greek Yogurt (Plain)", "Dairy", "cup (150g)", 1.0, 130.0, 15.0, 6.0, 4.0, "vegetarian,gluten_free", "dairy"),
        ("Idli (Steamed)", "Breakfast", "piece (40g)", 2.0, 130.0, 4.0, 26.0, 0.4, "vegetarian,vegan,gluten_free", ""),
        ("Plain Dosa", "Breakfast", "medium dosa", 1.0, 168.0, 3.8, 29.0, 3.7, "vegetarian,vegan,gluten_free", ""),
        ("Sambhar (Vegetable Lentil Stew)", "Legumes", "bowl (150g)", 1.0, 110.0, 4.5, 17.0, 2.8, "vegetarian,vegan,gluten_free", ""),
        ("Chana Masala (Cooked Chickpeas)", "Legumes", "katori (150g)", 1.0, 210.0, 10.5, 32.0, 4.5, "vegetarian,vegan,gluten_free", ""),
        ("Rajma Curry (Kidney Beans)", "Legumes", "katori (150g)", 1.0, 195.0, 9.8, 30.0, 3.8, "vegetarian,vegan,gluten_free", ""),
        ("Mixed Vegetable Sabzi", "Vegetables", "katori (150g)", 1.0, 120.0, 2.8, 14.0, 5.5, "vegetarian,vegan,gluten_free", ""),
        ("Palak Paneer", "Curry", "katori (150g)", 1.0, 230.0, 11.2, 8.0, 16.5, "vegetarian,gluten_free", "dairy"),
        ("Poha (Flattened Rice with Veggies)", "Breakfast", "plate (150g)", 1.0, 180.0, 3.5, 33.0, 4.2, "vegetarian,vegan,gluten_free", ""),
        ("Upma (Semolina / Rava)", "Breakfast", "plate (150g)", 1.0, 190.0, 4.2, 34.0, 4.0, "vegetarian,vegan", "gluten"),
        ("Moong Dal Khichdi", "Main Course", "bowl (200g)", 1.0, 220.0, 8.2, 38.0, 4.0, "vegetarian,gluten_free", ""),
        ("Sprouted Moong Salad", "Salads", "cup (100g)", 1.0, 105.0, 7.0, 19.0, 0.5, "vegetarian,vegan,gluten_free", ""),
        ("Soy Chunks Curry (Nutrela)", "Soy / Vegan", "katori (100g)", 1.0, 160.0, 16.0, 12.0, 4.0, "vegetarian,vegan,gluten_free", "soy"),
        ("Banana (Medium)", "Fruits", "medium (118g)", 1.0, 105.0, 1.3, 27.0, 0.3, "vegetarian,vegan,gluten_free", ""),
        ("Apple (Medium)", "Fruits", "medium (182g)", 1.0, 95.0, 0.5, 25.0, 0.3, "vegetarian,vegan,gluten_free", ""),
        ("Raw Almonds", "Nuts & Seeds", "handful (28g / 23 almonds)", 1.0, 164.0, 6.0, 6.1, 14.2, "vegetarian,vegan,gluten_free", "nuts"),
        ("Walnuts", "Nuts & Seeds", "handful (28g)", 1.0, 185.0, 4.3, 3.9, 18.5, "vegetarian,vegan,gluten_free", "nuts"),
        ("Peanut Butter (Natural)", "Spreads", "tablespoon (16g)", 1.0, 95.0, 4.0, 3.0, 8.0, "vegetarian,vegan,gluten_free", "peanuts,nuts"),
        ("Whey Protein (Standard Scoop)", "Supplements", "scoop (30g)", 1.0, 120.0, 24.0, 2.0, 1.5, "vegetarian,gluten_free", "dairy"),
        ("Cow Milk (Toned)", "Dairy", "glass (200ml)", 1.0, 120.0, 6.2, 9.6, 6.0, "vegetarian,gluten_free", "dairy"),
        ("Cucumber Salad with Lemon", "Salads", "plate (150g)", 1.0, 30.0, 1.0, 6.0, 0.2, "vegetarian,vegan,gluten_free", ""),
        ("Green Tea (Unsweetened)", "Beverage", "cup (200ml)", 1.0, 2.0, 0.2, 0.0, 0.0, "vegetarian,vegan,gluten_free", ""),
        ("Coffee with Milk (Light Sugar)", "Beverage", "cup (150ml)", 1.0, 65.0, 2.5, 8.0, 2.0, "vegetarian,gluten_free", "dairy")
    ]
    cursor.executemany("""
        INSERT INTO food_items 
        (name, category, serving_unit, default_serving, calories, protein, carbs, fat, dietary_tags, allergens)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category = excluded.category,
            serving_unit = excluded.serving_unit,
            default_serving = excluded.default_serving,
            calories = excluded.calories,
            protein = excluded.protein,
            carbs = excluded.carbs,
            fat = excluded.fat,
            dietary_tags = excluded.dietary_tags,
            allergens = excluded.allergens;
    """, foods)

def seed_demo_account(email: str = "demo@nutriai.local", password_hash: str = None):
    """Safely seeds an optional demo account for review/testing without real personal data."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?;", (email,))
        if not cursor.fetchone():
            from security import hash_password
            pw_hash = password_hash or hash_password("DemoNutri2026!")
            cursor.execute("""
                INSERT INTO users (name, email, password_hash, role)
                VALUES ('Demo User', ?, ?, 'user');
            """, (email, pw_hash))
            user_id = cursor.lastrowid
            cursor.execute("""
                INSERT OR IGNORE INTO user_profiles (user_id, age, gender, height_cm, weight_kg, goal, dietary_preference, daily_calorie_target, daily_water_target_ml)
                VALUES (?, 26, 'female', 165.0, 60.0, 'fat_loss', 'vegetarian', 1850, 2500);
            """, (user_id,))
            print(f"Created demo account: {email}")

if __name__ == "__main__":
    init_db()
    if os.environ.get("SEED_DEMO", "").lower() in ["1", "true", "yes"]:
        seed_demo_account()
    print("Database ready.")
