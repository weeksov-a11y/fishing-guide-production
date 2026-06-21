import streamlit as st
import sys
import os
import requests
import urllib.parse
from datetime import datetime
from streamlit_js_eval import streamlit_js_eval

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

import litellm
from fishing_agent_app.crew import FishingAgentApp

st.set_page_config(page_title="PNW Mobile Fishing Crew", page_icon="🎣", layout="centered")
st.title("🎣 Mobile Fishing Advisor")

# 🧠 Dynamic Session State Management
if "scouted_lakes_dict" not in st.session_state:
    st.session_state.scouted_lakes_dict = {
        "Freshwater": ["Spanaway Lake", "American Lake", "Lake Kapowsin"],
        "Saltwater (Marine)": ["Marine Area 11 (Tacoma)", "Marine Area 13 (Olympia)", "Point Defiance Pier"]
    }
if "scout_fingerprint" not in st.session_state:
    st.session_state.scout_fingerprint = ""

# 🌊 STEP 1: SELECT ENVIRONMENT
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

# 📡 STEP 3: LOCATION SYSTEM
st.subheader("📡 Step 3: Destination Routing Mode")
routing_mode = st.radio(
    "How do you want to set your fishing location?",
    options=["🔍 Suggest Local Hotspots", "✍️ Enter a Specific Water Body By Name", "🛰️ Use My Mobile GPS Coordinates"],
    horizontal=True
)

lat, lon, location_name = None, None, ""
water_context = ""
display_summary = ""
active_water_body = ""

# Build a fingerprint to know if the user changed targets
current_fp = f"{env_choice}-{target_fish}"

if routing_mode == "🛰️ Use My Mobile GPS Coordinates":
    gps_location = streamlit_js_eval(data_element='navigator.geolocation.getCurrentPosition', want_output=True, key='current_gps_click')
    if gps_location:
        lat = gps_location['coords']['latitude']
        lon = gps_location['coords']['longitude']
        location_name = f"GPS: ({lat:.4f}, {lon:.4f})"
        active_water_body = "Current GPS Location"
        water_context = f"the exact water body coordinates at GPS location {lat:.4f}, {lon:.4f}."
        display_summary = "🎯 Locked to Live Satellite GPS Location"
        st.success(f"🔒 Mobile Satellite Link Active")
    else:
        st.info("Awaiting satellite lock... Ensure browser permissions are enabled.")
        lat, lon, location_name = 47.2529, -122.4443, "Tacoma, WA"
        active_water_body = "Tacoma Local Waters"
        water_context = "Local bodies of water near Tacoma, WA"
        display_summary = "📍 Region: Tacoma, WA (GPS Awaiting Lock)"

elif routing_mode == "✍️ Enter a Specific Water Body By Name":
    user_water = st.text_input("📝 Type the name of the lake, river, or Marine Area:", value="American Lake")
    manual_city = st.text_input("📍 City/State closest to this water (for weather tracking):", value="Tacoma, WA")
    
    active_water_body = user_water
    water_context = f"""the specific single body of water named {user_water}. You MUST completely ignore alternative recommendations and list rules/gear exclusively for {user_water}."""
    display_summary = f"🗺️ Target Water Body: **{user_water}**"
    location_name = manual_city if manual_city.strip() else "Tacoma, WA"

else: # 🔍 Suggest Local Hotspots Mode
    manual_city = st.text_input("📍 Enter your search City, State:", value="Tacoma, WA")
    location_name = manual_city if manual_city.strip() else "Tacoma, WA"
    
    st.markdown("### 🛰️ Fast AI Scout Engine")
    st.caption("Tap the button below to have Gemini dynamically scout your immediate area for top choices matching your target fish.")
    
    if st.button("🔍 Scout & Update Local Choices", use_container_width=True, type="secondary"):
        with st.spinner("🤖 Mapping local hotspots..."):
            scout_inputs = {
                'target_fish': target_fish,
                'environment': f"Provide a simple comma-separated list of exactly 3 real, specific local named {env_choice} fishing spots/lakes/marine zones near {location_name} known for holding {target_fish}.",
                'current_state': "PNW Region",
                'water_temp': "70°F", 'barometric_pressure': "Stable", 'cloud_cover': "Clear", 'wind_speed': "5 mph", 'water_clarity': "Clear"
            }
            try:
                # Direct mini-execution to extract the raw text choices seamlessly
                scout_res = FishingAgentApp().crew().kickoff(inputs=scout_inputs)
                raw_text = str(scout_res)
                
                # Dynamic parsing fallback logic to safely isolate names
                cleaned_list = []
                for line in raw_text.split("\n"):
                    if any(char.isalpha() for char in line) and "Plan" not in line and "Guardrails" not in line:
                        item = line.replace("*","").replace("-","").replace("1.","").replace("2.","").replace("3.","").strip()
                        if len(item) > 3 and len(item) < 40:
                            cleaned_list.append(item)
                
                if len(cleaned_list) >= 2:
                    st.session_state.scouted_lakes_dict[env_choice] = cleaned_list[:3]
                    st.success("🎯 Dropdown choices updated below!")
            except Exception as se:
                st.warning("Using regional baseline index options.")

    # Render choices dynamically based on the update state
    dropdown_options = st.session_state.scouted_lakes_dict.get(env_choice, ["American Lake"])
    selected_suggested = st.selectbox("🎯 Tap to select one of your local suggested hotspots:", options=dropdown_options)
    
    active_water_body = selected_suggested
    water_context = f"the specific body of water named {selected_suggested}. Provide information, rules, and gear layouts exclusively for {selected_suggested}."
    display_summary = f"🔍 Scouting Hotspot Choice: **{selected_suggested}**"

