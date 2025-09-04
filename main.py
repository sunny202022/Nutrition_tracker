import streamlit as st
import pandas as pd
import json
from typing import Dict, Any
from datetime import datetime, timedelta, date
# <-- FIXED: Import when_matched and when_not_matched
from snowflake.snowpark.functions import col, when_matched, when_not_matched
# ---------------- App Configuration ----------------
st.set_page_config(layout="wide", page_title="Nutrition & Calorie Tracker", page_icon="🍽️")

# ---------------- Custom CSS for Styling ----------------
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.8em; justify-content: center; }
    [data-testid="stMetricLabel"] { justify-content: center; }
</style>
""", unsafe_allow_html=True)

# ---------------- Snowflake Connection ----------------
# Uses [connections.snowflake] from .streamlit/secrets.toml
try:
    conn = st.connection("snowflake")
except Exception as e:
    st.error("Failed to connect to Snowflake. Please check your secrets.toml configuration.")
    st.stop()


# ---------------- Snowflake Data Functions (Corrected & Secure) ----------------

def load_user_profile(user_name: str) -> Dict[str, Any]:
    """Load a specific user's profile from Snowflake using a parameterized query."""
    if not user_name:
        return {}
    try:
        # FIXED: Use parameters to prevent SQL injection
        df = conn.query(
    'SELECT * FROM NUTRITION_LOG WHERE USER_NAME = ? ORDER BY "ID" DESC', # <-- Use ?
    params=[user_name.lower()], # <-- List
    ttl=0
)
        if not df.empty:
            return json.loads(df.iloc[0]["VALUE"])
        return {} # Return an empty dict if the user is new
    except Exception as e:
        st.error(f"Error loading profile for {user_name}: {e}")
        return {}

def save_user_profile(user_name: str, profile_data: Dict[str, Any]):
    """Save or update user profile in Snowflake using a secure MERGE command."""
    if not user_name:
        return
    try:
        profile_json = json.dumps(profile_data)
        # Snowpark session for merge
        session = conn.session()
        source_df = session.create_dataframe(
            [(user_name.lower(), profile_json)],
            schema=['KEY', 'VALUE']
        )
        target_table = session.table("USER_PROFILE")
        target_table.merge(
            source=source_df,
            join_expr=(target_table['KEY'] == source_df['KEY']),
            clauses=[
                when_matched().update({'VALUE': source_df['VALUE']}),
                when_not_matched().insert({'KEY': source_df['KEY'], 'VALUE': source_df['VALUE']})
            ]
        )
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error saving profile: {e}")

def load_nutrition_log(user_name: str) -> pd.DataFrame:
    """Load all nutrition logs for a user using a parameterized query."""
    if not user_name:
        return pd.DataFrame()
    try:
        # FIXED: Use parameters to prevent SQL injection
        df = conn.query(
            'SELECT * FROM NUTRITION_LOG WHERE USER_NAME = :user ORDER BY "ID" DESC',
            params={"user": user_name.lower()},
            ttl=0
        )
        return df
    except Exception as e:
        st.error(f"Error loading nutrition log: {e}")
        return pd.DataFrame()

def save_entry_to_db(user_name: str, entry: Dict[str, Any]):
    """Insert a new food log entry using a Snowpark DataFrame."""
    if not user_name:
        return
    try:
        session = conn.session()
        # Add user_name to the entry
        entry_with_user = {"USER_NAME": user_name.lower(), **entry}
        
        # FIXED: Ensure column names and order match the table schema
        df_entry = session.create_dataframe([entry_with_user])
        df_entry.write.mode("append").save_as_table("NUTRITION_LOG")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error saving food entry: {e}")

