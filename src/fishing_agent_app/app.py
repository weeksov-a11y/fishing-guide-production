import streamlit as st
import sys
import os
import requests
import urllib.parse
import re
from datetime import datetime

# 🛰️ Native Universal Hardware Geolocation Link
from streamlit_geolocation import streamlit_geolocation

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
    temperature=0.1
)

logo_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
st.set_page_config(page_title="PNW Mobile Fishing Crew", page_icon=logo_path, layout="centered")
st.title("🎣 Mobile Fishing Advisor")

app_base_url = "https://fishing-guide.streamlit.app"
st.logo(logo_path) 

if "scouted_lakes_dict" not in st.session_state:
    st.session_state.scouted_lakes_dict = {
        "Freshwater": ["Spanaway Lake", "American Lake", "Lake Kapowsin"],
        "Saltwater (Marine)": ["Marine Area 11 (Tacoma)", "Marine Area 13 (Olympia)", "Point Defiance Pier"]
    }

# =====================================================================
# 🛰️ STEP 1: LOCATION-FIRST ROUTING MODULE (THE ANCHOR)
# =====================================================================
st.subheader("📡 Step 1: Destination Routing Mode")
routing_mode = st.radio(
    "How do you want to set your fishing location?",
    options=["🛰️ Use My Live GPS Coordinates", "✍️ Enter a Specific Water Body By Name", "🔍 Suggest Local Hotspots"],
    horizontal=True
)

lat, lon, location_name = None, None, ""
water_context = ""
display_summary = ""
active_water_body = ""

if routing_mode == "🛰️ Use My Live GPS Coordinates":
    st.markdown("### 🛰️ Mobile Satellite Link")
    st.info("Tap the button below to broadcast your phone's live coordinate data stream.")
    
    location_data = streamlit_geolocation()
    
    if location_data and location_data.get('latitude') is not None:
        lat = float(location_data['latitude'])
        lon = float(location_data['longitude'])
        
        try:
            headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
            rev_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            rev_res = requests.get(rev_url, headers=headers).json()
            address = rev_res.get('address', {})
            city = address.get('city', address.get('town', address.get('village', 'Unknown Area')))
            state = address.get('state', 'Washington')
            location_name = f"{city}, {state}"
        except Exception:
            location_name = "Tacoma, WA"
            
        active_water_body = "Current GPS Location"
        water_context = f"the exact water body coordinates at GPS location {lat:.4f}, {lon:.4f} near {location_name}."
        display_summary = f"🎯 Universal Position Locked: **{location_name}** ({lat:.4f}, {lon:.4f})"
        st.success("🔒 Satellite Handshake Verified")
    else:
        st.write("⏳ *Awaiting satellite link activation click above...*")

elif routing_mode == "✍️ Enter a Specific Water Body By Name":
    user_water = st.text_input("📝 Type the name of the lake, river, or Marine Area:", value="Puyallup River")
    manual_city = st.text_input("📍 Your Base Camp / Closest City (Sets State Jurisdiction):", value="Tacoma, WA")
    location_name = manual_city
    active_water_body = user_water.strip()

else: # 🔍 Suggest Local Hotspots Mode
    manual_city = st.text_input("📍 Search Anchor City (Finds spots within a 50-100 mile radius):", value="Tacoma, WA")
    location_name = manual_city
    active_water_body = "Suggested Spot"

# 🌍 IMMEDIATE DETERMINATION OF JURISDICTION STATE BASELINE
input_state = "Oregon" if re.search(r"\b(or|oregon)\b", location_name, re.IGNORECASE) else "Washington"

# 🧭 EXECUTING SEARCH STRING PROCESSING EARLY TO CAPTURE COORDINATES
if routing_mode in ["🔍 Suggest Local Hotspots", "✍️ Enter a Specific Water Body By Name"]:
    lat, lon = None, None  

