import streamlit as st
import sys
import os
import requests
import urllib.parse
from datetime import datetime
from streamlit_js_eval import streamlit_js_eval

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Securely fetch the key from Streamlit's private backend cloud settings
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

import litellm
original_completion = litellm.completion
def clean_groq_completion(*args, **kwargs):
    if "messages" in kwargs:
        for msg in kwargs["messages"]:
            if isinstance(msg, dict):
                msg.pop("cache_breakpoint", None)
    return original_completion(*args, **kwargs)
litellm.completion = clean_groq_completion

from fishing_agent_app.crew import FishingAgentApp

st.set_page_config(page_title="PNW Mobile Fishing Crew", page_icon="🎣", layout="centered")
st.title("🎣 Mobile Fishing Advisor")

# 🌊 STEP 1: CHOOSE ENVIRONMENT FIRST
st.subheader("🌊 Step 1: Select Your Environment")
env_choice = st.segmented_control(
    "Where are you fishing today?",
    options=["Freshwater", "Saltwater (Marine)"],
    default="Freshwater"
)

# 🐟 STEP 2: CHOOSE TARGET SPECIES
st.subheader("🐟 Step 2: Choose Your Target Species")

if env_choice == "Freshwater":
    species_options = ["Crappie", "Largemouth Bass", "Smallmouth Bass", "Rainbow Trout", "Perch", "Catfish"]
    default_species = "Crappie"
else:
    species_options = ["Resident Coho Salmon", "Chinook Salmon", "Puget Sound Surfperch", "Flounder", "Spiny Dogfish", "Dabs", "Sole"]
    default_species = "Resident Coho Salmon"

target_fish = st.pills("Tap a species:", options=species_options, default=default_species)
st.info(f"🎯 Strategy Target: **{target_fish}** ({env_choice})")

# 📡 STEP 3: LOCATION SYSTEM
st.subheader("📡 Step 3: Destination Routing Mode")

routing_mode = st.radio(
    "How do you want to set your fishing location?",
    options=["🔍 Suggest Local Hotspots", "✍️ Enter a Specific Water Body By Name", "🛰️ Use My Mobile GPS Coordinates"],
    horizontal=True
)

lat, lon, location_name = None, None, ""
water_context = ""
display_summary = "" # 💡 Added a clean summary string for the user layout

if routing_mode == "🛰️ Use My Mobile GPS Coordinates":
    gps_location = streamlit_js_eval(data_element='navigator.geolocation.getCurrentPosition', want_output=True, key='current_gps_click')
    if gps_location:
        lat = gps_location['coords']['latitude']
        lon = gps_location['coords']['longitude']
        location_name = f"GPS: ({lat:.4f}, {lon:.4f})"
        water_context = f"the exact water body coordinates at GPS location {lat:.4f}, {lon:.4f}"
        display_summary = "🎯 Locked to Live Satellite GPS Location"
        st.success(f"🔒 Mobile Satellite Link Active: {location_name}")
    else:
        st.info("Awaiting satellite lock... Ensure browser permissions are enabled.")
        lat, lon, location_name = 47.2529, -122.4443, "Tacoma, WA"
        water_context = f"Local bodies of water near Tacoma, WA"
        display_summary = "📍 Region: Tacoma, WA (GPS Awaiting Lock)"

elif routing_mode == "✍️ Enter a Specific Water Body By Name":
    user_water = st.text_input("📝 Type the name of the lake, river, or Marine Area:", value="American Lake")
    manual_city = st.text_input("📍 City/State closest to this water (for weather tracking):", value="Tacoma, WA")
    
    # Keep the strict instructions hidden here in the backend context variable...
    water_context = f"the specific body of water named '{user_water}'. Do NOT suggest any other lakes; only provide specific regulations, hot spots, and rigging methods exclusively for '{user_water}'"
    # ...but make a super clean sentence for the app UI display!
    display_summary = f"🗺️ Target Water Body: **{user_water}**"
    location_name = manual_city if manual_city.strip() else "Tacoma, WA"

else: # 🔍 Suggest Local Hotspots Mode
    manual_city = st.text_input("📍 Enter your current City, State:", value="Tacoma, WA")
    if not manual_city.strip():
        manual_city = "Tacoma, WA"
    location_name = manual_city
    water_context = f"Top highly-rated local {env_choice} spots near {location_name} specifically known for holding {target_fish}"
    display_summary = f"🔍 Auto-Scouting Local {env_choice} Hotspots near {location_name}"

