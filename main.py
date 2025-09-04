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

# ---------------- Custom CSS for Styling ----------------
st.markdown("""
<style>
[data-testid="stMetricValue"] {
    font-size: 1.8em;
    justify-content: center;
}
[data-testid="stMetricLabel"] {
    justify-content: center;
}
.unsaved-badge {
    background-color: #FFC107;
    color: black;
    padding: 2px 6px;
    border-radius: 8px;
    font-size: 0.75em;
    margin-left: 8px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# ---------------- Snowflake Connection ----------------
try:
    conn = st.connection("snowflake")
    session = conn.session()  # Create session object here
except Exception as e:
    st.error(f"Failed to connect to Snowflake: {str(e)}")
    st.stop()

# ---------------- Snowflake Data Functions ----------------
# ... [REST OF THE CODE BEFORE MAIN APP UI] ...

# ---------------- Snowflake Data Functions ----------------
def load_user_profile(user_name: str) -> Dict[str, Any]:
    if not user_name or isinstance(user_name, list):
        st.error("Invalid user_name parameter (should be a string).")
        return {}
    try:
        # Use quoted identifier for case-sensitive column name
        df = session.table("USER_PROFILE").filter(col('"key"') == user_name).to_pandas()
        if not df.empty:
            try:
                return json.loads(df.iloc[0]['value'])  # Use lowercase column name
            except Exception as e:
                st.warning(f"Could not parse profile JSON: {e}")
                return {}
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
        target_table = session.table("USER_PROFILE")
        
        # Use quoted identifiers for case-sensitive column names
        source_df = session.create_dataframe(
            [(user_name, profile_json)],
            schema=['"key"', '"value"']  # Quoted identifiers
        )
        
        target_table.merge(
            source=source_df,
            join_expr=(target_table['"key"'] == source_df['"key"']),
            clauses=[
                when_matched().update({'"value"': source_df['"value"']}),
                when_not_matched().insert({'"key"': source_df['"key"'], '"value"': source_df['"value"']})
            ]
        ).collect()
    except Exception as e:
        st.error(f"Error saving profile for {user_name}: {e}")

def load_nutrition_log(user_name: str) -> pd.DataFrame:
    if not user_name or isinstance(user_name, list):
        st.error("Invalid user_name parameter (should be a string).")
        return pd.DataFrame()
    try:
        df = session.table("NUTRITION_LOG").filter(col('"USER_NAME"') == user_name).to_pandas()
        return df
    except Exception as e:
        st.error(f"Error loading nutrition log: {e}")
        return pd.DataFrame()


def save_log_batch(user_name: str, entries: List[Dict[str, Any]]):
    if not user_name or isinstance(user_name, list) or not entries:
        st.error("Invalid parameters for saving log batch.")
        return
    try:
        rows_to_insert = []
        for entry in entries:
            rows_to_insert.append({
                "USER_NAME": str(user_name),
                "Date": entry["DATE"],
                "Meal": str(entry["MEAL"]),
                "Food": str(entry["FOOD"]),
                "Quantity": float(entry["QUANTITY"]),
                "Calories": float(entry["CALORIES"]),
                "Protein": float(entry["PROTEIN"]),
                "Carbs": float(entry["CARBS"]),
                "Fat": float(entry["FAT"])
            })

        schema = StructType([
            StructField("USER_NAME", StringType()),
            StructField("Date", DateType()),
            StructField("Meal", StringType()),
            StructField("Food", StringType()),
            StructField("Quantity", FloatType()),
            StructField("Calories", FloatType()),
            StructField("Protein", FloatType()),
            StructField("Carbs", FloatType()),
            StructField("Fat", FloatType())
        ])

        df_to_save = session.create_dataframe(rows_to_insert, schema=schema)
        df_to_save.write.mode("append").save_as_table("NUTRITION_LOG")
        st.session_state.new_entries = []

    except Exception as e:
        print("--- AN ERROR OCCURRED DURING BATCH SAVE ---")
        print(traceback.format_exc())
        st.session_state.error_message = f"Failed to save data: {e}"


def delete_entry_from_db(entry_id: int):
    if isinstance(entry_id, list):
        st.error("Invalid entry_id parameter (should be an int).")
        return
    try:
        # Use the global session object
        session.sql(f'DELETE FROM NUTRITION_LOG WHERE "ID" = {entry_id}').collect()
    except Exception as e:
        st.error(f"Error deleting entry: {e}")

# ... [REST OF THE CODE REMAINS THE SAME - FOOD DATABASE, CALCULATIONS, UI] ...


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

with st.sidebar:
    st.header("👤 Your Profile")
    user_name = st.text_input("Enter your name to load/save a profile", "Guest")

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

        # Calculate targets
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

        st.markdown("---"); st.header("📈 Daily Targets")
        st.metric("🔥 Calories", f"{targets['calories']:.0f} kcal")
        st.metric("💪 Protein", f"{targets['protein']:.0f} g")
        st.metric("🍞 Carbs", f"{targets['carbs']:.0f} g")
        st.metric("🥑 Fat", f"{targets['fat']:.0f} g")
    else:
        st.warning("Please enter a name to use the app.")
        st.stop()

# ---------------- Load Logs ----------------
log_df_db = load_nutrition_log(user_name)
today_date = date.today()

df_new = pd.DataFrame(st.session_state.new_entries) if st.session_state.new_entries else pd.DataFrame()
df_display = pd.concat([log_df_db, df_new], ignore_index=True) if not df_new.empty else log_df_db.copy()
if not df_display.empty:
    df_display['DATE'] = pd.to_datetime(df_display['DATE']).dt.date
df_today = df_display[df_display['DATE'] == today_date] if not df_display.empty else pd.DataFrame()

# ---------------- Today's Totals ----------------
if not df_today.empty:
    totals = df_today[['CALORIES', 'PROTEIN', 'CARBS', 'FAT']].sum()
    st.subheader(f"Today's Totals for {user_name}")
    c = st.columns(4)
    c[0].metric("🔥 Total Calories", f"{totals['CALORIES']:.0f} kcal")
    c[1].metric("💪 Protein", f"{totals['PROTEIN']:.1f} g")
    c[2].metric("🍞 Carbohydrates", f"{totals['CARBS']:.1f} g")
    c[3].metric("🥑 Fat", f"{totals['FAT']:.1f} g")
    st.markdown("---")

# ---------------- Layout ----------------
col1, col2 = st.columns([1.5, 2], gap="large")

with col1:
    with st.container(border=True):
        st.header("🍛 Add Food Intake")
        with st.form("add_food_form", clear_on_submit=True):
            selected_food = st.selectbox(
                "Select Food",
                [""] + [f"{name} ({info['serving_size_g']}g)" for name, info in sorted(FOOD_DB.items())]
            )
            search_food = selected_food.rsplit(' (', 1)[0] if selected_food else None
            c1, c2 = st.columns(2)
            quantity = c1.number_input("Servings", 1, 20, 1, 1)
            meal_type = c2.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snacks"])
            if st.form_submit_button("➕ Add Food to Today's Log", use_container_width=True):
                if search_food and search_food in FOOD_DB:
                    info = FOOD_DB[search_food]
                    entry = {
                        "DATE": today_date,
                        "MEAL": meal_type,
                        "FOOD": search_food,
                        "QUANTITY": float(quantity),
                        "CALORIES": info["cal"] * quantity,
                        "PROTEIN": info["protein"] * quantity,
                        "CARBS": info["carbs"] * quantity,
                        "FAT": info["fat"] * quantity
                    }
                    st.session_state.new_entries.append(entry)
                    st.rerun()
                else: st.warning("Please select a valid food item.")

    # Today's Log
    if not df_today.empty:
        with st.container(border=True):
            st.header(f"📅 Today's Log")
            for meal in ["Breakfast", "Lunch", "Dinner", "Snacks"]:
                meal_df = df_today[df_today['MEAL'] == meal]
                if not meal_df.empty:
                    with st.expander(f"**{meal}** - {meal_df['CALORIES'].sum():.0f} kcal", expanded=True):
                        for _, row in meal_df.iterrows():
                            is_saved = 'ID' in row and pd.notna(row['ID'])
                            c1, c2, c3 = st.columns([4, 2, 1])
                            if not is_saved:
                                c1.markdown(f"{row['QUANTITY']}x {row['FOOD']} <span class='unsaved-badge'>Unsaved</span>", unsafe_allow_html=True)
                            else:
                                c1.text(f"{row['QUANTITY']}x {row['FOOD']}")
                                if c3.button("🗑️", key=f"del_{row['ID']}", help="Remove item"):
                                    delete_entry_from_db(int(row['ID']))
                                    st.rerun()
            
            if st.session_state.new_entries:
                st.markdown("---")
                if st.button("💾 Save Today's Log to Snowflake", use_container_width=True, type="primary"):
                    with st.spinner("Saving entries..."):
                        save_log_batch(user_name, st.session_state.new_entries)
                    if not st.session_state.get("error_message"):
                        st.session_state.new_entries = []
                        st.success("Successfully saved today's log!")
                    st.rerun()
with col2:
    with st.container(border=True):
        st.header("📊 Daily Progress Dashboard")
        if not df_today.empty and 'targets' in locals():
            totals = df_today[['PROTEIN', 'CARBS', 'FAT', 'CALORIES']].sum()
            targets = {
                "protein": profile.get("protein_target", 120),
                "carbs": profile.get("carbs_target", 160),
                "fat": profile.get("fat_target", 53),
                "calories": profile.get("calorie_target", 2000)
            }

            # ✅ Build DataFrame cleanly
            progress_df = pd.DataFrame({
                'Nutrient': ['Protein', 'Carbs', 'Fat'],
                'Consumed': [totals['PROTEIN'], totals['CARBS'], totals['FAT']],
                'Target': [targets['protein'], targets['carbs'], targets['fat']]
            })

            # ✅ Use Nutrient as index for charting
            st.bar_chart(progress_df.set_index('Nutrient'), height=300)
            st.write(f"**Total Calories:** {totals['CALORIES']} / {targets['calories']} kcal")
        else:
            st.info("Add food entries to see today's progress.")

    with st.container(border=True):
        st.header("📆 Weekly Calorie Trend")
        if not df_display.empty:
            week_start_date = date.today() - timedelta(days=6)
            week_df = df_display[pd.to_datetime(df_display['DATE']).dt.date >= week_start_date]
            if len(week_df) >= 1:
                daily_summary = week_df.groupby(pd.to_datetime(week_df['DATE']).dt.date)['CALORIES'].sum()
                all_days = pd.date_range(start=week_start_date, end=date.today(), freq='D').date
                daily_summary = daily_summary.reindex(all_days, fill_value=0)
                st.area_chart(daily_summary, height=250)
            else:
                st.info("Log meals for a couple of days to see your weekly trends.")
        else:
            st.info("Log meals to see your weekly trends.")
