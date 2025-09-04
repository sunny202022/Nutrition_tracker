import streamlit as st
import pandas as pd
import json
import traceback
from typing import Dict, Any, List
from datetime import datetime, timedelta, date
from snowflake.snowpark.types import StructType, StructField, StringType, FloatType, DateType
from snowflake.snowpark.functions import col, when_matched, when_not_matched

# ---------------- App Configuration ----------------
st.set_page_config(layout="wide", page_title="Nutrition & Calorie Tracker", page_icon="🍽️")

# ---------------- Custom CSS ----------------
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.8em; justify-content: center; }
    [data-testid="stMetricLabel"] { justify-content: center; }
    .unsaved-badge {
        background-color: #FFC107; color: black; padding: 2px 6px;
        border-radius: 8px; font-size: 0.75em; margin-left: 8px; font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ---------------- Snowflake Connection ----------------
try:
    conn = st.connection("snowflake")
except Exception as e:
    st.error("Failed to connect to Snowflake. Please check your secrets.toml configuration.")
    st.stop()

# ---------------- Snowflake Functions ----------------
def load_user_profile(user_name: str) -> Dict[str, Any]:
    if not user_name or isinstance(user_name, list):
        st.error("Invalid user_name parameter (should be a string).")
        return {}
    try:
        session = conn.session()
        df = session.table("USER_PROFILE").filter(col("KEY") == user_name).to_pandas()
        if not df.empty:
            try:
                return json.loads(df.iloc[0]["PROFILE_JSON"])
            except Exception as e:
                st.warning(f"Could not parse profile JSON: {e}")
        return {}
    except Exception as e:
        st.error(f"Error loading profile for {user_name}: {e}")
        return {}

def save_user_profile(user_name: str, profile_data: Dict[str, Any]):
    if not user_name or isinstance(user_name, list):
        st.error("Invalid user_name parameter (should be a string).")
        return
    try:
        profile_json = json.dumps(profile_data)
        session = conn.session()
        target_table = session.table("USER_PROFILE")
        source_df = session.create_dataframe(
            [(user_name, profile_json)],
            schema=['KEY', 'PROFILE_JSON']
        )
        target_table.merge(
            source=source_df,
            join_expr=(target_table['KEY'] == source_df['KEY']),
            clauses=[
                when_matched().update({'PROFILE_JSON': source_df['PROFILE_JSON']}),
                when_not_matched().insert({'KEY': source_df['KEY'], 'PROFILE_JSON': source_df['PROFILE_JSON']})
            ]
        ).collect()

def load_nutrition_log(user_name: str) -> pd.DataFrame:
    if not user_name or isinstance(user_name, list):
        st.error("Invalid user_name parameter (should be a string).")
        return pd.DataFrame()
    try:
        df = conn.query('SELECT * FROM NUTRITION_LOG WHERE "user_name" = ? ORDER BY "id" DESC', params=[user_name], ttl=0)
        return df
    except Exception as e:
        st.error(f"Error loading nutrition log: {e}")
        return pd.DataFrame()

def save_log_batch(user_name: str, entries: List[Dict[str, Any]]):
    if not user_name or isinstance(user_name, list) or not entries:
        st.error("Invalid parameters for saving log batch.")
        return
    try:
        session = conn.session()
        rows_to_insert = []
        for entry in entries:
            rows_to_insert.append({
                "user_name": str(user_name),
                "date": entry["DATE"] if isinstance(entry["DATE"], (str, datetime, date)) else str(entry["DATE"]),
                "meal": str(entry["MEAL"]),
                "food": str(entry["FOOD"]),
                "quantity": float(entry["QUANTITY"]),
                "cal": float(entry["CALORIES"]),
                "protein": float(entry["PROTEIN"]),
                "carbs": float(entry["CARBS"]),
                "fat": float(entry["FAT"])
            })

        df_to_save = session.create_dataframe(rows_to_insert)
        df_to_save.write.mode("append").save_as_table(
            "NUTRITION_LOG",
            column_order=["user_name", "date", "meal", "food", "quantity", "cal", "protein", "carbs", "fat"]
        )
        st.cache_data.clear()
        st.session_state.error_message = None
    except Exception as e:
        st.session_state.error_message = f"Failed to save data: {e}"
        print(traceback.format_exc())

def delete_entry_from_db(entry_id: int):
    if isinstance(entry_id, list):
        st.error("Invalid entry_id parameter (should be an int).")
        return
    try:
        conn.query('DELETE FROM NUTRITION_LOG WHERE "id" = ?', params=[entry_id])
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error deleting entry: {e}")

# ---------------- Food Database ----------------
indian_food_data = { 
    "Food Item": ["Roti (Chapati)", "Phulka", "Tandoori Roti"],
    "Serving Size (g)": [40, 25, 50],
    "Calories (kcal)": [120, 70, 150],
    "Protein (g)": [3, 2, 4],
    "Carbohydrates (g)": [24, 15, 30],
    "Fats (g)": [1, 0.5, 2]
}

def format_food_database(data: dict) -> dict:
    df = pd.DataFrame(data).set_index('Food Item')
    df = df.rename(columns={
        'Calories (kcal)': 'cal',
        'Protein (g)': 'protein',
        'Carbohydrates (g)': 'carbs',
        'Fats (g)': 'fat',
        'Serving Size (g)': 'serving_size_g'
    })
    return df.to_dict(orient='index')

FOOD_DB = format_food_database(indian_food_data)

# ---------------- Activity Multipliers & TDEE ----------------
ACTIVITY_MULTIPLIERS = {
    "Sedentary (office job)": 1.2,
    "Lightly Active (1-3 days/week exercise)": 1.375,
    "Moderately Active (3-5 days/week exercise)": 1.55,
    "Very Active (6-7 days/week exercise)": 1.725,
    "Extra Active (hard labor, athlete)": 1.9
}

def calculate_tdee(weight_kg: float, height_cm: float, age: int, gender: str, activity_level: str) -> float:
    if gender == "Male":
        bmr = 88.362 + (13.397 * weight_kg) + (4.799 * height_cm) - (5.677 * age)
    else:
        bmr = 447.593 + (9.247 * weight_kg) + (3.098 * height_cm) - (4.330 * age)
    return bmr * ACTIVITY_MULTIPLIERS.get(activity_level, 1.2)

def calculate_targets(base_calories: float, goal: str, weekly_change_kg: float) -> dict:
    calorie_change_per_day = (weekly_change_kg * 7700) / 7
    target_calories = base_calories
    if goal == "Weight Loss":
        target_calories -= calorie_change_per_day
    elif goal == "Muscle Gain":
        target_calories += calorie_change_per_day
    target_calories = max(1200, target_calories)
    return {
        "calories": target_calories,
        "protein": (target_calories * 0.30) / 4,
        "carbs": (target_calories * 0.40) / 4,
        "fat": (target_calories * 0.30) / 9
    }

# ---------------- Main App ----------------
st.title("🍽️ Advanced Nutrition & Calorie Tracker")

# Persistent error display
if 'error_message' in st.session_state and st.session_state.error_message:
    st.error(st.session_state.error_message)
    if st.button("Clear Error Message"):
        st.session_state.error_message = None
        st.rerun()

if 'new_entries' not in st.session_state:
    st.session_state.new_entries = []

with st.sidebar:
    st.header("👤 Your Profile")
    user_name = st.text_input("Enter your name to load/save a profile", "Guest")
    if isinstance(user_name, list):
        st.error("Please enter a valid single name, not a list.")
        st.stop()

    if user_name:
        profile = load_user_profile(user_name)
        weight = st.number_input("Weight (kg)", 40.0, 200.0, profile.get("weight", 70.0), 0.5)
        height = st.number_input("Height (cm)", 120, 220, profile.get("height", 170), 1)
        age = st.number_input("Age", 10, 100, profile.get("age", 25), 1)
        gender = st.radio("Gender", ["Male", "Female"], index=["Male", "Female"].index(profile.get("gender", "Male")), horizontal=True)
        activity_level = st.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(profile.get("activity_level", "Sedentary (office job)")))
        st.header("🎯 Your Goal")
        goal = st.radio("Goal", ["Maintain", "Weight Loss", "Muscle Gain"], index=["Maintain", "Weight Loss", "Muscle Gain"].index(profile.get("goal", "Weight Loss")), horizontal=True)
        weekly_change = st.slider("Weekly Weight Change (kg)", 0.0, 1.5, profile.get("weekly_change", 0.5), 0.1) if goal != "Maintain" else 0.0

        tdee = calculate_tdee(weight, height, age, gender, activity_level)
        targets = calculate_targets(tdee, goal, weekly_change)

        if st.button("💾 Save Profile & Goals", use_container_width=True, type="primary"):
            profile_data = {
                "weight": weight,
                "height": height,
                "age": age,
                "gender": gender,
                "activity_level": activity_level,
                "goal": goal,
                "weekly_change": weekly_change,
                "calorie_target": targets["calories"],
                "protein_target": targets["protein"],
                "carbs_target": targets["carbs"],
                "fat_target": targets["fat"]
            }
            save_user_profile(user_name, profile_data)
            st.success(f"Profile saved for {user_name}!")
            st.rerun()