# Geocoding resolution for weather processing
if location_name and not lat:
    try:
        clean_city = location_name.replace(".", "").split(",")[0].strip()
        encoded_city = urllib.parse.quote(clean_city)
        headers = {'User-Agent': 'PNWFishingAdvisorApp/1.0'}
        osm_url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&countrycodes=us&format=json&addressdetails=1&limit=1"
        osm_res = requests.get(osm_url, headers=headers).json()
        
        if osm_res and len(osm_res) > 0:
            lat = float(osm_res[0]["lat"])
            lon = float(osm_res[0]["lon"])
            address = osm_res[0].get("address", {})
            city_display = address.get("city", address.get("town", address.get("village", clean_city)))
            state_display = address.get("state", "Washington")
            location_name = f"{city_display}, {state_display}"
        else:
            lat, lon, location_name = 47.2529, -122.4443, "Tacoma, Washington"
    except Exception as ge:
        lat, lon, location_name = 47.2529, -122.4443, "Tacoma, Washington"

# 🔀 SMART JURISDICTION DETECTION
if "Oregon" in location_name or "OR" in location_name:
    detected_state = "Oregon"
    agency_name = "ODFW"
else:
    detected_state = "Washington"
    agency_name = "WDFW"

# 🚀 STEP 4: RUN ANALYSIS BUTTON
st.subheader("⚡ Step 4: Run Analysis")
execute_crew = st.button("🚀 Generate Tactical Strategy Plan", type="primary", use_container_width=True)

# 📋 SHOW LIVE STATS BELOW BUTTON
if lat and lon:
    @st.cache_data(ttl=900)
    def get_weather_data(latitude, longitude):
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m,cloud_cover,surface_pressure,wind_speed_10m&hourly=surface_pressure&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
        return requests.get(url).json()

    try:
        weather = get_weather_data(lat, lon)
        current = weather['current']
        
        current_pressure = current['surface_pressure']
        past_pressure = weather['hourly']['surface_pressure'][-3] 
        diff = current_pressure - past_pressure
        
        trend = "Rising rapidly" if diff > 0.05 else "Rising slowly" if diff > 0.01 else "Falling rapidly" if diff < -0.05 else "Falling slowly" if diff < -0.01 else "Stable"
        cc = current['cloud_cover']
        cloud_word = "Clear/Sunny" if cc < 20 else "Partially Cloudy" if cc < 60 else "Overcast"

        with st.expander(f"🌦️ View Live Environmental Metrics for {location_name}", expanded=False):
            st.caption(f"🗺️ Jurisdiction Detected: {detected_state} ({agency_name})")
            st.markdown(display_summary) # 💡 Replaced the ugly routing prompt with our clean display text!
            col1, col2 = st.columns(2)
            with col1:
                st.metric(label="Air Temp Estimation", value=f"{current['temperature_2m']}°F")
                st.metric(label="Barometric Trend", value=trend, delta=f"{diff:.2f} hPa")
            with col2:
                st.metric(label="Cloud Cover", value=cloud_word)
                st.metric(label="Wind Velocity", value=f"{current['wind_speed_10m']} mph")

        # 🤖 ENGINE EXECUTION INTERFACE
        if execute_crew:
            inputs = {
                'target_fish': target_fish,
                'environment': water_context,  
                'current_state': detected_state,
                'water_temp': f"{current['temperature_2m']}°F",  
                'barometric_pressure': trend, 
                'cloud_cover': cloud_word,
                'wind_speed': f"{current['wind_speed_10m']} mph",
                'water_clarity': "Dynamic check based on system rules"
            }
            
            with st.spinner("🤖 Consulting AI Specialists..."):
                result = FishingAgentApp().crew().kickoff(inputs=inputs)
                raw_output = result.raw if hasattr(result, 'raw') else str(result)
                st.success("🎯 Strategy Formulated!")
                
                if "### 🎣 Tactical Strategy Plan" in raw_output:
                    parts = raw_output.split("### 🎣 Tactical Strategy Plan")
                    compliance_section = parts[0].replace("### 🚨 Regional Legal Compliance Guardrails & Location Suggestions", "").strip()
                    tactical_section = parts[1].strip()
                    
                    with st.expander(f"🚨 {agency_name} Legal Compliance Guardrails & Locations", expanded=True):
                        st.markdown(compliance_section)
                        
                    with st.expander("🎣 Tactical Strategy Plan", expanded=True):
                        st.markdown(tactical_section)
                else:
                    with st.expander("📋 View Generated Strategy Details", expanded=True):
                        st.markdown(raw_output)

    except Exception as err:
        st.error(f"Failed to compile weather data stream: {err}")