if not lat and active_water_body and location_name and active_water_body != "Suggested Spot":
    try:
        query_body = active_water_body.strip()
        if re.search(r"kapow", query_body, re.IGNORECASE):
            query_body = "Lake Kapowsin"
        elif re.search(r"ohop", query_body, re.IGNORECASE):
            query_body = "Lake Ohop"
        elif re.search(r"\blake\b$", query_body, re.IGNORECASE):
            base_name = re.sub(r"\blake\b$", "", query_body, flags=re.IGNORECASE).strip()
            query_body = f"Lake {base_name}"
            
        search_query = f"{query_body}, {input_state}"
        encoded_query = urllib.parse.quote(search_query.strip())
        headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
        osm_url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&countrycodes=us&format=json&addressdetails=1&limit=1"
        osm_res = requests.get(osm_url, headers=headers).json()
        
        if not osm_res or len(osm_res) == 0:
            encoded_city = urllib.parse.quote(location_name.strip())
            osm_url = f"https://nominatim.openstreetmap.org/search?q={encoded_city}&countrycodes=us&format=json&addressdetails=1&limit=1"
            osm_res = requests.get(osm_url, headers=headers).json()

        if osm_res and len(osm_res) > 0:
            lat = float(osm_res[0]["lat"])
            lon = float(osm_res[0]["lon"])
            
            try:
                rev_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
                rev_res = requests.get(rev_url, headers=headers).json()
                address = rev_res.get('address', {})
                true_town = address.get('village', address.get('town', address.get('city', 'Local Area')))
                true_state = address.get('state', input_state)
                location_name = f"{true_town}, {true_state}"
            except Exception:
                pass 
                
            display_summary = f"🗺️ Target Water: **{active_water_body}** ({location_name})"
            water_context = f"the specific body of water named {active_water_body} in {input_state}."
        else:
            lat, lon = 47.2529, -122.4443 
    except Exception:
        lat, lon = 47.2529, -122.4443

# Resolve actual operating agency names based on derived positions
if "oregon" in location_name.lower() or "or" in location_name.lower() or (lat and lat < 46.25):
    detected_state = "Oregon"
    agency_name = "ODFW"
else:
    detected_state = "Washington"
    agency_name = "WDFW"

st.markdown("---")

# =====================================================================
# 🎨 STEP 2 & 3: DYNAMIC CONFIGURATION WINDOWS (STATE JURISDICTION AWARE)
# =====================================================================

# 💉 Inject Micro-Styles for Selection Pills
st.markdown("""
    <style>
        div[data-testid="stPills"] button {
            background-color: #0f172a !important;
            color: #cbd5e1 !important;
            border: 1px solid #334155 !important;
            border-radius: 20px !important;
            padding: 6px 14px !important;
        }
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #22c55e !important;
            color: #0f172a !important;
            font-weight: bold !important;
            border-color: #22c55e !important;
        }
    </style>
""", unsafe_allow_html=True)

config_col1, config_col2 = st.columns(2)

with config_col1:
    st.markdown("### 🌊 2. Environment")
    env_choice = st.segmented_control(
        "Select your system framework:",
        options=["Freshwater", "Saltwater (Marine)"],
        default="Freshwater",
        label_visibility="collapsed"
    )
    if env_choice == "Freshwater":
        st.caption(f"🟢 USGS Data streams mapping to **{detected_state}** hydro networks.")
    else:
        st.caption(f"🔵 NOAA Marine array active for **{detected_state}** tidal zones.")

with config_col2:
    st.markdown("### 🗺️ 3. System Type")
    if env_choice == "Freshwater":
        fw_category = st.segmented_control(
            "Select water body type:", 
            options=["🏞️ Rivers", "🏡 Lakes"], 
            default="🏡 Lakes",
            label_visibility="collapsed"
        )
    else:
        st.markdown(f"<p style='color: #22c55e; font-size: 14px; margin-top: 8px;'>⚓ {agency_name} Marine Management Units</p>", unsafe_allow_html=True)
        fw_category = "🏡 Lakes"

st.markdown("---")

# 🎣 DYNAMIC SPECIES INTAKE (SEGREGATED FOR HABITAT ACCURACY)
st.markdown(f"### 🎣 4. Select Target Species ({agency_name} Legal Catalog)")

