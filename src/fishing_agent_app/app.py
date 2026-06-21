import streamlit as st
import sys
import os
import requests
import urllib.parse
from datetime import datetime
from streamlit_js_eval import streamlit_js_eval

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# 🔑 Load the Groq Key from Secrets Vault
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

from crewai import LLM
from fishing_agent_app.crew import FishingAgentApp

# 🏎️ Route the AI Scouting Engine through Groq's ultra-fast free tier
gemini_scout_model = LLM(
    model="groq/llama-3.1-8b-instant",
    temperature=0.3
)

logo_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
st.set_page_config(page_title="PNW Mobile Fishing Crew", page_icon=logo_path, layout="centered")
st.title("🎣 Mobile Fishing Advisor")

app_base_url = "https://fishing-guide.streamlit.app"
st.logo(logo_path) 

st.html(
    """
    <script>
        console.log("Mobile gateway initialized with Groq optimization.");
    </script>
    """
)

if "scouted_lakes_dict" not in st.session_state:
    st.session_state.scouted_lakes_dict = {
        "Freshwater": ["Spanaway Lake", "American Lake", "Lake Kapowsin"],
        "Saltwater (Marine)": ["Marine Area 11 (Tacoma)", "Marine Area 13 (Olympia)", "Point Defiance Pier"]
    }

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

if routing_mode == "🛰️ Use My Mobile GPS Coordinates":
    st.info("📡 Requesting satellite lock... If your browser blocks this, please use 'Suggest Local Hotspots' or enter location by name.")
    gps_location = streamlit_js_eval(data_element='navigator.geolocation.getCurrentPosition', want_output=True, key='current_gps_click_v3')
    
    if gps_location:
        lat = float(gps_location['coords']['latitude'])
        lon = float(gps_location['coords']['longitude'])
        location_name = f"GPS: ({lat:.4f}, {lon:.4f})"
        active_water_body = "Current GPS Location"
        water_context = f"the exact water body coordinates at GPS location {lat:.4f}, {lon:.4f}."
        display_summary = f"🎯 Locked to Live Satellite GPS: {lat:.4f}, {lon:.4f}"
        st.success(f"🔒 Mobile Satellite Link Active")
    else:
        st.warning("⚠️ Mobile GPS access was denied or blocked by browser security permissions.")
        fallback_city = st.text_input("📍 GPS Backup Mode: Enter your current City, State manually instead:", value="Portland, OR")
        location_name = fallback_city

elif routing_mode == "✍️ Enter a Specific Water Body By Name":
    user_water = st.text_input("📝 Type the name of the lake, river, or Marine Area:", value="Lake Kapowsin")
    manual_city = st.text_input("📍 City/State closest to this water (for weather tracking):", value="Tacoma, WA")
    location_name = manual_city
    active_water_body = user_water.strip()

