import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta, date
from snowflake.snowpark.functions import col, when_matched, when_not_matched

# ---------------- App Configuration ----------------
st.set_page_config(layout="wide", page_title="Nutrition & Calorie Tracker", page_icon="🍽️")

# ---------------- Custom CSS for Styling ----------------
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

# ---------------- Snowflake Data Functions ----------------

def load_user_profile() -> dict:
    try:
        df = conn.query('SELECT "VALUE" FROM USER_PROFILE WHERE "KEY" = \'guest\'', ttl=0)
        if not df.empty:
            return json.loads(df.iloc[0]["VALUE"])
        return {}
    except Exception as e:
        st.error(f"Error loading profile: {e}")
        return {}

def save_user_profile(profile_data: dict):
    try:
        profile_json = json.dumps(profile_data)
        session = conn.session()
        source_df = session.create_dataframe([('guest', profile_json)], schema=['KEY', 'VALUE'])
        target_table = session.table("USER_PROFILE")
        target_table.merge(
            source=source_df,
            join_expr=(target_table['KEY'] == source_df['KEY']),
            clauses=[
                when_matched().update({'VALUE': source_df['VALUE']}),
                when_not_matched().insert({'KEY': source_df['KEY'], 'VALUE': source_df['VALUE']})
            ]
        ).collect()
    except Exception as e:
        st.session_state.error_message = f"Error saving profile: {e}"

def load_nutrition_log() -> pd.DataFrame:
    try:
        df = conn.query('SELECT * FROM NUTRITION_LOG WHERE "USER_NAME" = \'guest\' ORDER BY "ID" DESC', ttl=0)
        return df
    except Exception as e:
        st.error(f"Error loading nutrition log: {e}")
        return pd.DataFrame()

def save_log_batch(entries: list):
    if not entries: 
        return
    try:
        session = conn.session()
        rows_to_insert = []
        for entry in entries:
            rows_to_insert.append({
                "USER_NAME": "guest",
                "DATE": entry["DATE"],
                "MEAL": entry["MEAL"],
                "FOOD": entry["FOOD"],
                "QUANTITY": float(entry["QUANTITY"]),
                "CALORIES": float(entry["CALORIES"]),
                "PROTEIN": float(entry["PROTEIN"]),
                "CARBS": float(entry["CARBS"]),
                "FAT": float(entry["FAT"])
            })
        
        target_columns = ["USER_NAME","DATE","MEAL","FOOD","QUANTITY","CALORIES","PROTEIN","CARBS","FAT"]
        # Pass list of dicts and schema explicitly
        df_to_save = session.create_dataframe(rows_to_insert, schema=target_columns)
        
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

# Persistent error message display
if 'error_message' in st.session_state and st.session_state.error_message:
    st.error(st.session_state.error_message)
    if st.button("Clear Error Message"):
        st.session_state.error_message = None
        st.rerun()

if 'new_entries' not in st.session_state:
    st.session_state.new_entries = []

# ---------------- Sidebar: Profile ----------------
st.sidebar.header("👤 Your Profile")
profile = load_user_profile()
weight = st.sidebar.number_input("Weight (kg)", 40.0, 200.0, profile.get("weight", 70.0), 0.5)
height = st.sidebar.number_input("Height (cm)", 120, 220, profile.get("height", 170), 1)
age = st.sidebar.number_input("Age", 10, 100, profile.get("age", 25), 1)
gender = st.sidebar.radio("Gender", ["Male", "Female"], index=["Male","Female"].index(profile.get("gender","Male")), horizontal=True)
activity_level = st.sidebar.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(profile.get("activity_level","Sedentary (office job)")))
goal = st.sidebar.radio("Goal", ["Maintain","Weight Loss","Muscle Gain"], index=["Maintain","Weight Loss","Muscle Gain"].index(profile.get("goal","Weight Loss")), horizontal=True)
weekly_change = st.sidebar.slider("Weekly Weight Change (kg)", 0.0, 1.5, profile.get("weekly_change",0.5), 0.1) if goal != "Maintain" else 0.0

tdee = calculate_tdee(weight, height, age, gender, activity_level)
targets = calculate_targets(tdee, goal, weekly_change)

if st.sidebar.button("💾 Save All Changes", use_container_width=True, type="primary"):
    st.session_state.error_message = None
    profile_data = {
        "weight": weight, "height": height, "age": age, "gender": gender,
        "activity_level": activity_level, "goal": goal, "weekly_change": weekly_change,
        "calorie_target": targets['calories'], "protein_target": targets['protein'],
        "carbs_target": targets['carbs'], "fat_target": targets['fat']
    }
    save_user_profile(profile_data)
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