if detected_state == "Washington":
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = [
                "King Salmon (Chinook)", "Silver Salmon (Coho)", "Pink Salmon", 
                "Chum Salmon", "Sockeye Salmon", "Summer Steelhead", 
                "Winter Steelhead", "Coastal Cutthroat", "White Sturgeon"
            ]
            default_species = "Silver Salmon (Coho)"
        else: # 🏡 Lowland Lakes Only
            species_options = [
                "Rainbow Trout", "Cutthroat Trout", "Brown Trout", "Brook Trout", 
                "Kokanee", "Crappie", "Largemouth Bass", "Smallmouth Bass", 
                "Yellow Perch", "Walleye", "Channel Catfish", "Bluegill/Sunfish", "Tiger Muskie"
            ]
            default_species = "Crappie"
    else: # ⚓ Saltwater WA
        species_options = ["Resident Coho Salmon", "Blackmouth (Chinook)", "Puget Sound Surfperch", "Flounder", "Spiny Dogfish", "Lingcod", "Cabezon", "Halibut"]
        default_species = "Resident Coho Salmon"
else: # 🌲 Oregon Jurisdiction
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = [
                "Spring Chinook", "Fall Chinook", "Coho Salmon", 
                "Winter Steelhead", "Summer Steelhead", "White Sturgeon", "American Shad"
            ]
            default_species = "Coho Salmon"
        else: # 🏡 Lowland Lakes Only
            species_options = [
                "Rainbow Trout", "Brown Trout", "Brook Trout", "Lake Trout (Mackinaw)", 
                "Kokanee", "Largemouth Bass", "Smallmouth Bass", "Crappie", 
                "Yellow Perch", "Walleye", "Channel Catfish", "Bluegill"
            ]
            default_species = "Crappie"
    else: # ⚓ Saltwater OR
        species_options = ["Ocean Chinook", "Ocean Coho", "Rockfish (Black/Blue)", "Lingcod", "Pacific Halibut", "Surfperch", "Greenling"]
        default_species = "Ocean Coho"

target_fish = st.pills("Choose your target profile:", options=species_options, default=default_species, label_visibility="collapsed")

st.markdown(f"""
    <div style='background-color: #0f172a; padding: 8px 12px; border-radius: 6px; border: 1px dashed #334155; margin-bottom: 20px;'>
        <span style='color: #94a3b8; font-size: 13px;'>🎯 <b>Tactical Lock:</b> Targeting <b>{target_fish}</b> under <b>{agency_name}</b> regulatory jurisdiction rules.</span>
    </div>
""", unsafe_allow_html=True)

