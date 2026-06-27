import streamlit as st
import sys
import os
import requests
import urllib.parse
import re
import sqlite3
import pandas as pd
from datetime import datetime

# 🛰️ Native Universal Hardware Geolocation Link
from streamlit_geolocation import streamlit_geolocation
import folium
from streamlit_folium import st_folium

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# 🔑 Load the Groq Key from Secrets Vault
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

from crewai import LLM
from fishing_agent_app.crew import FishingAgentApp

# =====================================================================
# 🧠 MASTER GLOBAL SESSION STATE INITIALIZATION 
# =====================================================================
if "lat" not in st.session_state:
    st.session_state.lat = 47.2529
if "lon" not in st.session_state:
    st.session_state.lon = -122.4443
if "location_name" not in st.session_state:
    st.session_state.location_name = "Tacoma, WA"

# Fallback local mirror variables for structural layout routing
lat = st.session_state.lat
lon = st.session_state.lon
location_name = st.session_state.location_name

# 🏎️ Route the AI Scouting Engine through Groq's ultra-fast free tier
gemini_scout_model = LLM(
    model="groq/llama-3.1-8b-instant",
    temperature=0.1
)

logo_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
st.set_page_config(page_title="Global Mobile Fishing Crew", page_icon=logo_path, layout="wide")
st.title("🎣 Mobile Fishing Advisor")

app_base_url = "https://fishing-guide.streamlit.app"
st.logo(logo_path) 

# =====================================================================
# ⚡ CENTRAL ANTI-LAG CACHING MATRIX
# =====================================================================

@st.cache_data(ttl=600)
def get_coordinates_from_osm(search_query):
    """Caches text-to-coordinate lookups to eliminate map pan lag"""
    headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(search_query)}&countrycodes=us,ca,mx&format=json&limit=1"
        return requests.get(url, headers=headers, timeout=5).json()
    except Exception:
        return []

@st.cache_data(ttl=600)
def get_address_from_gps(lat, lon):
    """Caches reverse GPS-to-city lookups"""
    headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        return requests.get(url, headers=headers, timeout=5).json()
    except Exception:
        return {}

