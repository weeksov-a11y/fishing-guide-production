import streamlit as st
import sys
import os
import requests
import urllib.parse
from datetime import datetime
from streamlit_js_eval import streamlit_js_eval

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Securely fetch the key from Streamlit's private backend cloud settings
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
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

# 🐟 VISUAL CARD SELECTION CONFIGURATION
st.subheader("🐟 Choose Your Target Species")

target_fish = st.pills(
    "Tap a species to select your target:",
    options=[
        "Crappie", 
        "Largemouth Bass", 
        "Smallmouth Bass", 
        "Rainbow Trout", 
        "Perch",
        "Resident Coho Salmon", 
        "Chinook Salmon", 
        "Puget Sound Surfperch", 
        "Flounder"
    ],
    default="Crappie"
)

st.info(f"🎯 Currently targeting: **{target_fish}**")

is_saltwater = target_fish in ["Resident Coho Salmon", "Chinook Salmon", "Puget Sound Surfperch", "Flounder"]
environment_type = "Marine (Saltwater)" if is_saltwater else "Freshwater"

# 📡 LOCATION CONFIGURATION SYSTEM
st.subheader("📡 Location Configuration")

if "use_gps" not in st.session_state:
    st.session_state.use_gps = False

if st.button("📍 Tap to Share Mobile GPS Location", type="secondary", use_container_width=True):
    st.session_state.use_gps = True

lat, lon, location_name = None, None, ""

gps_location = None
if st.session_state.use_gps:
    gps_location = streamlit_js_eval(data_element='navigator.geolocation.getCurrentPosition', want_output=True, key='current_gps_click')

if gps_location:
    lat = gps_location['coords']['latitude']
    lon = gps_location['coords']['longitude']
    location_name = f"GPS Coordinates ({lat:.4f}, {lon:.4f})"
    st.success(f"🔒 Mobile Satellite Link Active: {lat:.4f}, {lon:.4f}")
else:
    manual_city = st.text_input("📍 Location Fallback (Enter City, State if GPS is off)", value="Tacoma, WA")
    
    if not manual_city.strip():
        manual_city = "Tacoma, WA"
        
    # 🧼 FIXED CLEANING: Grab everything before the comma completely to protect multi-word cities!
    clean_city = manual_city.replace(".", "").split(",")[0].strip()
    encoded_city = urllib.parse.quote(clean_city)
    
    try:
        # Pull up to 20 results so we have plenty of room to hunt down the exact state match
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_city}&count=20&language=en&format=json"
        geo_res = requests.get(geo_url).json()
        
        if "results" in geo_res and len(geo_res["results"]) > 0:
            us_match = None
            
            # 🔍 SMART SCANNER: Look for a match in the US, prioritizing the specific state typed
            for res in geo_res["results"]:
                if res.get("country_code") == "US":
                    # Check if the user hinted at Oregon
                    if "OR" in manual_city.upper() or "OREGON" in manual_city.upper():
                        if res.get("admin1") == "Oregon":
                            us_match = res
                            break
                    # Check if the user hinted at Washington
                    elif "WA" in manual_city.upper() or "WASHINGTON" in manual_city.upper():
                        if res.get("admin1") == "Washington":
                            us_match = res
                            break
                    us_match = res
            
            final_res = us_match if us_match else geo_res["results"][0]
            
            lat = final_res["latitude"]
            lon = final_res["longitude"]
            location_name = f"{final_res['name']}, {final_res.get('admin1', '')}"
            st.success(f"🗺️ Set to location: {location_name} ({lat:.4f}, {lon:.4f})")
        else:
            st.warning(f"Could not resolve details for '{manual_city}'. Falling back to default baseline.")
            lat, lon, location_name = 47.2529, -122.4443, "Tacoma, WA"
    except Exception as ge:
        st.error(f"Geocoding stream failed: {ge}")
        lat, lon, location_name = 47.2529, -122.4443, "Tacoma, WA"

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
        
        if diff > 0.05: trend = "Rising rapidly"
        elif diff > 0.01: trend = "Rising slowly"
        elif diff < -0.05: trend = "Falling rapidly"
        elif diff < -0.01: trend = "Falling slowly"
        else: trend = "Stable"

        cc = current['cloud_cover']
        if cc < 20: cloud_word = "Clear/Sunny"
        elif cc < 60: cloud_word = "Partially Cloudy"
        else: cloud_word = "Overcast"

        # 🔀 DYNAMIC STATE DETECTION LOGIC
        if "OR" in location_name or "Oregon" in location_name:
            detected_state = "Oregon"
            agency_name = "ODFW (Oregon Department of Fish and Wildlife)"
        else:
            detected_state = "Washington"
            agency_name = "WDFW (Washington Department of Fish and Wildlife)"

        with st.expander(f"🌦️ View Live Environmental Metrics for {location_name}", expanded=True):
            st.caption(f"🗺️ Jurisdiction Detected: {detected_state} ({agency_name})")
            col1, col2 = st.columns(2)
            with col1:
                st.metric(label="Air Temp Estimation", value=f"{current['temperature_2m']}°F")
                st.metric(label="Barometric Trend", value=trend, delta=f"{diff:.2f} hPa")
            with col2:
                st.metric(label="Cloud Cover", value=cloud_word)
                st.metric(label="Wind Velocity", value=f"{current['wind_speed_10m']} mph")

        if st.button("Generate Tactical Strategy Plan", type="primary"):
            inputs = {
                'target_fish': target_fish,
                'environment': environment_type,  
                'current_state': detected_state,
                'water_temp': f"{current['temperature_2m']}°F",  
                'barometric_pressure': trend, 
                'cloud_cover': cloud_word,
                'wind_speed': f"{current['wind_speed_10m']} mph",
                'water_clarity': "Clear marine water" if is_saltwater else "Slightly stained"
            }
            
            with st.spinner("🤖 Consulting AI Specialists..."):
                result = FishingAgentApp().crew().kickoff(inputs=inputs)
                raw_output = result.raw if hasattr(result, 'raw') else str(result)
                st.success("🎯 Strategy Formulated!")
                
                if "### 🎣 Tactical Strategy Plan" in raw_output:
                    parts = raw_output.split("### 🎣 Tactical Strategy Plan")
                    compliance_section = parts[0].replace("### 🚨 Regional Legal Compliance Guardrails & Environment", "").strip()
                    tactical_section = parts[1].strip()
                    
                    with st.expander(f"🚨 {agency_name} Legal Compliance Guardrails", expanded=False):
                        st.markdown(compliance_section)
                        
                    with st.expander("🎣 Tactical Strategy Plan", expanded=True):
                        st.markdown(tactical_section)
                else:
                    with st.expander("📋 View Generated Strategy Details", expanded=True):
                        st.markdown(raw_output)

    except Exception as err:
        st.error(f"Failed to compile weather data stream: {err}")