else: # 🔍 Suggest Local Hotspots Mode
    manual_city = st.text_input("📍 Enter your search City, State:", value="Tacoma, WA")
    location_name = manual_city
    
    st.markdown("### 🛰️ Fast AI Scout Engine")
    
    if st.button("🔍 Scout & Update Local Choices", use_container_width=True, type="secondary"):
        with st.spinner(f"🤖 Mapping local hotspots near {location_name}..."):
            # Cleaned prompt style optimized for open-source Llama parsing
            prompt = f"Provide exactly 3 real, specific local named {env_choice} fishing spots, lakes, or marine zones located near {location_name} that are highly-rated for catching {target_fish}. Output ONLY the 3 names separated by newlines, with no extra text, explanations, or numbers."
            try:
                scout_res = gemini_scout_model.call(messages=[{"role": "user", "content": prompt}])
                raw_text = str(scout_res).strip()
                cleaned_list = [line.replace("*","").replace("-","").strip() for line in raw_text.split("\n") if line.strip()]
                
                if len(cleaned_list) >= 1:
                    st.session_state.scouted_lakes_dict[env_choice] = cleaned_list[:3]
                    st.success("🎯 Hotspots updated!")
                    st.rerun() 
                else:
                    st.error("🤖 AI returned an empty list. Try clicking again.")
            except Exception as e:
                st.error(f"⚠️ Scouting engine timeout: {e}")

    if "oregon" in location_name.lower() or "or" in location_name.lower():
        default_spots = ["Hagg Lake", "Blue Lake", "Willamette River Sector"] if env_choice == "Freshwater" else ["Marine Area 1 (Astoria)", "Columbia River Estuary", "Newport Pier"]
    else:
        default_spots = ["Spanaway Lake", "American Lake", "Lake Kapowsin"] if env_choice == "Freshwater" else ["Marine Area 11 (Tacoma)", "Marine Area 13 (Olympia)", "Point Defiance Pier"]

    dropdown_options = st.session_state.scouted_lakes_dict.get(env_choice, default_spots)
    selected_suggested = st.selectbox("🎯 Tap to select one of your local suggested hotspots:", options=dropdown_options)
    active_water_body = selected_suggested

# 🧭 CORE GEOLOCATION RESOLUTION ENGINE
if location_name and not lat:
    try:
        encoded_city = urllib.parse.quote(location_name.strip())
        headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
        osm_url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&countrycodes=us&format=json&addressdetails=1&limit=1"
        osm_res = requests.get(osm_url, headers=headers).json()
        if osm_res and len(osm_res) > 0:
            lat = float(osm_res[0]["lat"])
            lon = float(osm_res[0]["lon"])
            if routing_mode != "🛰️ Use My Mobile GPS Coordinates":
                display_summary = f"🗺️ Target Water: **{active_water_body}** ({location_name})"
                water_context = f"the specific body of water named {active_water_body} near {location_name}."
        else:
            lat, lon = 47.2529, -122.4443 
    except Exception:
        lat, lon = 47.2529, -122.4443

# 🌲 JURISDICTION ROUTER
if lat is not None:
    if "oregon" in location_name.lower() or "or" in location_name.lower() or lat < 46.25:
        detected_state = "Oregon"
        agency_name = "ODFW"
    else:
        detected_state = "Washington"
        agency_name = "WDFW"