@st.cache_data(ttl=600)
def fetch_cached_weather(lat, lon):
    """Caches weather data for 10 minutes so map zooming skips internet loading calls"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,cloud_cover,surface_pressure,wind_speed_10m&hourly=surface_pressure,precipitation,temperature_2m&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
        return requests.get(url, timeout=5).json()
    except Exception:
        return None

# =====================================================================
# 🗄️ DATABASE SYSTEM (Tiny Local Footprint: ~1KB per catch)
# =====================================================================
DB_FILE = "premium_catches.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS catch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            lake_name TEXT,
            species TEXT,
            weight REAL,
            latitude REAL,
            longitude REAL,
            substrate TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

if "scouted_lakes_dict" not in st.session_state:
    st.session_state.scouted_lakes_dict = {
        "Freshwater": [],
        "Saltwater (Marine)": []
    }

STATE_DICTIONARY = {
    "wa": "Washington", "or": "Oregon", "tx": "Texas", "pa": "Pennsylvania",
    "fl": "Florida", "ca": "California", "ny": "New York", "mi": "Michigan",
    "mn": "Minnesota", "oh": "Ohio", "wi": "Wisconsin", "ga": "Georgia"
}

# =====================================================================
# 🛰️ STEP 1: LOCATION-FIRST ROUTING MODULE (THE ANCHOR)
# =====================================================================
st.subheader("📡 Step 1: Destination Routing Mode")
routing_mode = st.radio(
    "How do you want to set your fishing location?",
    options=["🛰️ Use My Live GPS Coordinates", "📝 Enter a Specific Water Body By Name", "🔍 Suggest Local Hotspots"],
    horizontal=True
)

water_context = ""
display_summary = ""
active_water_body = ""
base_anchor_city = ""

scout_dropdown_val = st.session_state.get(f"sb_hotspots_{routing_mode}")
if scout_dropdown_val and not scout_dropdown_val.startswith("⚡"):
    active_water_body = scout_dropdown_val

if routing_mode == "🛰️ Use My Live GPS Coordinates":
    st.markdown("### 🛰️ Mobile Satellite Link")
    st.info("Tap the button below to broadcast your phone's live coordinate data stream.")
    
    location_data = streamlit_geolocation()
    
    if location_data and location_data.get('latitude') is not None:
        if not active_water_body:
            # 🔒 Save the live coordinates into long-term memory
            st.session_state.lat = float(location_data['latitude'])
            st.session_state.lon = float(location_data['longitude'])
            lat = st.session_state.lat
            lon = st.session_state.lon
            
            try:
                headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
                rev_res = get_address_from_gps(lat, lon)
                address = rev_res.get('address', {})
                city = address.get('city', address.get('town', address.get('village', 'Unknown Area')))
                state = address.get('state', 'Washington')
                st.session_state.location_name = f"{city}, {state}"
                location_name = st.session_state.location_name
            except Exception:
                st.session_state.location_name = "Tacoma, WA"
                location_name = st.session_state.location_name
                
            active_water_body = "Current GPS Location"
            water_context = f"the exact water body coordinates at GPS location {lat:.4f}, {lon:.4f} near {location_name}."
            display_summary = f"🎯 Universal Position Locked: **{location_name}** ({lat:.4f}, {lon:.4f})"
        else:
            lat = st.session_state.lat
            lon = st.session_state.lon
            location_name = st.session_state.location_name
            
        base_anchor_city = location_name
        st.success("🔒 Satellite Handshake Verified")
    else:
        if not st.session_state.get("lat"):
            st.session_state.lat = 47.2529
            st.session_state.lon = -122.4443
            st.session_state.location_name = "Tacoma, WA"
        lat = st.session_state.lat
        lon = st.session_state.lon
        location_name = st.session_state.location_name
        base_anchor_city = location_name

elif routing_mode == "📝 Enter a Specific Water Body By Name":
    user_water = st.text_input("📝 Type the name of the lake, river, or Marine Area:", value="Puyallup River")
    manual_city = st.text_input("📍 Your Base Camp / Closest City (Sets State Jurisdiction):", value="Tacoma, WA")
    location_name = manual_city
    base_anchor_city = manual_city
    if not active_water_body:
        active_water_body = user_water.strip()

else: 
    manual_city = st.text_input("📍 Search Anchor City (Finds spots within a 50-100 mile radius):", value="Tacoma, WA")
    location_name = manual_city
    base_anchor_city = manual_city

if base_anchor_city:
    state_match = re.search(r",\s*([A-Za-z\s]+)$", base_anchor_city)
    input_state = state_match.group(1).strip() if state_match else base_anchor_city
else:
    input_state = "Washington"

clean_state_key = input_state.strip().lower()
if clean_state_key in STATE_DICTIONARY:
    input_state = STATE_DICTIONARY[clean_state_key]

# =====================================================================
# 🎨 STEP 2 & 3: DYNAMIC CONFIGURATION WINDOWS
# =====================================================================
st.markdown("---")
config_col1, config_col2 = st.columns(2)

with config_col1:
    st.markdown("### 🌊 2. Environment")
    env_choice = st.segmented_control(
        "Select your system framework:", options=["Freshwater", "Saltwater (Marine)"], default="Freshwater", label_visibility="collapsed"
    )

with config_col2:
    st.markdown("### 🗺️ 3. System Type")
    if env_choice == "Freshwater":
        fw_category = st.segmented_control(
            "Select water body type:", options=["🏞️ Rivers", "🏡 Lakes"], default="🏡 Lakes", label_visibility="collapsed"
        )
    else:
        st.markdown(f"<p style='color: #22c55e; font-size: 14px; margin-top: 8px;'>⚓ Marine Management Units Active</p>", unsafe_allow_html=True)
        fw_category = "🏡 Lakes"

# =====================================================================
# 🎣 STEP 4: MULTI-STATE / GLOBAL BIOLOGICAL TARGET MENUS
# =====================================================================
st.markdown("---")
st.markdown(f"### 🎣 4. Select Target Species ({input_state} Catalog)")

if input_state == "Washington":
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = ["King Salmon (Chinook)", "Silver Salmon (Coho)", "Pink Salmon", "Chum Salmon", "Sockeye Salmon", "Summer Steelhead", "Winter Steelhead", "Coastal Cutthroat", "White Sturgeon"]
        else:
            species_options = ["Rainbow Trout", "Cutthroat Trout", "Brown Trout", "Brook Trout", "Kokanee", "Crappie", "Largemouth Bass", "Smallmouth Bass", "Yellow Perch", "Walleye", "Channel Catfish", "Bluegill/Sunfish", "Tiger Muskie"]
    else:
        species_options = ["Resident Coho Salmon", "Blackmouth (Chinook)", "Puget Sound Surfperch", "Flounder", "Spiny Dogfish", "Lingcod", "Cabezon", "Halibut"]

elif input_state == "Oregon":
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = ["Spring Chinook", "Fall Chinook", "Coho Salmon", "Winter Steelhead", "Summer Steelhead", "White Sturgeon", "American Shad"]
        else:
            species_options = ["Rainbow Trout", "Brown Trout", "Brook Trout", "Lake Trout (Mackinaw)", "Kokanee", "Largemouth Bass", "Smallmouth Bass", "Crappie", "Yellow Perch", "Walleye", "Channel Catfish", "Bluegill"]
    else:
        species_options = ["Ocean Chinook", "Ocean Coho", "Rockfish (Black/Blue)", "Lingcod", "Pacific Halibut", "Surfperch", "Greenling"]

elif input_state == "Texas":
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = ["Alligator Gar", "Striped Bass", "White Bass", "Guadalupe Bass", "Channel Catfish", "Flathead Catfish", "Blue Catfish"]
        else:
            species_options = ["Largemouth Bass", "Smallmouth Bass", "Spotted Bass", "White Crappie", "Black Crappie", "Bluegill", "Channel Catfish", "Blue Catfish", "Hybrid Striped Bass", "Walleye"]
    else:
        species_options = ["Red Drum (Redfish)", "Spotted Seatrout", "Black Drum", "Flounder", "Sheepshead", "King Mackerel", "Cobias", "Snapper (Red)"]

elif input_state == "Pennsylvania":
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = ["Smallmouth Bass", "Walleye", "Muskellunge", "Channel Catfish", "Flathead Catfish", "Brown Trout", "Brook Trout"]
        else:
            species_options = ["Largemouth Bass", "Walleye", "Yellow Perch", "Black Crappie", "Bluegill", "Rainbow Trout", "Northern Pike", "Channel Catfish"]
    else:
        species_options = ["Striped Bass", "Summer Flounder", "Bluefish", "Weakfish", "Tautog"]

else: 
    if env_choice == "Freshwater":
        if fw_category == "🏞️ Rivers":
            species_options = ["Salmon", "Steelhead", "River Trout", "Smallmouth Bass", "Striper", "Catfish", "Walleye"]
        else:
            species_options = ["Largemouth Bass", "Smallmouth Bass", "Rainbow Trout", "Crappie", "Panfish/Bluegill", "Walleye", "Northern Pike", "Catfish"]
    else:
        species_options = ["Coastal Gamefish", "Inshore Sea Trout", "Snook/Redfish", "Striper", "Flounder", "Rockfish/Cod", "Deep Sea Pelagic"]

default_species = species_options[0] if species_options else ""
target_fish = st.pills("Choose your target profile:", options=species_options, default=default_species, label_visibility="collapsed")

# =====================================================================
# ⚙️ AUTOMATED RADAR SCOUT ENGINE WITH HARDCODED BIOLOGICAL OVERRIDES
# =====================================================================
if routing_mode in ["🔍 Suggest Local Hotspots", "🛰️ Use My Live GPS Coordinates"]:
    scout_fingerprint = f"{routing_mode}_{env_choice}_{fw_category}_{target_fish}_{base_anchor_city}"
    
    if st.session_state.get("last_scout_fingerprint") != scout_fingerprint and base_anchor_city != "":
        if "Channel Catfish" in target_fish and input_state == "Washington":
            st.session_state.scouted_lakes_dict[env_choice] = ["Green Lake (Seattle)", "Sprague Lake", "Swofford Pond"]
            st.session_state.last_scout_fingerprint = scout_fingerprint
            st.rerun()
        elif "Tiger Muskie" in target_fish and input_state == "Washington":
            st.session_state.scouted_lakes_dict[env_choice] = ["Mayfield Lake", "Merwin Lake", "Newman Lake"]
            st.session_state.last_scout_fingerprint = scout_fingerprint
            st.rerun()
            
        else:
            with st.spinner(f"🤖 Auto-Scouting fresh local options near {base_anchor_city}..."):
                prompt = f"Provide exactly 3 real, specific local named {env_choice} fishing spots, lakes, boat launches, or marine zones located within a scenic 50-100 mile driving radius of {base_anchor_city} that are highly-rated for catching {target_fish}. Output ONLY the 3 names separated by newlines, with no extra text, no markdown bullets, no dashes, and no numbers."
                try:
                    scout_res = gemini_scout_model.call(messages=[{"role": "user", "content": prompt}])
                    raw_text = str(scout_res).strip()
                    cleaned_list = [re.sub(r'^\d+[.)]\s*|^[*-]\s*', '', line).strip() for line in raw_text.split("\n") if line.strip()]
                    if len(cleaned_list) >= 1:
                        st.session_state.scouted_lakes_dict[env_choice] = cleaned_list[:3]
                        st.session_state.last_scout_fingerprint = scout_fingerprint
                        st.rerun()
                except Exception:
                    pass

    if scout_fingerprint != st.session_state.get("last_scout_fingerprint"):
        dropdown_options = [f"⚡ [Click to Scan Local Spots for {target_fish}]"]
    else:
        dropdown_options = st.session_state.scouted_lakes_dict.get(env_choice, [])
        if not dropdown_options:
            dropdown_options = [f"⚡ [Click to Scan Local Spots for {target_fish}]"]

    selected_suggested = st.selectbox(
        "🎯 Tap to select one of your local suggested hotspots:", 
        options=dropdown_options, 
        key=f"sb_hotspots_{routing_mode}_{env_choice}_{fw_category}"
    )

    if "⚡" in selected_suggested:
        active_water_body = ""
    else:
        active_water_body = selected_suggested

# =====================================================================
# 🧭 RESOLVE TARGET COORDINATES (GEOLOCATION INTERCEPT PROCESSORS)
# =====================================================================
if active_water_body and active_water_body != "Current GPS Location":
    try:
        query_body = re.sub(r"\(Seattle\)", "", active_water_body, flags=re.IGNORECASE).strip()
        
        if re.search(r"kapow", query_body, re.IGNORECASE): query_body = "Lake Kapowsin"
        elif re.search(r"ohop", query_body, re.IGNORECASE): query_body = "Lake Ohop"
        elif env_choice == "Freshwater" and fw_category == "🏡 Lakes" and not re.search(r"\blake\b", query_body, re.IGNORECASE):
            query_body = f"Lake {query_body}"

        search_query = f"{query_body}, {input_state}, water=lake" if (env_choice == "Freshwater" and fw_category == "🏡 Lakes") else f"{query_body}, {input_state}"
        
        # Pull from cached OSM execution module
        osm_res = get_coordinates_from_osm(search_query)
        if not osm_res:
            loose_query = f"{query_body}, {input_state}"
            osm_res = get_coordinates_from_osm(loose_query)

        if osm_res:
            # 🔒 Directly commit search coordinates to state memory
            st.session_state.lat = float(osm_res[0]["lat"])
            st.session_state.lon = float(osm_res[0]["lon"])
            
            try:
                rev_res = get_address_from_gps(st.session_state.lat, st.session_state.lon)
                address = rev_res.get('address', {})
                resolved_state = address.get('state', input_state)
                st.session_state.location_name = f"{address.get('village', address.get('town', address.get('city', 'Local Area')))}, {resolved_state}"
            except Exception:
                st.session_state.location_name = f"{active_water_body}, {input_state}"
            
            display_summary = f"🗺️ Target Water: **{active_water_body}** ({st.session_state.location_name})"
            water_context = f"the specific body of water named {active_water_body} in {input_state}."
    except Exception:
        pass
else:
    if routing_mode != "🛰️ Use My Live GPS Coordinates" and base_anchor_city:
        osm_res = get_coordinates_from_osm(base_anchor_city)
        if osm_res:
            st.session_state.lat = float(osm_res[0]["lat"])
            st.session_state.lon = float(osm_res[0]["lon"])
            st.session_state.location_name = base_anchor_city

# 🗺️ Hardcoded Target Overrides (For Specific Verified Coordinates)
if active_water_body:
    if "wallenpaupack" in active_water_body.lower():
        st.session_state.lat, st.session_state.lon = 41.4201, -75.2333
        st.session_state.location_name = "Pocono Mountains, PA"
    elif "green lake" in active_water_body.lower() and "seattle" in base_anchor_city.lower():
        st.session_state.lat, st.session_state.lon = 47.6797, -122.3256
        st.session_state.location_name = "Seattle, WA"
    elif "elmo" in active_water_body.lower():
        st.session_state.lat, st.session_state.lon = 45.8410, -108.4794
        st.session_state.location_name = "Billings/Great Falls Region, MT"

# 🧲 Pull the active variables out of session state directly for the rest of the app execution
lat = st.session_state.lat
lon = st.session_state.lon
location_name = st.session_state.location_name
check_str = location_name.lower() if ("location_name" in locals() and location_name != "") else base_anchor_city.lower()

# 🏔️ Fixed State Calculator (Handles Montana explicitly to stop Oregon bleed)
if "montana" in check_str or "mt" in check_str:
    detected_state = "Montana"
    agency_name = "FWP"
elif "texas" in check_str or "tx" in check_str:
    detected_state = "Texas"
    agency_name = "TPWD"
elif "oregon" in check_str or "or" in check_str:
    detected_state = "Oregon"
    agency_name = "ODFW"
elif "pennsylvania" in check_str or "pa" in check_str:
    detected_state = "Pennsylvania"
    agency_name = "PFBC"
else:
    detected_state = "Washington"
    agency_name = "WDFW"

# =====================================================================
# 🚀 STEP 5: RUN COMPILATION ENGINE & RENDER DASHBOARD UI
# =====================================================================
st.subheader("⚡ Step 5: Run Analysis")
execute_crew = st.button("🚀 Generate Tactical Strategy Plan", type="primary", use_container_width=True)

if lat and lon:
    try:
        # Pull from our ultra-fast weather caching block
        weather = fetch_cached_weather(lat, lon)
        
        # 🛡️ SAFETY CHECKPOINT: If API limits are throttling, inject backup data instead of crashing
        if not weather or 'current' not in weather:
            current = {
                'temperature_2m': 65.0, 
                'cloud_cover': 50, 
                'surface_pressure': 1013.25, 
                'wind_speed_10m': 5.0
            }
            trend = "Stable (API Limit Throttling)"
            cloud_word = "Partially Cloudy"
            recent_rain = 0.0
            clarity_estimate = "Clear Water Visibility"
            estimated_water_temp = 62.0
            current_air_temp = 65.0
        else:
            current = weather['current']
            diff = current['surface_pressure'] - weather['hourly']['surface_pressure'][-3]
            trend = "Rising rapidly" if diff > 0.05 else "Rising slowly" if diff > 0.01 else "Falling rapidly" if diff < -0.05 else "Falling slowly" if diff < -0.01 else "Stable"
            cloud_word = "Clear/Sunny" if current['cloud_cover'] < 20 else "Partially Cloudy" if current['cloud_cover'] < 60 else "Overcast"
            
            recent_rain = sum(weather['hourly'].get('precipitation', [0.0])[-12:])
            clarity_estimate = "Stained / Muddy Runoff" if (recent_rain > 0.50 or current['wind_speed_10m'] > 15) else "Slightly Stained / Milky" if recent_rain > 0.15 else "Clear Water Visibility"
            estimated_water_temp = (0.7 * (sum(weather['hourly']['temperature_2m'][:72]) / 72)) + (0.3 * current['temperature_2m'])
            current_air_temp = current['temperature_2m']

        live_gauge_data = "Station data unavailable for static land locations."
        if env_choice == "Freshwater":
            try:
                usgs_res = requests.get(f"https://waterservices.usgs.gov/nwis/iv/?format=json&bBox={lon-0.45:.4f},{lat-0.45:.4f},{lon+0.45:.4f},{lat+0.45:.4f}&parameterCd=00060,00065&siteStatus=active", timeout=6).json()
                time_series = usgs_res.get('value', {}).get('timeSeries', [])
                if time_series:
                    ts_entry = time_series[0]
                    val = ts_entry['values'][0]['value'][0]['value']
                    unit = "CFS (Flow)" if "00060" in ts_entry['variable']['variableCode'][0]['value'] else "ft (Height)"
                    live_gauge_data = f"🌊 Gauge: {ts_entry['sourceInfo']['siteName']} | State: {val} {unit}"
            except Exception: pass
        else:
            try:
                noaa_res = requests.get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=latest&range=24&product=water_level&datum=MLLW&units=english&time_zone=lst_ldt&format=json&application=PNWFishingCrew&station=9446484", timeout=5).json()
                if "data" in noaa_res:
                    live_gauge_data = f"⚓ NOAA 9446484 | Tide: {noaa_res['data'][-1]['v']} ft above MLLW at {noaa_res['data'][-1]['t']}"
            except Exception: pass

        bite_score = max(10, min(100, 50 + (20 if "Rising" in trend else 10 if "Stable" in trend else -15) + (15 if "Cloudy" in cloud_word or "Overcast" in cloud_word else 0) + (15 if current['wind_speed_10m'] < 10 else -20 if current['wind_speed_10m'] > 18 else 0)))
        card_border, score_color, rating_text = ("#22c55e", "#22c55e", "🏆 EXCELLENT") if bite_score >= 75 else ("#eab308", "#eab308", "🟡 FAIR") if bite_score >= 45 else ("#ef4444", "#ef4444", "🚨 TOUGH BITE")

        st.markdown(f"""
            <style>
                .bite-card {{ background-color: #1e293b; border-radius: 12px; padding: 20px; border-left: 6px solid {card_border}; margin-bottom: 20px; }}
                .bite-score {{ font-size: 32px; font-weight: bold; color: {score_color}; }}
            </style>
            <div class="bite-card">
                <span style="color: #94a3b8; font-size: 14px; font-weight: bold;">Live Analytics</span>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 5px;">
                    <div class="bite-score">{bite_score}%</div>
                    <div style="font-weight: bold; color: {score_color};">{rating_text}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

# =====================================================================
        # 🗺️ GRAPHICAL GRID & PREMIUM INTERACTIVE LOGGING CORE
        # =====================================================================
        m_col1, m_col2 = st.columns([2, 1])
        
        with m_col1:
            st.markdown(f"### 🛰️ Interactive Survey Grid: {active_water_body}")
            
            if "map_view" not in st.session_state or st.session_state.get("last_water_body") != active_water_body:
                st.session_state.map_view = {"center": [lat, lon], "zoom": 13}
                st.session_state.last_water_body = active_water_body

            # 🚀 ULTRA-LIGHTWEIGHT BASE MAP FRAME (Wipes out zoom lag entirely)
            m = folium.Map(
                location=st.session_state.map_view["center"], 
                zoom_start=st.session_state.map_view["zoom"],
                tiles="OpenStreetMap"
            )

            try:
                conn = sqlite3.connect(DB_FILE)
                saved_catches = pd.read_sql_query("SELECT * FROM catch_log", conn)
                conn.close()
                for _, row in saved_catches.iterrows():
                    folium.Marker(
                        location=[row['latitude'], row['longitude']],
                        popup=f"🎣 {row['species']} ({row['weight']} lbs)<br>⏳ {row['timestamp']}",
                        icon=folium.Icon(color='blue', icon='fish', prefix='fa')
                    ).add_to(m)
            except Exception:
                saved_catches = pd.DataFrame()

            m.add_child(folium.LatLngPopup())
            
            # 🏎️ HIGH-PERFORMANCE FILTERS: Only reload the page on explicit pin-drop clicks
            map_data = st_folium(
                m, 
                width=750, 
                height=450, 
                key=f"stable_map_{active_water_body}",
                returned_objects=["last_clicked"]
            )
            if map_data.get("center"):
                st.session_state.map_view["center"] = [map_data["center"]["lat"], map_data["center"]["lng"]]
                st.session_state.map_view["zoom"] = map_data["zoom"]

        with m_col2:
            st.markdown("### 📝 Telemetry Log Hub")
            clicked_coords = map_data.get("last_clicked")
            
            if clicked_coords:
                c_lat, c_lon = clicked_coords["lat"], clicked_coords["lng"]
                st.success(f"🎯 Pin Set: {c_lat:.4f}, {c_lon:.4f}")
                
                with st.form("catch_form", clear_on_submit=True):
                    species_log = st.selectbox("Caught Profile:", [target_fish] if target_fish else ["Largemouth Bass"])
                    weight_log = st.number_input("Weight (lbs):", min_value=0.1, value=2.5)
                    substrate_log = st.segmented_control("Substrate Composition:", ["Sand Bank", "Rock/Boulders", "Mud/Silt", "Weed Line"], default="Sand Bank")
                    submit = st.form_submit_button("🔒 Secure Entry to Local DB")
                    
                    if submit:
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO catch_log (timestamp, lake_name, species, weight, latitude, longitude, substrate)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (datetime.now().strftime("%Y-%m-%d %H:%M"), active_water_body, species_log, weight_log, c_lat, c_lon, substrate_log))
                        conn.commit()
                        conn.close()
                        st.toast("Catch synchronized to hard drive storage workspace!", icon="💾")
                        st.rerun()
            else:
                st.info("💡 Tap directly on any hot spot or structure on the map grid to lock coordinates and open your premium catch logger panel.")

        st.markdown("---")
        
        clean_lake_name = urllib.parse.quote(active_water_body.strip())
        if detected_state == "Washington":
            state_gis_url = f"https://wdfw.wa.gov/fishing/locations/lowland-lakes"
            gis_label = "🌲 Launch WDFW Hydro Graphics Portal"
        elif detected_state == "Oregon":
            state_gis_url = f"https://oregonexplorer.info/topics/Water"
            gis_label = "🌲 Open Oregon Explorer Portal"
        elif detected_state == "Texas":
            state_gis_url = f"https://tpwd.texas.gov/fishboat/fish/recreational/lakes/"
            gis_label = "🤠 Open Texas Volumetric Lake Surveys"
        else:
            state_gis_url = f"https://www.google.com/search?q={clean_lake_name}+{detected_state}+depth+contour+map&tbm=isch"
            gis_label = "🔍 Scan Public Contour Archives"

        b_col1, b_col2 = st.columns(2)
        with b_col1: 
            st.link_button(gis_label, state_gis_url, use_container_width=True)
        with b_col2: 
            st.link_button("🚙 Launch Phone GPS Route", f"http://maps.google.com/?q={lat},{lon}", use_container_width=True, type="primary")

        st.markdown("---")
        tab_cond, tab_hydro, tab_strategy, tab_rules = st.tabs(["🌦️ Atmosphere", "🌊 Water Gauges", "🎣 Tactical Strategy", "🚨 Game Rules"])

        with tab_cond:
            st.caption(f"🗺️ Position Fixed: {lat:.4f}, {lon:.4f} | Region Context: {location_name}")
            w_col1, w_col2, w_col3, w_col4 = st.columns(4)
            w_col1.metric("🌡️ Water Temp", f"{estimated_water_temp:.1f}°F")
            w_col2.metric("🌤️ Air Temp", f"{current_air_temp:.1f}°F")
            w_col3.metric("💨 Wind", f"{current['wind_speed_10m']} mph")
            w_col4.metric("☁️ Sky", cloud_word)

        with tab_hydro: st.info(live_gauge_data)

        with tab_strategy:
            if execute_crew:
                with st.spinner("🤖 Formulating tactics..."):
                    result = FishingAgentApp().crew().kickoff(inputs={'target_fish': target_fish, 'environment': water_context, 'current_state': detected_state, 'water_temp': f"{estimated_water_temp:.1f}°F", 'barometric_pressure': trend, 'cloud_cover': cloud_word, 'wind_speed': f"{current['wind_speed_10m']} mph", 'water_clarity': clarity_estimate})
                    st.session_state.current_raw_output = result.raw if hasattr(result, 'raw') else str(result)
            if "current_raw_output" in st.session_state:
                st.markdown(st.session_state.current_raw_output.split("### 🎣 Tactical Strategy Plan")[1].strip() if "### 🎣 Tactical Strategy Plan" in st.session_state.current_raw_output else st.session_state.current_raw_output)

        with tab_rules:
            if "current_raw_output" in st.session_state and "### 🎣 Tactical Strategy Plan" in st.session_state.current_raw_output:
                st.markdown(st.session_state.current_raw_output.split("### 🎣 Tactical Strategy Plan")[0].replace("### 🚨 Regional Legal Compliance Guardrails & Location Suggestions", "").strip())
            else: st.warning(f"Verify rules on your native dashboard.")

    except Exception as err: st.error(f"Telemetry stream failed: {err}")