# Geocoding resolution for weather processing
if location_name and not lat:
    try:
        clean_city = location_name.replace(".", "").split(",")[0].strip()
        encoded_city = urllib.parse.quote(clean_city)
        headers = {'User-Agent': 'PNWFishingAdvisorApp/1.0'}
        osm_url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&countrycodes=us&format=json&addressdetails=1&limit=1"
        osm_res = requests.get(osm_url, headers=headers).json()
        if osm_res and len(osm_res) > 0:
            lat, lon = float(osm_res[0]["lat"]), float(osm_res[0]["lon"])
        else:
            lat, lon = 47.2529, -122.4443
    except Exception:
        lat, lon = 47.2529, -122.4443

detected_state = "Oregon" if ("Oregon" in location_name or "OR" in location_name) else "Washington"
agency_name = "ODFW" if detected_state == "Oregon" else "WDFW"

# 🚀 RUN ANALYSIS BUTTON
st.subheader("⚡ Step 4: Run Analysis")
execute_crew = st.button("🚀 Generate Tactical Strategy Plan", type="primary", use_container_width=True)

# 📋 SHOW LIVE STATS BELOW BUTTON
if lat and lon:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,cloud_cover,surface_pressure,wind_speed_10m&hourly=surface_pressure,precipitation,temperature_2m&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
        weather = requests.get(url).json()
        current = weather['current']
        
        current_pressure = current['surface_pressure']
        past_pressure = weather['hourly']['surface_pressure'][-3] 
        diff = current_pressure - past_pressure
        trend = "Rising rapidly" if diff > 0.05 else "Rising slowly" if diff > 0.01 else "Falling rapidly" if diff < -0.05 else "Falling slowly" if diff < -0.01 else "Stable"
        cloud_word = "Clear/Sunny" if current['cloud_cover'] < 20 else "Partially Cloudy" if current['cloud_cover'] < 60 else "Overcast"

        # 🌊 Water Clarity Calculation Engine
        recent_rain = sum(weather['hourly'].get('precipitation', [0.0])[-12:])
        clarity_estimate = "Stained / Muddy Runoff" if (recent_rain > 0.50 or current['wind_speed_10m'] > 15) else "Slightly Stained" if recent_rain > 0.15 else "Clear"

        # 🌡️ Mathematical Water Surface Temperature Estimation Model
        past_3_days_air_temps = weather['hourly']['temperature_2m'][:72]
        mean_air_temp = sum(past_3_days_air_temps) / len(past_3_days_air_temps) if past_3_days_air_temps else current['temperature_2m']
        estimated_water_temp = (0.7 * mean_air_temp) + (0.3 * current['temperature_2m'])

        with st.expander(f"🌦️ Live Environmental Metrics & Maps for {active_water_body}", expanded=True):
            st.caption(f"🗺️ Jurisdiction: {detected_state} ({agency_name})")
            st.markdown(display_summary)
            
            # 🗺️ DYNAMIC DEPTH MAP AND RESOURCE BROKER LINKS
            clean_lake_url = urllib.parse.quote(active_water_body.strip())
            if detected_state == "Washington":
                map_link = f"https://wdfw.wa.gov/fishing/locations/lowland-lakes/{clean_lake_url.lower().replace('%20', '-')}"
            else:
                map_link = f"https://myodfw.com/fishing/locations?q={clean_lake_url}"
                
            st.link_button("🗺️ Open Official State Depth Map & Fish Stocking Records", map_link, use_container_width=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(label="Estimated Surface Water Temp", value=f"{estimated_water_temp:.1f}°F")
                st.metric(label="Barometric Trend", value=trend, delta=f"{diff:.2f} hPa")
            with col2:
                st.metric(label="Calculated Water Clarity", value=clarity_estimate)
                st.metric(label="Wind Velocity", value=f"{current['wind_speed_10m']} mph")

        # 🤖 ENGINE EXECUTION INTERFACE
        if execute_crew:
            inputs = {
                'target_fish': target_fish,
                'environment': water_context,  
                'current_state': detected_state,
                'water_temp': f"{estimated_water_temp:.1f}°F",  
                'barometric_pressure': trend, 
                'cloud_cover': cloud_word,
                'wind_speed': f"{current['wind_speed_10m']} mph",
                'water_clarity': clarity_estimate
            }
            with st.spinner("🤖 Consulting AI Specialists..."):
                result = FishingAgentApp().crew().kickoff(inputs=inputs)
                raw_output = result.raw if hasattr(result, 'raw') else str(result)
                st.success("🎯 Strategy Formulated!")
                
                if "### 🎣 Tactical Strategy Plan" in raw_output:
                    parts = raw_output.split("### 🎣 Tactical Strategy Plan")
                    compliance_section = parts[0].replace("### 🚨 Regional Legal Compliance Guardrails & Location Suggestions", "").strip()
                    tactical_section = parts[1].strip()
                    
                    with st.expander(f"🚨 {agency_name} Legal Compliance Guardrails & Location Data", expanded=True):
                        st.markdown(compliance_section)
                    with st.expander("🎣 Tactical Strategy Plan", expanded=True):
                        st.markdown(tactical_section)
                else:
                    with st.expander("📋 View Generated Strategy Details", expanded=True):
                        st.markdown(raw_output)

    except Exception as err:
        st.error(f"Failed to compile weather data stream: {err}")