else:
    detected_state = "Washington"
    agency_name = "WDFW"

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

        recent_rain = sum(weather['hourly'].get('precipitation', [0.0])[-12:])
        clarity_estimate = "Stained / Muddy Runoff" if (recent_rain > 0.50 or current['wind_speed_10m'] > 15) else "Slightly Stained / Milky" if recent_rain > 0.15 else "Clear Water Visibility"

        past_3_days_air_temps = weather['hourly']['temperature_2m'][:72]
        mean_air_temp = sum(past_3_days_air_temps) / len(past_3_days_air_temps) if past_3_days_air_temps else current['temperature_2m']
        estimated_water_temp = (0.7 * mean_air_temp) + (0.3 * current['temperature_2m'])

        live_gauge_data = "Station data unavailable for static land locations."
        
        if env_choice == "Freshwater":
            west_lon, south_lat, east_lon, north_lat = lon - 0.45, lat - 0.45, lon + 0.45, lat + 0.45
            usgs_url = f"https://waterservices.usgs.gov/nwis/iv/?format=json&bBox={west_lon:.4f},{south_lat:.4f},{east_lon:.4f},{north_lat:.4f}&parameterCd=00060,00065&siteStatus=active"
            try:
                usgs_res = requests.get(usgs_url, timeout=6).json()
                time_series = usgs_res.get('value', {}).get('timeSeries', [])
                if time_series and len(time_series) > 0:
                    ts_entry = time_series[0]
                    site_name = ts_entry.get('sourceInfo', {}).get('siteName', 'Unknown Stream')
                    values_block = ts_entry.get('values', [])
                    if values_block and len(values_block) > 0 and len(values_block[0].get('value', [])) > 0:
                        val = values_block[0]['value'][0]['value']
                        p_code = ts_entry.get('variable', {}).get('variableCode', [{}])[0].get('value', '')
                        unit = "CFS (Flow Volume)" if "00060" in p_code else "ft (Water Height)"
                        live_gauge_data = f"🌊 Nearest Active Field Gauge: {site_name} | Current State: {val} {unit}"
                else:
                    live_gauge_data = "⚠️ Local Hydrology: No active river flow gauges found in this lake zone."
            except Exception:
                live_gauge_data = "⚠️ Local Hydrology: Stream telemetry loop bypassed due to network timeout."
        else:
            noaa_url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=latest&range=24&product=water_level&datum=MLLW&units=english&time_zone=lst_ldt&format=json&application=PNWFishingCrew&station=9446484"
            try:
                noaa_res = requests.get(noaa_url, timeout=5).json()
                if "data" in noaa_res and len(noaa_res["data"]) > 0:
                    latest_reading = noaa_res["data"][-1]
                    tide_height = latest_reading["v"]
                    tide_time = latest_reading["t"]
                    live_gauge_data = f"⚓ NOAA Marine Station 9446484 | Current Tide Level: {tide_height} ft above MLLW at {tide_time}"
            except Exception:
                live_gauge_data = "⚓ NOAA Tides: Marine telemetry link timed out."

        with st.expander(f"🌦️ Live Environmental Metrics & Maps for {active_water_body}", expanded=True):
            st.caption(f"🗺️ Jurisdiction: {detected_state} ({agency_name})")
            st.markdown(display_summary)
            
            cleaned_name_str = active_water_body.strip().lower()
            if "lake" in cleaned_name_str:
                cleaned_name_str = cleaned_name_str.replace("lake", "").strip()
                url_lake_segment = f"lake-{cleaned_name_str}"
            else:
                url_lake_segment = cleaned_name_str
                
            url_lake_segment = url_lake_segment.replace(" ", "-").replace("'", "")
            encoded_clean_segment = urllib.parse.quote(url_lake_segment)
            
            if detected_state == "Washington":
                map_link = f"https://wdfw.wa.gov/fishing/locations/lowland-lakes/{encoded_clean_segment}"
            else:
                map_link = f"https://myodfw.com/fishing/locations?q={urllib.parse.quote(active_water_body.strip())}"
                
            st.link_button("🗺️ Open Official State Depth Map & Fish Stocking Records", map_link, use_container_width=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(label="Est. Water Temp", value=f"{estimated_water_temp:.1f}°F")
            with col2:
                st.metric(label="Wind Velocity", value=f"{current['wind_speed_10m']} mph")
                
            st.markdown("---")
            st.markdown(f"📡 **Live Hydrological Telemetry:** {live_gauge_data}")
            st.markdown(f"🌊 **Calculated Water Clarity:** {clarity_estimate}")
            st.markdown(f"📈 **Barometric Pressure Trend:** {trend} ({diff:+.2f} hPa)")
            st.markdown(f"☁️ **Sky Conditions:** {cloud_word}")

        if execute_crew:
            inputs = {
                'target_fish': target_fish,
                'environment': water_context,  
                'current_state': detected_state,
                'water_temp': f"{estimated_water_temp:.1f}°F",  
                'barometric_pressure': trend, 
                'cloud_cover': cloud_word,
                'wind_speed': f"{current['wind_speed_10m']} mph",
                'water_clarity': f"{clarity_estimate}. Additional live field gauge data shows: {live_gauge_data}"
            }
            with st.spinner("🤖 Consulting Fast AI Specialists via Groq..."):
                # ⚙️ NOTE: Ensure your underlying crew.py definition also hooks into os.environ.get("GROQ_API_KEY") 
                # or uses the default environment model if you configured it there!
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