def delete_entry_from_db(entry_id: int):
    """Deletes an entry by its unique ID."""
    try:
        # FIXED: Use the 'ID' column for deletion
        conn.query('DELETE FROM NUTRITION_LOG WHERE "ID" = :id', params={"id": entry_id})
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error deleting entry: {e}")
# ---------------- Food Database ----------------
indian_food_data = {
    "Food Item": [
        # Grains & Breads (20)
        "Roti (Chapati)", "Phulka", "Tandoori Roti", "Naan (Plain)", "Butter Naan",
        "Paratha (Plain)", "Aloo Paratha", "Gobi Paratha", "Thepla", "Puri",
        "Bhatura", "Bajra Roti", "Jowar Roti", "Makki di Roti",
        "White Bread (1 slice)", "Brown Bread (1 slice)", "Appam", "Puran Poli",
        "Rumali Roti", "Missi Roti",
        # Lentils & Pulses (20)
        "Moong Dal (Cooked)", "Toor Dal (Cooked)", "Chana Dal (Cooked)", "Masoor Dal (Cooked)", "Urad Dal (Cooked)",
        "Rajma (Cooked)", "Chole (Cooked)", "Kala Chana (Cooked)", "Green Moong (Cooked)", "Soybean (Cooked)",
        "Sprouted Moong Salad", "Sambar", "Dal Tadka", "Dal Makhani", "Pesarattu",
        "Khichdi", "Adai", "Panchmel Dal", "Roasted Bengal Gram", "Horse Gram (Cooked)",
        # Vegetables & Curries (20)
        "Aloo Sabzi", "Aloo Matar", "Aloo Gobi", "Bhindi Masala", "Baingan Bharta",
        "Mixed Vegetable Curry", "Cabbage Sabzi", "Lauki Curry", "Tinda Sabzi", "Karela Fry",
        "Palak Paneer", "Matar Paneer", "Paneer Butter Masala", "Shahi Paneer", "Chole Masala",
        "Rajma Curry", "Kadhi Pakora", "Dum Aloo", "Vegetable Kofta Curry", "Soya Chunk Curry",
        # Rice & Biryani/Pulao (15)
        "Plain Rice", "Jeera Rice", "Veg Pulao", "Veg Biryani", "Hyderabadi Chicken Biryani",
        "Mutton Biryani", "Curd Rice", "Lemon Rice", "Tamarind Rice", "Khichdi (Rice + Dal)",
        "Fried Rice (Veg)", "Egg Fried Rice", "Chicken Fried Rice", "Paneer Pulao", "Peas Pulao",
        # Breakfast (15)
        "Idli", "Dosa (Plain)", "Masala Dosa", "Medu Vada", "Upma",
        "Poha", "Sabudana Khichdi", "Pesarattu Dosa", "Uttapam", "Pongal",
        "Paratha + Curd", "Chole Bhature", "Aloo Puri", "Pesarattu + Chutney", "Puttu + Kadala Curry",
        # Snacks & Street Food (20)
        "Samosa", "Kachori", "Pakora (Onion)", "Pakora (Paneer)", "Bread Pakora",
        "Pav Bhaji", "Vada Pav", "Dabeli", "Sev Puri", "Bhel Puri",
        "Pani Puri", "Aloo Tikki", "Chaat Papdi", "Kathi Roll (Veg)", "Egg Roll",
        "Chicken Roll", "Spring Roll", "Manchurian (Veg)", "Cutlet (Veg)", "Paneer Tikka",
        # Sweets & Desserts (15)
        "Gulab Jamun", "Rasgulla", "Sandesh", "Kheer", "Gajar Halwa",
        "Moong Dal Halwa", "Ladoo (Besan)", "Ladoo (Motichoor)", "Jalebi", "Rava Kesari",
        "Mysore Pak", "Barfi (Kaju)", "Peda", "Rasgulla (Chhena)", "Payasam",
        # Fruits (15)
        "Banana", "Apple", "Mango", "Papaya", "Guava",
        "Pineapple", "Watermelon", "Muskmelon", "Orange", "Pomegranate",
        "Grapes", "Chikoo", "Lychee", "Pear", "Strawberry",
        # Nuts & Dry Fruits (10)
        "Almonds", "Cashews", "Pistachios", "Walnuts", "Peanuts",
        "Raisins", "Dates", "Figs", "Dry Coconut", "Fox Nuts (Makhana)",
        # Dairy & Drinks (15)
        "Milk (Cow)", "Milk (Buffalo)", "Curd", "Paneer", "Cheese",
        "Butter", "Ghee", "Lassi (Sweet)", "Chaas (Buttermilk)", "Milkshake (Banana)",
        "Tea (with Milk)", "Coffee (with Milk)", "Badam Milk", "Masala Chai", "Hot Chocolate",
        # Non-Veg (15)
        "Egg (Boiled)", "Omelette", "Chicken Curry", "Butter Chicken", "Chicken Tikka",
        "Tandoori Chicken", "Mutton Curry", "Mutton Rogan Josh", "Fish Curry", "Fish Fry",
        "Prawn Curry", "Prawn Fry", "Egg Curry", "Keema Mutton", "Chicken 65"
    ],
    "Category": (
        ["Grains"]*20 + ["Lentils & Pulses"]*20 + ["Vegetables & Curries"]*20 +
        ["Rice & Biryani"]*15 + ["Breakfast"]*15 + ["Snacks & Street Food"]*20 +
        ["Sweets & Desserts"]*15 + ["Fruits"]*15 + ["Nuts & Dry Fruits"]*10 +
        ["Dairy & Drinks"]*15 + ["Non-Veg"]*15
    ),
    "Serving Size (g)": [
        40,25,50,70,75,80,100,100,60,30,75,45,45,60,25,28,70,80,40,60,
        100,100,100,100,100,100,100,100,100,100,80,150,150,150,120,200,120,150,100,100,
        100,150,150,100,150,150,100,150,100,100,150,150,180,180,150,150,180,150,180,150,
        150,150,180,200,250,250,180,180,180,200,200,220,220,200,180,
        40,70,120,60,150,100,150,100,150,180,200,250,200,180,220,
        80,80,70,80,90,200,150,150,120,120,120,100,120,180,180,200,150,150,100,120,
        50,50,50,150,100,100,40,40,60,80,60,50,40,60,150,
        100,150,200,150,150,150,200,200,150,150,150,150,100,150,100,
        28,28,28,28,28,30,30,30,30,30,
        200,200,100,100,30,10,10,200,200,250,150,150,200,150,200,
        50,60,150,180,120,150,180,200,150,120,150,120,150,150,150
    ],
    "Calories (kcal)": [
        120,70,150,220,260,240,290,280,180,100,210,120,110,200,70,75,120,250,100,140,
        105,120,130,115,127,140,160,150,118,170,90,180,200,280,180,210,200,190,360,140,
        120,160,150,110,140,170,90,95,85,100,220,240,320,340,250,260,200,180,300,210,
        180,200,240,280,400,480,210,230,250,200,300,320,350,260,240,
        70,120,200,150,180,120,190,180,200,250,300,400,320,280,400,
        130,150,180,200,220,350,300,280,180,160,150,180,200,280,300,350,250,280,180,250,
        150,120,140,210,250,280,160,170,220,200,250,200,160,170,220,
        90,80,150,60,68,50,40,45,60,80,70,90,60,85,35,
        170,160,170,180,160,100,120,110,200,95,
        120,150,60,260,120,72,90,150,40,220,60,80,180,50,210,
        70,90,250,320,200,220,350,400,220,200,240,220,210,300,280
    ],
    "Protein (g)": [
        3,2,4,6,7,6,7.5,7,4,2,5.5,3.5,3,4.5,2.3,2.6,3,6,3,4,
        7,6.5,7,8,7.5,9,8,8.5,8,12,6,8,9,12,9,7,10,9.5,18,11,
        2,4,4,3,4,5,2,3,2,2,10,12,10,12,9,10,7,5,8,12,
        4,4,6,6,12,15,5,5,6,6,8,10,12,8,7,
        2,3,4,4,5,3,4,6,5,7,8,10,6,7,9,
        3,4,5,7,8,9,8,7,4,4,3,5,5,7,9,12,6,7,4,10,
        3,2,3,6,5,6,3,3,2,4,6,5,4,3,6,
        1,0.5,1.5,0.6,1,0.5,0.8,0.9,1.2,1.5,0.7,0.9,0.8,1,0.7,
        6,5,6,7,7,1,1,1,2,3,
        6,8,4,18,7,0.1,0,6,2,8,1,1,5,1,6,
        6,7,20,22,18,20,25,28,22,20,24,23,20,26,24
    ],
    "Carbohydrates (g)": [
        24,15,30,38,40,36,45,44,28,12,32,22,22,35,13,13,25,45,20,26,
        19,20,22,18,20,24,27,26,19,15,16,28,25,32,28,32,30,27,60,25,
        18,22,20,12,18,20,10,14,10,12,12,14,18,16,20,22,15,20,22,16,
        38,42,45,48,55,60,44,46,48,40,50,52,54,48,46,
        15,20,30,25,28,25,35,28,32,36,45,55,48,40,50,
        18,22,25,20,22,45,40,42,30,28,26,32,34,36,38,40,35,36,28,30,
        25,28,30,35,40,42,28,30,38,36,35,32,28,30,40,
        23,22,35,15,14,13,10,11,15,18,17,20,16,22,8,
        6,9,8,7,6,22,30,27,12,18,
        12,11,5,6,1,0,0,20,4,28,14,12,22,12,25,
        1,1,6,8,5,4,3,4,0,2,0,1,2,1,3
    ],
    "Fats (g)": [
        1,0.5,2,4,8,8,9,9,5,4.5,7,1.5,1.2,3,1,1,2,8,1.5,2,
        0.8,1.2,1.5,0.9,1.1,1.2,2.5,2,1,7,0.5,4,7,12,6,3,7,6,5,1.2,
        5,8,7,6,8,9,4,4,3,6,15,16,25,27,12,11,10,12,20,9,
        1,2,4,6,12,15,3,5,6,4,8,10,12,6,5,
        0.5,3,6,8,5,3,5,6,7,8,12,20,15,10,18,
        7,8,10,12,14,18,15,16,10,8,6,9,10,14,15,18,12,14,8,16,
        5,3,4,6,10,12,8,9,12,8,10,12,6,8,7,
        0.3,0.2,0.4,0.2,0.4,0.3,0.2,0.2,0.1,0.3,0.2,0.3,0.2,0.2,0.1,
        15,14,14,16,14,0.5,0.5,0.5,18,1,
        5,8,3,20,9,8,10,5,1,5,2,2,7,2,8,
        5,7,15,20,12,14,22,25,12,14,15,14,12,20,18
    ]
}

