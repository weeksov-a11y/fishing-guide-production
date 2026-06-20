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

gps_location = streamlit_js_eval(data_element='navigator.geolocation.getCurrentPosition', want_output=True, key='current_gps')

lat, lon, location_name = None, None, ""

if gps_location:
    lat = gps_location['coords']['latitude']
    lon = gps_location['coords']['longitude']
    location_name = f"GPS Coordinates ({lat:.4f}, {lon:.4f})"
    st.success(f"🔒 Satellite GPS Connection Active: {lat:.4f}, {lon:.4f}")
else:
    st.info("Searching for browser satellite stream... (Laptops often block this)")
    manual_city = st.text_input("📍 Laptop Fallback: Enter your current location manually", value="Tacoma, WA")
    
    if manual_city:
        clean_city = manual_city.split(",")[0].strip()
        encoded_city = urllib.parse.quote(clean_city)
        
        try:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_city}&count=1&language=en&format=json"
            geo_res = requests.get(geo_url).json()
            
            if "results" in geo_res and len(geo_res["results"]) > 0:
                lat = geo_res["results"][0]["latitude"]
                lon = geo_res["results"][0]["longitude"]
                location_name = f"{geo_res['results'][0]['name']}, {geo_res['results'][0].get('admin1', '')}"
                st.success(f"🗺️ Locked to manual location: {location_name} ({lat:.4f}, {lon:.4f})")
            else:
                st.warning(f"Could not resolve query details for '{clean_city}'. Try entering just the city name.")
        except Exception as ge:
            st.error(f"Geocoding stream failed: {ge}")

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
                
                # Split and output into clean collapsible views matching your task format
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
