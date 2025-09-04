import streamlit as st
import pandas as pd
import json
from datetime import date, timedelta
from typing import Dict, Any, List

# Snowpark
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
    st.error("Failed to connect to Snowflake. Please check your configuration.")
    st.stop()

# ---------------- Snowflake Functions ----------------
def load_user_profile() -> Dict[str, Any]:
    """Load the single profile (no username)"""
    try:
        df = conn.query('SELECT VALUE FROM USER_PROFILE LIMIT 1', ttl=0)
        if not df.empty:
            return df.iloc[0]["VALUE"]  # Already VARIANT dict
        return {}
    except Exception as e:
        st.error(f"Error loading profile: {e}")
        return {}

def save_user_profile(profile_data: Dict[str, Any]):
    try:
        session = conn.session()
        source_df = session.create_dataframe([(profile_data,)], schema=["VALUE"])
        target_table = session.table("USER_PROFILE")
        target_table.merge(
            source=source_df,
            join_expr=None,  # Single-row table, no join needed
            clauses=[
                when_matched().update({"VALUE": source_df["VALUE"]}),
                when_not_matched().insert({"VALUE": source_df["VALUE"]})
            ]
        )
    except Exception as e:
        st.session_state.error_message = f"Error saving profile: {e}"

def load_nutrition_log() -> pd.DataFrame:
    try:
        df = conn.query('SELECT * FROM NUTRITION_LOG ORDER BY "ID" DESC', ttl=0)
        return df
    except Exception as e:
        st.error(f"Error loading nutrition log: {e}")
        return pd.DataFrame()

def save_log_batch(entries: List[Dict[str, Any]]):
    if not entries:
        return
    try:
        session = conn.session()
        df_to_save = session.create_dataframe(entries)
        target_columns = ["DATE", "MEAL", "FOOD", "QUANTITY", "CALORIES", "PROTEIN", "CARBS", "FAT"]
        df_to_save.write.mode("append").save_as_table("NUTRITION_LOG", column_order=target_columns)
    except Exception as e:
        st.session_state.error_message = f"Failed to save log data: {e}"

def delete_entry_from_db(entry_id: int):
    try:
        conn.query('DELETE FROM NUTRITION_LOG WHERE "ID" = ?', params=[entry_id])
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
    change = (weekly_change_kg * 7700) / 7
    target = base_calories - change if goal=="Weight Loss" else base_calories + change if goal=="Muscle Gain" else base_calories
    target = max(1200, target)
    return {"calories": target, "protein": target*0.3/4, "carbs": target*0.4/4, "fat": target*0.3/9}

# ---------------- Main App ----------------
st.title("🍽️ Nutrition & Calorie Tracker")

if 'error_message' in st.session_state and st.session_state.error_message:
    st.error(st.session_state.error_message)
    if st.button("Clear Error Message"):
        st.session_state.error_message = None
        st.rerun()

if 'new_entries' not in st.session_state:
    st.session_state.new_entries = []

# ---------------- Profile Inputs ----------------
profile = load_user_profile()
weight = st.number_input("Weight (kg)", 40.0, 200.0, float(profile.get("weight", 70.0)), 0.5)
height = st.number_input("Height (cm)", 120.0, 220.0, float(profile.get("height", 170.0)), 1.0)
age = st.number_input("Age", 10, 100, int(profile.get("age", 25)), 1)
gender = st.radio("Gender", ["Male", "Female"], index=["Male","Female"].index(profile.get("gender","Male")), horizontal=True)
activity_level = st.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(profile.get("activity_level","Sedentary (office job)")))
goal = st.radio("Goal", ["Maintain", "Weight Loss", "Muscle Gain"], index=["Maintain","Weight Loss","Muscle Gain"].index(profile.get("goal","Weight Loss")), horizontal=True)
weekly_change = st.slider("Weekly Weight Change (kg)", 0.0, 1.5, profile.get("weekly_change", 0.5), 0.1) if goal != "Maintain" else 0.0

tdee = calculate_tdee(weight, height, age, gender, activity_level)
targets = calculate_targets(tdee, goal, weekly_change)