def format_food_database(data: dict) -> dict:
    df = pd.DataFrame(data).set_index('Food Item')
    df = df.rename(columns={
        'Calories (kcal)': 'cal', 'Protein (g)': 'protein',
        'Carbohydrates (g)': 'carbs', 'Fats (g)': 'fat',
        'Serving Size (g)': 'serving_size_g'
    })
    return df.to_dict(orient='index')

FOOD_DB = format_food_database(indian_food_data)

# ---------------- Calculation Functions (No Changes) ----------------
ACTIVITY_MULTIPLIERS = {
    "Sedentary (office job)": 1.2,
    "Lightly Active (1-3 days/week exercise)": 1.375,
    "Moderately Active (3-5 days/week exercise)": 1.55,
    "Very Active (6-7 days/week exercise)": 1.725,
    "Extra Active (hard labor, athlete)": 1.9,
}

def calculate_tdee(weight_kg: float, height_cm: float, age: int, gender: str, activity_level: str) -> float:
    if gender == "Male": bmr = 88.362 + (13.397 * weight_kg) + (4.799 * height_cm) - (5.677 * age)
    else: bmr = 447.593 + (9.247 * weight_kg) + (3.098 * height_cm) - (4.330 * age)
    return bmr * ACTIVITY_MULTIPLIERS.get(activity_level, 1.2)