if not df_today.empty:
    totals = df_today[['CALORIES','PROTEIN','CARBS','FAT']].sum()
    st.subheader("Today's Totals")
    c = st.columns(4)
    c[0].metric("🔥 Calories", f"{totals['CALORIES']:.0f} kcal")
    c[1].metric("💪 Protein", f"{totals['PROTEIN']:.1f} g")
    c[2].metric("🍞 Carbs", f"{totals['CARBS']:.1f} g")
    c[3].metric("🥑 Fat", f"{totals['FAT']:.1f} g")
    st.markdown("---")

# ---------------- Layout ----------------
col1, col2 = st.columns([1.5,2], gap="large")

# Left: Add Food
with col1:
    st.header("🍛 Add Food Intake")
    with st.form("add_food_form", clear_on_submit=True):
        selected_food = st.selectbox("Select Food", [""] + [f"{name} ({info['serving_size_g']}g)" for name, info in sorted(FOOD_DB.items())])
        search_food = selected_food.rsplit(" (",1)[0] if selected_food else None
        c1, c2 = st.columns(2)
        quantity = c1.number_input("Servings",1,20,1,1)
        meal_type = c2.selectbox("Meal", ["Breakfast","Lunch","Dinner","Snacks"])
        if st.form_submit_button("➕ Add Food"):
            if search_food and search_food in FOOD_DB:
                info = FOOD_DB[search_food]
                entry = {
                    "DATE": today_date, "MEAL": meal_type, "FOOD": search_food,
                    "QUANTITY": float(quantity), "CALORIES": info["cal"]*quantity,
                    "PROTEIN": info["protein"]*quantity, "CARBS": info["carbs"]*quantity,
                    "FAT": info["fat"]*quantity
                }
                st.session_state.new_entries.append(entry)
                st.rerun()
            else:
                st.warning("Please select a valid food item.")

    if not df_today.empty:
        st.header("📅 Today's Log")
        for meal in ["Breakfast","Lunch","Dinner","Snacks"]:
            meal_df = df_today[df_today['MEAL']==meal]
            if not meal_df.empty:
                with st.expander(f"**{meal}** - {meal_df['CALORIES'].sum():.0f} kcal", expanded=True):
                    for _, row in meal_df.iterrows():
                        c1,c2,c3 = st.columns([4,2,1])
                        c1.markdown(f"{row['QUANTITY']}x {row['FOOD']} <span class='unsaved-badge'>Unsaved</span>", unsafe_allow_html=True)
                        c2.text(f"{row['CALORIES']:.0f} kcal")

# Right: Progress Dashboard
with col2:
    st.header("📊 Daily Progress Dashboard")
    if not df_today.empty:
        totals = df_today[['CALORIES','PROTEIN','CARBS','FAT']].sum()
        st.subheader("🔥 Calories")
        progress_ratio = totals['CALORIES']/targets['calories'] if targets['calories']>0 else 0
        st.progress(min(1.0, progress_ratio), text=f"{totals['CALORIES']:.0f}/{targets['calories']:.0f} kcal")
        st.markdown("---"); st.subheader("💪 Macronutrients (grams)")
        progress_df = pd.DataFrame({'Consumed':[totals['PROTEIN'],totals['CARBS'],totals['FAT']],
                                    'Target':[targets['protein'],targets['carbs'],targets['fat']]},
                                    index=['Protein','Carbs','Fat'])
        st.bar_chart(progress_df, height=300)
    else:
        st.info("Log your first meal to see your progress dashboard!")

    st.header("📆 Weekly Calorie Trend")
    if not df_display.empty:
        week_start_date = date.today()-timedelta(days=6)
        week_df = df_display[pd.to_datetime(df_display['DATE']).dt.date>=week_start_date]
        if len(week_df)>=1:
            daily_summary = week_df.groupby(pd.to_datetime(week_df['DATE']).dt.date)['CALORIES'].sum()
            all_days = pd.date_range(start=week_start_date,end=date.today(),freq='D').date
            daily_summary = daily_summary.reindex(all_days, fill_value=0)
            st.area_chart(daily_summary, height=250)
        else:
            st.info("Log meals for a couple of days to see weekly trends.")
    else:
        st.info("Log meals to see weekly trends.")