if st.button("💾 Save All Changes", use_container_width=True, type="primary"):
    st.session_state.error_message = None
    save_user_profile({
        "weight": weight, "height": height, "age": age, "gender": gender,
        "activity_level": activity_level, "goal": goal, "weekly_change": weekly_change
    })
    if st.session_state.new_entries:
        save_log_batch(st.session_state.new_entries)
    if not st.session_state.get("error_message"):
        st.session_state.new_entries = []
        st.success("All changes saved successfully!")
        st.cache_data.clear()
    st.rerun()

# ---------------- Load Logs ----------------
log_df_db = load_nutrition_log()
today_date = date.today()
df_new = pd.DataFrame(st.session_state.new_entries) if st.session_state.new_entries else pd.DataFrame()
df_display = pd.concat([log_df_db, df_new], ignore_index=True) if not df_new.empty else log_df_db.copy()
if not df_display.empty:
    df_display['DATE'] = pd.to_datetime(df_display['DATE']).dt.date
    df_today = df_display[df_display['DATE'] == today_date]
else:
    df_today = pd.DataFrame()

# ---------------- Display Today's Totals ----------------
if not df_today.empty:
    totals = df_today[['CALORIES','PROTEIN','CARBS','FAT']].sum()
    st.subheader("Today's Totals")
    c = st.columns(4)
    c[0].metric("🔥 Calories", f"{totals['CALORIES']:.0f} kcal")
    c[1].metric("💪 Protein", f"{totals['PROTEIN']:.1f} g")
    c[2].metric("🍞 Carbs", f"{totals['CARBS']:.1f} g")
    c[3].metric("🥑 Fat", f"{totals['FAT']:.1f} g")
    st.markdown("---")

# ---------------- Add Food Intake & Log Display ----------------
col1, col2 = st.columns([1.5,2], gap="large")
with col1:
    st.header("🍛 Add Food Intake")
    with st.form("add_food_form", clear_on_submit=True):
        selected_food = st.selectbox("Select Food", [""] + [f"{name} ({info['serving_size_g']}g)" for name, info in FOOD_DB.items()])
        search_food = selected_food.rsplit(' (',1)[0] if selected_food else None
        c1,c2 = st.columns(2)
        quantity = c1.number_input("Servings", 1, 20, 1, 1)
        meal_type = c2.selectbox("Meal", ["Breakfast","Lunch","Dinner","Snacks"])
        if st.form_submit_button("➕ Add Food"):
            if search_food and search_food in FOOD_DB:
                info = FOOD_DB[search_food]
                entry = {
                    "DATE": today_date, "MEAL": meal_type, "FOOD": search_food,
                    "QUANTITY": float(quantity),
                    "CALORIES": info["cal"]*quantity,
                    "PROTEIN": info["protein"]*quantity,
                    "CARBS": info["carbs"]*quantity,
                    "FAT": info["fat"]*quantity
                }
                st.session_state.new_entries.append(entry)
                st.rerun()
            else:
                st.warning("Select a valid food item.")

with col2:
    st.header("📊 Daily Progress Dashboard")
    if not df_today.empty:
        totals = df_today[['CALORIES','PROTEIN','CARBS','FAT']].sum()
        st.progress(min(1.0, totals['CALORIES']/targets['calories']), text=f"{totals['CALORIES']:.0f}/{targets['calories']:.0f} kcal")
        progress_df = pd.DataFrame({
            'Consumed':[totals['PROTEIN'],totals['CARBS'],totals['FAT']],
            'Target':[targets['protein'],targets['carbs'],targets['fat']]
        }, index=['Protein','Carbs','Fat'])
        st.bar_chart(progress_df, height=300)
    else:
        st.info("Log meals to see progress dashboard.")

    st.header("📆 Weekly Calorie Trend")
    if not df_display.empty:
        week_start = date.today()-timedelta(days=6)
        week_df = df_display[pd.to_datetime(df_display['DATE']).dt.date>=week_start]
        if not week_df.empty:
            daily_summary = week_df.groupby(pd.to_datetime(week_df['DATE']).dt.date)['CALORIES'].sum()
            all_days = pd.date_range(week_start,date.today(),freq='D').date
            daily_summary = daily_summary.reindex(all_days, fill_value=0)
            st.area_chart(daily_summary, height=250)
        else: st.info("Log meals for a few days to see weekly trends.")
    else: st.info("Log meals to see weekly trends.")