def calculate_targets(base_calories: float, goal: str, weekly_change_kg: float) -> dict:
    calorie_change_per_day = (weekly_change_kg * 7700) / 7
    target_calories = base_calories
    if goal == "Weight Loss": target_calories -= calorie_change_per_day
    elif goal == "Muscle Gain": target_calories += calorie_change_per_day
    target_calories = max(1200, target_calories)
    return {"calories": target_calories, "protein": (target_calories * 0.30) / 4, "carbs": (target_calories * 0.40) / 4, "fat": (target_calories * 0.30) / 9}

# ---------------- Main App UI (Corrected Logic Flow) ----------------
st.title("🍽️ Advanced Nutrition & Calorie Tracker")

# --- Sidebar for User Profile Management ---
with st.sidebar:
    st.header("👤 Your Profile")
    user_name = st.text_input("Enter your name to load/save a profile", "Guest")

    if user_name:
        profile = load_user_profile(user_name)
        weight = st.number_input("Weight (kg)", 40.0, 200.0, profile.get("weight", 70.0), 0.5)
        height = st.number_input("Height (cm)", 120, 220, profile.get("height", 170), 1)
        age = st.number_input("Age", 10, 100, profile.get("age", 25), 1)
        gender_options = ["Male", "Female"]
        activity_options = list(ACTIVITY_MULTIPLIERS.keys())
        goal_options = ["Maintain", "Weight Loss", "Muscle Gain"]
        gender = st.radio("Gender", gender_options, index=gender_options.index(profile.get("gender", "Male")), horizontal=True)
        activity_level = st.selectbox("Activity Level", activity_options, index=activity_options.index(profile.get("activity_level", "Sedentary (office job)")))
        st.header("🎯 Your Goal")
        goal = st.radio("Goal", goal_options, index=goal_options.index(profile.get("goal", "Weight Loss")), horizontal=True)
        weekly_change = st.slider("Weekly Weight Change (kg)", 0.0, 1.5, profile.get("weekly_change", 0.5), 0.1) if goal != "Maintain" else 0.0

        if st.button("💾 Save Profile & Goals", use_container_width=True, type="primary"):
            profile_data = {"weight": weight, "height": height, "age": age, "gender": gender, "activity_level": activity_level, "goal": goal, "weekly_change": weekly_change}
            save_user_profile(user_name, profile_data)
            st.success(f"Profile saved for {user_name}!")
            st.rerun()

        tdee = calculate_tdee(weight, height, age, gender, activity_level)
        targets = calculate_targets(tdee, goal, weekly_change)
        st.markdown("---")
        st.header("📈 Daily Targets")
        st.metric("🔥 Calories", f"{targets['calories']:.0f} kcal")
        st.metric("💪 Protein", f"{targets['protein']:.0f} g")
        st.metric("🍞 Carbs", f"{targets['carbs']:.0f} g")
        st.metric("🥑 Fat", f"{targets['fat']:.0f} g")
    else:
        st.warning("Please enter a name to use the app.")
        st.stop() # Stop execution if no username is provided