# 🔍 LATE-EXECUTION DRIVEN SPOT SCOUTING FOR RADIUS PROMPTS
if routing_mode in ["🔍 Suggest Local Hotspots", "🛰️ Use My Live GPS Coordinates"]:
    st.markdown("### 🛰️ Fast AI Scout Engine")
    if st.button("🔍 Scout & Update Local Choices", use_container_width=True, type="secondary"):
        with st.spinner(f"🤖 Mapping local hotspots near {location_name}..."):
            prompt = f"Provide exactly 3 real, specific local named {env_choice} fishing spots, lakes, boat launches, or marine zones located within a scenic 50-100 mile driving radius of {location_name} that are highly-rated for catching {target_fish}. Output ONLY the 3 names separated by newlines, with no extra text, no markdown bullets, no dashes, and no numbers. Example format:\nLake Kapowsin\nAmerican Lake\nSpanaway Lake"
            try:
                scout_res = gemini_scout_model.call(messages=[{"role": "user", "content": prompt}])
                raw_text = str(scout_res).strip()
                
                cleaned_list = []
                for line in raw_text.split("\n"):
                    clean_line = re.sub(r'^[*-]\s*', '', line)
                    clean_line = re.sub(r'^\d+[.)]\s*', '', clean_line)
                    clean_line = clean_line.strip()
                    if clean_line:
                        cleaned_list.append(clean_line)
                
                if len(cleaned_list) >= 1:
                    st.session_state.scouted_lakes_dict[env_choice] = cleaned_list[:3]
                    st.success("🎯 Hotspots updated!")
                    st.rerun() 
                else:
                    st.error("🤖 AI returned an empty list. Try clicking again.")
            except Exception as e:
                st.error(f"⚠️ Scouting engine timeout: {e}")

    default_spots = ["Spanaway Lake", "American Lake", "Lake Kapowsin"] if env_choice == "Freshwater" else ["Marine Area 11 (Tacoma)", "Marine Area 13 (Olympia)", "Point Defiance Pier"]
    dropdown_options = st.session_state.scouted_lakes_dict.get(env_choice, default_spots)
    selected_suggested = st.selectbox("🎯 Tap to select one of your local suggested hotspots:", options=dropdown_options)
    active_water_body = selected_suggested

    # Run execution parsing on final selected suggestion item context
    if not lat and active_water_body:
        try:
            query_body = active_water_body.strip()
            if re.search(r"\blake\b$", query_body, re.IGNORECASE):
                base_name = re.sub(r"\blake\b$", "", query_body, flags=re.IGNORECASE).strip()
                query_body = f"Lake {base_name}"
            
            search_query = f"{query_body}, {detected_state}"
            encoded_query = urllib.parse.quote(search_query.strip())
            headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
            osm_res = requests.get(f"https://nominatim.openstreetmap.org/search?q={encoded_query}&countrycodes=us&format=json&limit=1", headers=headers).json()
            if osm_res:
                lat = float(osm_res[0]["lat"])
                lon = float(osm_res[0]["lon"])
                
                # Dynamic weather correction on the auto-scouted lake structure item position!
                rev_res = requests.get(f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json", headers=headers).json()
                address = rev_res.get('address', {})
                true_town = address.get('village', address.get('town', address.get('city', 'Local Area')))
                location_name = f"{true_town}, {detected_state}"
        except Exception:
            lat, lon = 47.2529, -122.4443

# =====================================================================
# 🚀 STEP 5: RUN COMPILATION ENGINE & RENDER DASHBOARD UI
# =====================================================================
st.subheader("⚡ Step 5: Run Analysis")
execute_crew = st.button("🚀 Generate Tactical Strategy Plan", type="primary", use_container_width=True)

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

        # Premium Layout Render Calculations
        bite_score = 50
        if "Rising" in trend: bite_score += 20
        elif "Stable" in trend: bite_score += 10
        else: bite_score -= 15  
        if "Cloudy" in cloud_word or "Overcast" in cloud_word: bite_score += 15
        if current['wind_speed_10m'] < 10: bite_score += 15
        elif current['wind_speed_10m'] > 18: bite_score -= 20
        bite_score = max(10, min(100, bite_score)) 
        
        if bite_score >= 75:
            card_border, score_color, rating_text = "#22c55e", "#22c55e", "🏆 EXCELLENT CONDITIONS"
        elif bite_score >= 45:
            card_border, score_color, rating_text = "#eab308", "#eab308", "🟡 FAIR CONDITIONS"
        else:
            card_border, score_color, rating_text = "#ef4444", "#ef4444", "🚨 TOUGH BITE WINDOW"

        # 📊 1. FORECAST BADGE
        st.markdown(f"""
            <div class="bite-card" style="border-left-color: {card_border};">
                <span style="color: #94a3b8; font-size: 14px; font-weight: bold; uppercase;">Live Solunar Analytics</span>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 5px;">
                    <div class="bite-score" style="color: {score_color};">{bite_score}%</div>
                    <div style="text-align: right; font-weight: bold; color: {score_color};">{rating_text}</div>
                </div>
                <p style="margin-top: 8px; margin-bottom: 0; font-size: 14px; color: #cbd5e1;">
                    Barometric trends indicate a <b>{trend.lower()}</b> profile. Water visibility evaluates to <b>{clarity_estimate.split(" ")[0].lower()}</b>.
                </p>
            </div>
        """, unsafe_allow_html=True)

        # 🗺️ 2. NAVIGATION FRAME
        st.markdown(f"### 🗺️ Navigation Hub: {active_water_body}")
        google_maps_url = f"https://maps.google.com/maps?q={lat},{lon}&t=k&z=14&output=embed"
        st.iframe(src=google_maps_url, height=400)
        
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            encoded_search = urllib.parse.quote(f"{active_water_body} depth chart contour map")
            st.link_button("🔍 Search Bathymetric Charts", f"https://www.google.com/search?q={encoded_search}&tbm=isch", use_container_width=True)
        with m_col2:
            st.button("📍 Log Secret Waypoint Coordinates", use_container_width=True, disabled=True)

        st.markdown("---")

        # 📈 3. COMPACT TABBED INTERFACE LAYOUT
        tab_cond, tab_hydro, tab_strategy, tab_rules = st.tabs(["🌦️ Atmosphere", "🌊 Water Gauges", "🎣 Tactical Strategy", "🚨 Game Rules"])

        with tab_cond:
            st.caption(f"🗺️ Position Fixed: {lat:.4f}, {lon:.4f} | System Zone Context: {location_name}")
            w_col1, w_col2, w_col3 = st.columns(3)
            with w_col1:
                st.metric(label="🌡️ Calculated Water Temp", value=f"{estimated_water_temp:.1f}°F")
                st.metric(label="🌤️ Outside Air Temp", value=f"{current['temperature_2m']:.1f}°F")
            with w_col2:
                st.metric(label="💨 Wind Velocity", value=f"{current['wind_speed_10m']} mph")
            with w_col3:
                st.metric(label="☁️ Sky Density Cover", value=cloud_word)
            st.info(f"📈 **Barometric Micro-Changes:** {trend} ({diff:+.2f} hPa relative to baseline)")

        with tab_hydro:
            st.markdown("#### 🛰️ Real-Time Streamflow & Marine Station Feeds")
            if "unavailable" not in live_gauge_data.lower() and "⚠️" not in live_gauge_data:
                st.success(f"{live_gauge_data}")
            else:
                st.warning(f"{live_gauge_data}")

        with tab_strategy:
            if execute_crew:
                inputs = {
                    'target_fish': target_fish,
                    'environment': water_context if water_context else f"fishing target body near {location_name}",  
                    'current_state': detected_state,
                    'water_temp': f"{estimated_water_temp:.1f}°F",  
                    'barometric_pressure': trend, 
                    'cloud_cover': cloud_word,
                    'wind_speed': f"{current['wind_speed_10m']} mph",
                    'water_clarity': f"{clarity_estimate}. Field data: {live_gauge_data}"
                }
                with st.spinner("🤖 Compiling rigging tactics with AI Crew Specialists..."):
                    result = FishingAgentApp().crew().kickoff(inputs=inputs)
                    st.session_state.current_raw_output = result.raw if hasattr(result, 'raw') else str(result)
                    st.success("🎯 Strategy Formulated!")
            
            if "current_raw_output" in st.session_state:
                raw_out = st.session_state.current_raw_output
                if "### 🎣 Tactical Strategy Plan" in raw_out:
                    st.markdown(raw_out.split("### 🎣 Tactical Strategy Plan")[1].strip())
                else:
                    st.markdown(raw_out)
            else:
                st.info("💡 Tap **'Generate Tactical Strategy Plan'** above to compile custom rigging patterns.")

        with tab_rules:
            st.markdown(f"#### 🚨 Regional Legal Compliance Guardrails ({agency_name})")
            if "current_raw_output" in st.session_state:
                raw_out = st.session_state.current_raw_output
                if "### 🎣 Tactical Strategy Plan" in raw_out:
                    st.markdown(raw_out.split("### 🎣 Tactical Strategy Plan")[0].replace("### 🚨 Regional Legal Compliance Guardrails & Location Suggestions", "").strip())
                else:
                    st.write("Review localized regulatory parameters on the primary console output data block.")
            else:
                st.warning(f"Verify standard limit definitions on your native **{agency_name}** regional dashboard before making your first cast.")

    except Exception as err:
        st.error(f"Failed to compile weather data stream: {err}")
