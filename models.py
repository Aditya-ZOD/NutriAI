from pydantic import BaseModel, Field
from typing import Optional, List

# --- Auth Models ---
class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

# --- Profile Models ---
class ProfileUpdateRequest(BaseModel):
    age: Optional[int] = Field(None, ge=10, le=120)
    gender: Optional[str] = None
    height_cm: Optional[float] = Field(None, ge=50.0, le=260.0)
    weight_kg: Optional[float] = Field(None, ge=20.0, le=350.0)
    activity_level: Optional[str] = None
    goal: Optional[str] = None
    dietary_preference: Optional[str] = None
    allergies: Optional[str] = None
    daily_calorie_target: Optional[int] = Field(None, ge=800, le=6000)
    daily_water_target_ml: Optional[int] = Field(None, ge=500, le=10000)

# --- Nutrition & Meal Models ---
class MealCreateRequest(BaseModel):
    log_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    meal_category: str = Field(..., description="breakfast, lunch, snack, or dinner")
    food_name: str = Field(..., min_length=1, max_length=120)
    serving_size: float = Field(1.0, gt=0)
    calories: float = Field(..., ge=0)
    protein: Optional[float] = Field(0.0, ge=0)
    carbs: Optional[float] = Field(0.0, ge=0)
    fat: Optional[float] = Field(0.0, ge=0)

# --- Water & Weight Models ---
class WaterCreateRequest(BaseModel):
    log_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount_ml: int = Field(..., ge=10, le=5000)

class WeightCreateRequest(BaseModel):
    log_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    weight_kg: float = Field(..., ge=20.0, le=350.0)
    notes: Optional[str] = Field("", max_length=200)

# --- Plan Models ---
class PlanSaveRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100)
    plan_content: str = Field(..., min_length=10)

# --- Chat Models ---
class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field("New Nutrition Consultation", max_length=120)

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