# --- Load Data for the selected user ---
log_df = load_nutrition_log(user_name)
today_str = date.today().strftime("%Y-%m-%d")

# Prepare today's data (handle potential uppercase columns from Snowflake)
# Ensure 'DATE' column is datetime type for comparison
if not log_df.empty:
    date_col = 'DATE' if 'DATE' in log_df.columns else 'date'
    log_df[date_col] = pd.to_datetime(log_df[date_col])
    df_today = log_df[log_df[date_col].dt.strftime('%Y-%m-%d') == today_str]
else:
    df_today = pd.DataFrame()


# --- Display "Today's Totals" Metrics ---
if not df_today.empty:
    # Handle potential uppercase column names from Snowflake
    calorie_col, protein_col, carbs_col, fat_col = 'CALORIES', 'PROTEIN', 'CARBS', 'FAT'
    totals = df_today[[calorie_col, protein_col, carbs_col, fat_col]].sum()
    st.subheader(f"Today's Totals for {user_name}")
    c = st.columns(4)
    c[0].metric("🔥 Total Calories", f"{totals[calorie_col]:.0f} kcal")
    c[1].metric("💪 Protein", f"{totals[protein_col]:.1f} g")
    c[2].metric("🍞 Carbohydrates", f"{totals[carbs_col]:.1f} g")
    c[3].metric("🥑 Fat", f"{totals[fat_col]:.1f} g")
    st.markdown("---")

# --- Main Page Layout ---
col1, col2 = st.columns([1.5, 2], gap="large")

with col1: # Food Logging & Log Display
    with st.container(border=True):
        st.header("🍛 Add Food Intake")
        with st.form("add_food_form", clear_on_submit=True):
            food_options_display = [""] + [f"{name} ({info['serving_size_g']}g)" for name, info in sorted(FOOD_DB.items())]
            selected_food_display = st.selectbox("Select Food", food_options_display)
            search_food = selected_food_display.rsplit(' (', 1)[0] if selected_food_display else None
            c1, c2 = st.columns(2)
            quantity = c1.number_input("Servings", 1, 20, 1, 1)
            meal_type = c2.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snacks"])
            if st.form_submit_button("➕ Add Food to Log", use_container_width=True, type="primary"):
                if search_food and search_food in FOOD_DB:
                    info = FOOD_DB[search_food]
                    # FIXED: Keys must match the Snowflake table's column names
                    entry = {
                        "DATE": today_str, "MEAL": meal_type, "FOOD": search_food,
                        "QUANTITY": float(quantity), "CALORIES": info["cal"] * quantity,
                        "PROTEIN": info["protein"] * quantity, "CARBS": info["carbs"] * quantity,
                        "FAT": info["fat"] * quantity
                    }
                    # FIXED: Called the correct save function with the user's name
                    save_entry_to_db(user_name, entry)
                    st.success(f"Added {quantity}x {search_food}!")
                    st.rerun()
                else:
                    st.warning("Please select a valid food item.")

    if not df_today.empty:
        with st.container(border=True):
            st.header(f"📅 Today's Log")
            # Handle potential uppercase column names
            meal_col, calorie_col, quantity_col, food_col, id_col = 'MEAL', 'CALORIES', 'QUANTITY', 'FOOD', 'ID'
            for meal in ["Breakfast", "Lunch", "Dinner", "Snacks"]:
                meal_df = df_today[df_today[meal_col] == meal]
                if not meal_df.empty:
                    with st.expander(f"**{meal}** - {meal_df[calorie_col].sum():.0f} kcal", expanded=True):
                        for _, row in meal_df.iterrows():
                            c1, c2, c3 = st.columns([4, 2, 1])
                            c1.text(f"{row[quantity_col]}x {row[food_col]}")
                            c2.text(f"{row[calorie_col]:.0f} kcal")
                            # FIXED: Use correct ID column for the button key and function call
                            if id_col in row and c3.button("🗑️", key=f"del_{row[id_col]}", help="Remove item"):
                                delete_entry_from_db(int(row[id_col]))
                                st.rerun()

with col2: # Dashboards
    with st.container(border=True):
        st.header("📊 Daily Progress Dashboard")
        if not df_today.empty:
            calorie_col, protein_col, carbs_col, fat_col = 'CALORIES', 'PROTEIN', 'CARBS', 'FAT'
            totals = df_today[[calorie_col, protein_col, carbs_col, fat_col]].sum()
            st.subheader("🔥 Calories")
            progress_ratio = totals[calorie_col] / targets['calories'] if targets['calories'] > 0 else 0
            st.progress(min(1.0, progress_ratio), text=f"{totals[calorie_col]:.0f} / {targets['calories']:.0f} kcal")
            st.markdown("---")
            st.subheader("💪 Macronutrients (grams)")
            progress_df = pd.DataFrame({'Consumed': [totals[protein_col], totals[carbs_col], totals[fat_col]], 'Target': [targets['protein'], targets['carbs'], targets['fat']]}, index=['Protein', 'Carbs', 'Fat'])
            st.bar_chart(progress_df, height=300)
        else:
            st.info("Log your first meal to see your progress dashboard!")
    
    with st.container(border=True):
        st.header("📆 Weekly Calorie Trend")
        if not log_df.empty:
            date_col, calorie_col = 'DATE', 'CALORIES'
            log_df[date_col] = pd.to_datetime(log_df[date_col])
            week_start_date = date.today() - timedelta(days=6)
            week_df = log_df[log_df[date_col].dt.date >= week_start_date]
            if len(week_df) >= 1:
                daily_summary = week_df.groupby(week_df[date_col].dt.date)[calorie_col].sum()
                all_days = pd.date_range(start=week_start_date, end=date.today(), freq='D').date
                daily_summary = daily_summary.reindex(all_days, fill_value=0)
                st.area_chart(daily_summary, height=250)
            else:
                st.info("Log meals for a couple of days to see your weekly trends.")
        else:
            st.info("Log meals to see your weekly trends.")
