import streamlit as st
import sys
import os
import requests
import urllib.parse
import re
import time
import math
import sqlite3
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime
import litellm

# Groq 429 handling: do NOT let litellm retry internally.
# Free tier is 8k TPM; internal retries with short backoff just burn more budget and
# guarantee the next attempt also 429s (retry death spiral). One clean attempt per call --
# the app waits out the TPM window itself.
litellm.num_retries = 0

# 🛰️ Native Universal Hardware Geolocation Link
from streamlit_geolocation import streamlit_geolocation

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# 🔑 Load the Groq Key from Secrets Vault
groq_key_fallback = st.secrets["GROQ_API_KEY"] if "GROQ_API_KEY" in st.secrets else os.environ.get("GROQ_API_KEY", "")

os.environ["GROQ_API_KEY"] = groq_key_fallback
os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

from crewai import LLM
from fishing_agent_app.crew import FishingAgentApp

# 🚀 Configured with Groq's active gpt-oss-20b model and token limits to prevent TPM rate limits
production_llm = LLM(
    model="groq/openai/gpt-oss-20b",
    api_key=groq_key_fallback,
    temperature=0.1,
    max_tokens=1000
)
logo_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
st.set_page_config(page_title="Global Mobile Fishing Crew", page_icon=logo_path, layout="wide")
st.title("🎣 Mobile Fishing Advisor")
st.logo(logo_path)

# =====================================================================
# ⚡ CENTRAL ANTI-LAG CACHING MATRIX
# =====================================================================
@st.cache_data(ttl=600)
def get_coordinates_from_osm(search_query, lat=None, lon=None, limit=5):
    # Nominatim search biased toward the anchor point.
    # Returns up to `limit` candidates (with address details) so callers
    # can rank by state match and distance instead of trusting one blind hit.
    headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
    try:
        params = {
            "q": search_query,
            "countrycodes": "us,ca,mx",
            "format": "json",
            "limit": limit,
            "addressdetails": 1,
        }
        if lat is not None and lon is not None:
            d = 1.5  # ~100-mile viewbox bias around the anchor
            params["viewbox"] = f"{lon-d},{lat+d},{lon+d},{lat-d}"
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
        res = requests.get(url, headers=headers, timeout=8).json()
        return res if isinstance(res, list) else []
    except Exception:
        return []

@st.cache_data(ttl=600)
def get_address_from_gps(lat, lon):
    headers = {'User-Agent': 'PNWFishingAdvisorApp/2.0'}
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        res = requests.get(url, headers=headers, timeout=5).json()
        address = res.get('address', {})
        
        city = address.get('city', address.get('town', address.get('suburb', address.get('county', address.get('village', 'Local Area')))))
        state = address.get('state', address.get('state_district', address.get('region', '')))
        
        return {'city': city, 'state': state}
    except Exception:
        return {'city': 'Local Area', 'state': ''}

def haversine_miles(lat1, lon1, lat2, lon2):
    # Great-circle distance in miles.
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def pick_best_osm_result(results, anchor_lat, anchor_lon, state):
    # Pick the candidate in the right state and closest to the anchor.
    # State match first, then haversine distance. Never trusts
    # Nominatim's importance ranking alone.
    if not results:
        return None
    want_state = (state or "").strip().lower()
    state_known = bool(want_state) and want_state != "local region"
    scored = []
    for res in results:
        try:
            rlat, rlon = float(res["lat"]), float(res["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        addr = res.get("address") or {}
        rstate = (addr.get("state") or "").lower()
        state_ok = bool(state_known and rstate and (want_state in rstate or rstate in want_state))
        if anchor_lat is not None and anchor_lon is not None:
            dist = haversine_miles(anchor_lat, anchor_lon, rlat, rlon)
        else:
            dist = float("inf")
        scored.append((0 if state_ok else 1, dist, res))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2]

def resolve_lake_location(query_body, anchor_lat, anchor_lon, state, quiet=False, max_miles=60):
    # Resolve a lake name to (lat, lon) near the anchor.
    # Tries state-qualified then bare queries, always proximity-ranked.
    # Returns None instead of a far-away guess.
    candidates = []
    want_state = (state or "").strip()
    if want_state and want_state.lower() != "local region":
        candidates = get_coordinates_from_osm(f"{query_body}, {want_state}", lat=anchor_lat, lon=anchor_lon)
    if not candidates:
        candidates = get_coordinates_from_osm(query_body, lat=anchor_lat, lon=anchor_lon)
    best = pick_best_osm_result(candidates, anchor_lat, anchor_lon, want_state)
    if not best:
        return None
    try:
        blat, blon = float(best["lat"]), float(best["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    if anchor_lat is not None and haversine_miles(anchor_lat, anchor_lon, blat, blon) > max_miles:
        if not quiet:
            st.warning("Lake '" + query_body + "' only matched places far from your location - keeping your anchor point instead.")
        return None
    return (blat, blon)

@st.cache_data(ttl=600)
def fetch_cached_weather(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,cloud_cover,surface_pressure,wind_speed_10m&hourly=surface_pressure,precipitation,temperature_2m&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
        return requests.get(url, timeout=5).json()
    except Exception:
        return None

# =====================================================================
# 🗄️ DATABASE SYSTEM (SQLite Permanent Local Storage)
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

if "scouted_lakes_options" not in st.session_state:
    st.session_state.scouted_lakes_options = []
if "active_water_body" not in st.session_state:
    st.session_state.active_water_body = ""

# =====================================================================
# 🛰️ STEP 1: POSITION & LOCATION ROUTING MODULE
# =====================================================================
st.subheader("📡 Step 1: Destination Routing Mode")
routing_mode = st.radio(
    "Set your search anchor method:",
    options=["🛰️ Use My Live GPS Coordinates", "📍 Enter a Location / City / Water Body"],
    horizontal=True
)

# Clear stale lake selections when the routing mode changes, otherwise
# an old state's lake can linger and resolve far away (P0-2).
if "prev_routing_mode" not in st.session_state:
    st.session_state.prev_routing_mode = routing_mode
if st.session_state.prev_routing_mode != routing_mode:
    st.session_state.active_water_body = ""
    st.session_state.scouted_lakes_options = []
    st.session_state.prev_routing_mode = routing_mode

lat, lon, location_name, base_anchor_city = None, None, "", ""
detected_state = ""

if routing_mode == "🛰️ Use My Live GPS Coordinates":
    st.markdown("### 🛰️ Mobile Satellite Link")
    location_data = streamlit_geolocation()
    
    if location_data and location_data.get('latitude') is not None:
        lat = float(location_data['latitude'])
        lon = float(location_data['longitude'])
        
        geo_info = get_address_from_gps(lat, lon)
        city = geo_info['city']
        state = geo_info['state']
        
        detected_state = state if state else "Local Region"
        location_name = f"{city}, {state}" if state else city
        base_anchor_city = location_name
        
        st.session_state.geo_miss_streak = 0
        st.success(f"🎯 Locked Position: **{location_name}** ({lat:.4f}, {lon:.4f})")
    else:
        st.session_state.geo_miss_streak = st.session_state.get("geo_miss_streak", 0) + 1
        st.write("⏳ *Awaiting satellite link activation...*")
        if st.session_state.geo_miss_streak >= 3:
            st.warning("📡 GPS is not responding (this needs HTTPS + location permission). Try the text search mode instead.")

elif routing_mode == "📍 Enter a Location / City / Water Body":
    user_location = st.text_input("📍 Type a City, State, ZIP, or specific Water Body:", value="")
    
    if user_location.strip():
        base_anchor_city = user_location.strip()
        
        osm_res = get_coordinates_from_osm(user_location.strip())
        if osm_res:
            lat = float(osm_res[0]["lat"])
            lon = float(osm_res[0]["lon"])
            location_name = user_location.strip()
            st.session_state.active_water_body = user_location.strip()
            
            geo_info = get_address_from_gps(lat, lon)
            detected_state = geo_info['state'] if geo_info['state'] else "Local Region"
            st.success(f"🎯 Position Resolved: **{location_name}** ({lat:.4f}, {lon:.4f})")

input_state = detected_state

# =====================================================================
# 🎨 STEP 2, 3 & 4: CONFIGURATION MENUS
# =====================================================================
st.markdown("---")
config_col1, config_col2 = st.columns(2)

with config_col1:
    st.markdown("### 🌊 2. Environment")
    env_choice = st.segmented_control("System framework:", options=["Freshwater", "Saltwater (Marine)"], default="Freshwater", label_visibility="collapsed")

with config_col2:
    st.markdown("### 🗺️ 3. System Type")
    if env_choice == "Freshwater":
        fw_category = st.segmented_control("Water body type:", options=["🏞️ Rivers", "🏡 Lakes"], default="🏡 Lakes", label_visibility="collapsed")
    else:
        st.markdown(f"<p style='color: #22c55e; font-size: 14px; margin-top: 8px;'>⚓ Marine Management Active</p>", unsafe_allow_html=True)
        fw_category = "🏡 Lakes"

st.markdown("---")
st.markdown(f"### 🎣 4. Select Target Species ({input_state} Catalog)")

if input_state == "Washington":
    species_options = ["Crappie", "Rainbow Trout", "Largemouth Bass", "Smallmouth Bass", "Yellow Perch", "King Salmon (Chinook)", "Silver Salmon (Coho)", "Cutthroat Trout", "Walleye"] if env_choice == "Freshwater" else ["Resident Coho Salmon", "Blackmouth (Chinook)", "Puget Sound Surfperch", "Flounder", "Lingcod", "Halibut"]
elif input_state == "Oregon":
    species_options = ["Rainbow Trout", "Largemouth Bass", "Smallmouth Bass", "Crappie", "Yellow Perch", "Spring Chinook"] if env_choice == "Freshwater" else ["Ocean Chinook", "Ocean Coho", "Rockfish", "Lingcod", "Pacific Halibut"]
else:
    species_options = ["Largemouth Bass", "Smallmouth Bass", "Rainbow Trout", "Crappie", "Panfish/Bluegill", "Catfish"] if env_choice == "Freshwater" else ["Coastal Gamefish", "Inshore Sea Trout", "Striper", "Flounder"]

target_fish = st.pills("Choose target profile:", options=species_options, default=species_options[0] if species_options else "", label_visibility="collapsed", key=f"species_pills_{input_state}_{env_choice}")

# Switching environment invalidates the other environment's selections:
# clear scouted spots, the active water body, and any stale strategy output.
if st.session_state.get("last_env_choice") != env_choice:
    st.session_state["last_env_choice"] = env_choice
    st.session_state.scouted_lakes_options = []
    st.session_state.active_water_body = ""
    st.session_state.pop("current_raw_output", None)
    st.session_state.pop("scouted_lake_select", None)

# =====================================================================
# 🔍 PHASE 1 ENGINE: REGIONAL SCOUTING ENGINE
# =====================================================================
st.markdown("---")
# 🗺️ State-aware offline fallback lakes (used only if the AI scout call fails)
FALLBACK_LAKES_BY_STATE = {
    "Washington": ["Lake Washington", "Lake Sammamish", "Lake Tapps", "American Lake", "Lake Whatcom"],
    "Oregon": ["Hagg Lake", "Detroit Lake", "Timothy Lake", "Trillium Lake", "Wallowa Lake"],
    "California": ["Clear Lake", "Lake Berryessa", "Lake Shasta", "Diamond Valley Lake", "Lake Tahoe"],
    "Texas": ["Lake Fork", "Lake Travis", "Toledo Bend Reservoir", "Sam Rayburn Reservoir", "Lake Conroe"],
    "Pennsylvania": ["Raystown Lake", "Lake Wallenpaupack", "Pymatuning Reservoir", "Lake Nockamixon", "Blue Marsh Lake"],
}
DEFAULT_FALLBACK_LAKES = ["Lake Washington", "Clear Lake", "Lake Fork", "Raystown Lake", "Lake Tahoe"]

def get_fallback_lakes(state):
    """Return offline backup lakes for the detected state."""
    return FALLBACK_LAKES_BY_STATE.get(state, DEFAULT_FALLBACK_LAKES)

# Saltwater (marine) equivalents: public piers, jetties, and marine parks.
FALLBACK_PIERS_BY_STATE = {
    "Washington": ["Edmonds Fishing Pier", "Des Moines Fishing Pier", "Les Davis Pier", "Alki Beach Park", "Mukilteo Lighthouse Park"],
    "Oregon": ["Yaquina Bay South Jetty", "Tillamook Bay South Jetty", "Siuslaw River South Jetty", "Winchester Bay South Jetty", "Columbia River South Jetty"],
    "California": ["Santa Monica Pier", "Manhattan Beach Pier", "Redondo Beach Pier", "Huntington Beach Pier", "San Clemente Pier"],
    "Texas": ["Port Aransas South Jetty", "San Luis Pass", "Packery Channel", "Galveston Seawall", "Matagorda Beach"],
    "Pennsylvania": ["Presque Isle Bay", "Erie Harbor North Pier", "Walnut Creek Access", "Trout Run", "Godfrey Run"],
}
DEFAULT_FALLBACK_PIERS = ["Santa Monica Pier", "Edmonds Fishing Pier", "Huntington Beach Pier", "Port Aransas South Jetty", "Redondo Beach Pier"]

def get_fallback_piers(state):
    """Return offline backup saltwater access points for the detected state."""
    return FALLBACK_PIERS_BY_STATE.get(state, DEFAULT_FALLBACK_PIERS)

def get_offline_spots(state, env_choice):
    """Offline backup spots honoring the selected environment."""
    if env_choice == "Freshwater":
        return get_fallback_lakes(state)
    return get_fallback_piers(state)

@st.cache_data(ttl=1800, show_spinner=False)
def run_tactical_crew(target_fish, environment, current_state, water_temp, barometric_pressure, cloud_cover, wind_speed, water_clarity):
    # Builds the crew fresh on each uncached call and runs one kickoff.
    # Cached by inputs for 30 min so repeat taps do not re-burn Groq tokens.
    _crew = FishingAgentApp().crew()
    for _agent in _crew.agents:
        _agent.llm = production_llm
    if hasattr(_crew, 'tasks'):
        for _task in _crew.tasks:
            if hasattr(_task, 'agent') and _task.agent:
                _task.agent.llm = production_llm
    _res = _crew.kickoff(inputs={
        'target_fish': target_fish,
        'environment': environment,
        'current_state': current_state,
        'water_temp': water_temp,
        'barometric_pressure': barometric_pressure,
        'cloud_cover': cloud_cover,
        'wind_speed': wind_speed,
        'water_clarity': water_clarity,
    })
    return _res.raw if hasattr(_res, 'raw') else str(_res)

st.subheader("🔍 Phase 1: Scout Regional Hotspots (Optional)")
_is_saltwater = env_choice != "Freshwater"
st.info("Find top rated saltwater access points nearby, or proceed directly using your anchor location." if _is_saltwater else "Find top rated water bodies nearby, or proceed directly using your anchor location.")

anchor_ready = lat is not None and lon is not None
if not anchor_ready:
    st.caption("📍 Set your location above to enable scouting.")
if st.button("🔍 Scout Top 5 Saltwater Access Points" if _is_saltwater else "🔍 Scout Top 5 Local Water Bodies", type="secondary", use_container_width=True, disabled=not anchor_ready):
    search_anchor = base_anchor_city if base_anchor_city else f"{lat}, {lon}"
    target_species = target_fish if target_fish else "Gamefish"
    spot_kinds = "public saltwater fishing access points (fishing piers, jetties, marine parks, boat launches, or shoreline access)" if _is_saltwater else "public fishing spots (lakes, rivers, reservoirs, or access parks)"

    with st.spinner(f"🤖 Scanning regional {'saltwater access points' if _is_saltwater else 'water bodies'} near {search_anchor}..."):
        prompt = f"List exactly 5 real, specific, named {spot_kinds} within 50 miles of {search_anchor} for catching {target_species}. Output ONLY the 5 names, one per line. No introduction, no numbers, no bullet points, no extra text."
        
        try:
            api_url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key_fallback}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "openai/gpt-oss-20b",
                "messages": [
                    {"role": "system", "content": "You are a raw data generator. Output plain text lists only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 150
            }
            
            response = None
            for _attempt in range(3):
                response = requests.post(api_url, headers=headers, json=payload, timeout=15)
                if response.status_code != 429:
                    break
                time.sleep(2 ** _attempt * 2)  # 2s, 4s, 8s backoff on rate limits
            
            cleaned_list = []
            if response.status_code == 200:
                raw_text = response.json()['choices'][0]['message']['content'].strip()
                
                # Strip markdown code block wrappers
                raw_text = re.sub(r'```[a-zA-Z]*\n?', '', raw_text)
                raw_text = raw_text.replace('```', '')
                
                for line in raw_text.split("\n"):
                    # Aggressively strip leading numbers, bullets, markdown symbols
                    clean_line = re.sub(r'^[\d\*\-\•\.\#\_]+\s*', '', line).strip()
                    clean_line = clean_line.replace('*', '').replace('_', '').strip()
                    
                    if clean_line and len(clean_line) > 2:
                        lower_line = clean_line.lower()
                        # Skip conversational filler sentences
                        if not any(p in lower_line for p in ["here are", "sure", "following", "locations", "spots", "fishing spots", "radius"]):
                            cleaned_list.append(clean_line)
                            
                # Fallback to any non-empty lines if strict filter caught everything
                if not cleaned_list:
                    cleaned_list = [re.sub(r'^[\d\*\-\•\.\#\_]+\s*', '', l).strip() for l in raw_text.split("\n") if l.strip()]

            # Guaranteed fallback list so it never fails to populate your dropdown
            if not cleaned_list:
                cleaned_list = get_offline_spots(detected_state, env_choice)

            # Drop anything that does not actually resolve near the anchor;
            # the LLM's 'within 50 miles' is never validated otherwise.
            nearby = []
            for _name in cleaned_list[:5]:
                if resolve_lake_location(_name, lat, lon, detected_state, quiet=True):
                    nearby.append(_name)
            if nearby and len(nearby) < len(cleaned_list[:5]):
                st.warning(f"⚠️ Dropped {len(cleaned_list[:5]) - len(nearby)} scouted spot(s) that were not near your location.")
                cleaned_list = nearby

            st.session_state.scouted_lakes_options = cleaned_list[:5]
            st.success("🎯 Scouted 5 regional target locations!")
                
        except Exception as e:
            # Fallback on network exception so the app keeps moving
            st.session_state.scouted_lakes_options = get_offline_spots(detected_state, env_choice)
            st.success("🎯 Scouted 5 regional target locations (Offline Backup)!")

if st.session_state.scouted_lakes_options:
    selected_suggested = st.selectbox(
        "🎯 Select a scouted hotspot to refine your target (optional):",
        options=["(Use Main Anchor Location)"] + st.session_state.scouted_lakes_options,
        index=0,
        key="scouted_lake_select",
    )
    if selected_suggested and selected_suggested != "(Use Main Anchor Location)":
        st.session_state.active_water_body = selected_suggested

active_water_body = st.session_state.active_water_body if st.session_state.active_water_body else location_name

if active_water_body and active_water_body != location_name:
    try:
        display_name = active_water_body.strip()
        query_body = display_name
        if input_state == "Washington":
            if re.search(r"kapow", query_body, re.IGNORECASE):
                query_body = "Lake Kapowsin"
            elif re.search(r"ohop", query_body, re.IGNORECASE):
                query_body = "Lake Ohop"
        if env_choice == "Freshwater" and fw_category == "🏡 Lakes" and not re.search(r"\b(lake|river|reservoir|creek|pond|park|bay)\b", query_body, re.IGNORECASE):
            query_body = f"Lake {query_body}"

        # Proximity-ranked resolution: state match first, then distance.
        # Never silently accepts a far-away guess.
        resolved = resolve_lake_location(query_body, lat, lon, input_state)
        if resolved:
            lat, lon = resolved
            active_water_body = display_name
        else:
            st.warning("Could not pin down '" + display_name + "' on the map - showing your anchor location instead.")
    except Exception:
        pass

# =====================================================================
# 📋 STEP 4.5: MICRO-TARGETING SURVEY FACTORS
# =====================================================================
water_clarity, cover_type, spawn_phase, fishing_style = None, None, None, None
if lat and lon:
    st.markdown("---")
    st.markdown("### 🛠️ Step 4.5: Micro-Targeting Survey Factors")
    with st.expander("🔬 Fine-Tune Algorithmic Factor Controls", expanded=True):
        s_col1, s_col2 = st.columns(2)
        with s_col1:
            water_clarity = st.radio("💧 Current Water Clarity Observation:", options=["🤖 Let AI Agents Decide", "Clear Water Visibility", "Slightly Stained / Milky", "Stained / Muddy Runoff"], horizontal=True)
            _cover_options = ["🤖 Let AI Agents Decide", "Pier Pilings & Structure", "Rocky Jetty & Riprap", "Sandy Beach Troughs", "Kelp Beds & Eelgrass"] if env_choice != "Freshwater" else ["🤖 Let AI Agents Decide", "Submerged Timber/Logs", "Heavy Vegetation/Lily Pads", "Rocky Drop-offs & Riprap", "Docks & Structural Pilings"]
            cover_type = st.radio("🌿 Dominant Visible Structure/Cover:", options=_cover_options, horizontal=True)
        with s_col2:
            spawn_phase = st.radio("🐟 Lifecycle Breeding Target Stage:", options=["🤖 Let AI Agents Decide", "Deep Winter Staging", "Pre-Spawn Staging Flocks", "Shallow Spawning Beds", "Summer Post-Spawn Patterns"], horizontal=True)
            fishing_style = st.radio("👟 Mobility / Angler Framework:", options=["🤖 Let AI Agents Decide", "Foot / Shoreline Angler", "Power Boat / Deep Hull", "Kayak / Stealth Shallow"], horizontal=True)

# =====================================================================
# 🚀 STEP 5: RUN COMPILATION ENGINE & RENDER DASHBOARD UI (3 TABS)
# =====================================================================
if lat and lon:
    st.markdown("---")
    st.subheader("⚡ Step 5: Dashboard & Strategy Analysis")
    execute_crew = st.button("🚀 Generate Tactical Strategy Plan", type="primary", use_container_width=True)

    try:
        weather = fetch_cached_weather(lat, lon)
        if not weather or 'current' not in weather:
            current = {'temperature_2m': 68.0, 'cloud_cover': 40, 'surface_pressure': 1013.25, 'wind_speed_10m': 6.0}
            trend, cloud_word, clarity_estimate = "Stable", "Partially Cloudy", "Clear Water Visibility"
            estimated_water_temp, current_air_temp = 64.0, 68.0
        else:
            current = weather['current']
            diff = current['surface_pressure'] - weather['hourly']['surface_pressure'][-3]
            trend = "Rising rapidly" if diff > 0.05 else "Rising slowly" if diff > 0.01 else "Falling rapidly" if diff < -0.05 else "Falling slowly" if diff < -0.01 else "Stable"
            cloud_word = "Clear/Sunny" if current['cloud_cover'] < 20 else "Partially Cloudy" if current['cloud_cover'] < 60 else "Overcast"
            recent_rain = sum(weather['hourly'].get('precipitation', [0.0])[-12:])
            clarity_estimate = water_clarity if water_clarity and water_clarity != "🤖 Let AI Agents Decide" else ("Stained / Muddy Runoff" if (recent_rain > 0.50 or current['wind_speed_10m'] > 15) else "Slightly Stained / Milky" if recent_rain > 0.15 else "Clear Water Visibility")
            estimated_water_temp = (0.7 * (sum(weather['hourly']['temperature_2m'][:72]) / 72)) + (0.3 * current['temperature_2m'])
            current_air_temp = current['temperature_2m']

        agency_name = "TPWD" if detected_state == "Texas" else "ODFW" if detected_state == "Oregon" else "PFBC" if detected_state == "Pennsylvania" else "WDFW" if detected_state == "Washington" else f"{detected_state} Wildlife"
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

        bite_score = max(10, min(100, 50 + (20 if "Rising" in trend else 10 if "Stable" in trend else -15) + (15 if "Cloudy" in cloud_word or "Overcast" in cloud_word else 0) + (15 if current['wind_speed_10m'] < 10 else -20 if current['wind_speed_10m'] > 18 else 0)))
        card_border, score_color, rating_text = ("#22c55e", "#22c55e", "🏆 EXCELLENT CONDITIONS") if bite_score >= 75 else ("#eab308", "#eab308", "🟡 FAIR CONDITIONS") if bite_score >= 45 else ("#ef4444", "#ef4444", "🚨 TOUGH BITE WINDOW")

        major_start = "5:30 AM" if "Rising" in trend else "6:15 AM" if "Stable" in trend else "7:00 AM"
        major_end = "7:30 AM" if "Rising" in trend else "8:15 AM" if "Stable" in trend else "8:30 AM"
        minor_start = "4:30 PM" if current['cloud_cover'] > 50 else "6:00 PM"
        minor_end = "6:00 PM" if current['cloud_cover'] > 50 else "7:30 PM"
        bite_windows_text = f"🟢 **Major Peak:** {major_start} - {major_end} | 🟡 **Minor Window:** {minor_start} - {minor_end}"

        st.markdown(f"""
            <style>
                .bite-card {{ background-color: #1e293b; border-radius: 12px; padding: 20px; border-left: 6px solid {card_border}; margin-bottom: 20px; }}
                .bite-score {{ font-size: 32px; font-weight: bold; color: {score_color}; }}
                .window-text {{ color: #e2e8f0; font-size: 16px; margin-top: 10px; font-family: sans-serif; }}
            </style>
            <div class="bite-card">
                <span style="color: #94a3b8; font-size: 14px; font-weight: bold;">Live Tactical Analytics ({active_water_body})</span>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 5px;">
                    <div class="bite-score">{bite_score}%</div>
                    <div style="font-weight: bold; color: {score_color};">{rating_text}</div>
                </div>
                <div class="window-text">⏱️ {bite_windows_text}</div>
            </div>
        """, unsafe_allow_html=True)

        tab_strat, tab_telemetry, tab_maps = st.tabs(["🎣 Fishing Strategy", "🌦️ Weather & Stats", "🗺️ Maps"])

        # TAB 1: FISHING STRATEGY
        with tab_strat:
            if execute_crew:
                with st.spinner("🤖 Formulating tactical operations..."):
                    selected_clarity = "dynamically determine water clarity based on recent rain/wind telemetry" if water_clarity == "🤖 Let AI Agents Decide" else water_clarity
                    selected_cover = "predict high-probability structure zones for this water body type" if cover_type == "🤖 Let AI Agents Decide" else f"focus around {cover_type}"
                    selected_spawn = f"automatically calculate the exact biological lifecycle phase for {target_fish} using the current month ({datetime.now().strftime('%B')}), location climate, and water temperature vectors" if spawn_phase == "🤖 Let AI Agents Decide" else f"utilize the {spawn_phase} lifecycle framework"
                    selected_style = "provide general tactical approaches for both shore and watercraft setups" if fishing_style == "🤖 Let AI Agents Decide" else f"tailored for a {fishing_style} approach pattern"

                    water_context = f"the area or water body named {active_water_body} in {detected_state}."
                    env_label = "saltwater (marine)" if env_choice != "Freshwater" else "freshwater"
                    
                    # Free-tier friendly: the 3-agent crew can exceed Groq's
                    # 8k TPM free limit in one kickoff. On a 429, wait out the
                    # token window and retry instead of surfacing the error.
                    _crew_inputs = {
                        'target_fish': target_fish,
                        'environment': f"{env_label} environment at {water_context} holding active targets. Your primary directive is to {selected_spawn}, optimize hot spots targeting areas to {selected_cover} under a setting of {selected_style}.",
                        'current_state': detected_state,
                        'water_temp': f"{estimated_water_temp:.1f}°F",
                        'barometric_pressure': trend,
                        'cloud_cover': cloud_word,
                        'wind_speed': f"{current['wind_speed_10m']} mph",
                        'water_clarity': selected_clarity,
                    }
                    _plan_text = None
                    _plan_error = None
                    for _attempt in range(2):
                        try:
                            _plan_text = run_tactical_crew(**_crew_inputs)
                            _plan_error = None
                            break
                        except Exception as _e:
                            _plan_error = _e
                            _msg = str(_e)
                            _flat = _msg.lower().replace(" ", "").replace("_", "")
                            _is_rl = "ratelimit" in _flat or "rate limit" in _msg.lower()
                            if _is_rl and _attempt == 0:
                                # One deliberate retry after the TPM window clears.
                                # Retrying sooner just burns budget and guarantees another 429.
                                _m = re.search(r"try again in ([\d.]+)s", _msg)
                                _wait = min(max((float(_m.group(1)) + 10) if _m else 70, 70), 95)
                                st.info(f"\u23f3 Groq free tier is at its token limit \u2014 waiting ~{int(_wait)}s for it to reset, then retrying once...")
                                time.sleep(_wait)
                                continue
                            break
                    if _plan_text:
                        st.session_state.current_raw_output = _plan_text
                    elif _plan_error:
                        _emsg = str(_plan_error)
                        _eflat = _emsg.lower().replace(" ", "").replace("_", "")
                        if "ratelimit" in _eflat or "rate limit" in _emsg.lower():
                            st.warning("⏳ Groq\u2019s free tier is still at its token limit. Wait a minute or two, then tap **Generate** again \u2014 your settings are saved.")
                        else:
                            st.error(f"Strategy generation failed: {_plan_error}")
                    
            if "current_raw_output" in st.session_state:
                st.markdown(st.session_state.current_raw_output.split("### 🎣 Tactical Strategy Plan")[1].strip() if "### 🎣 Tactical Strategy Plan" in st.session_state.current_raw_output else st.session_state.current_raw_output)
            else:
                st.info("👈 Click **'🚀 Generate Tactical Strategy Plan'** above to run AI tactical analysis for this location.")

        # TAB 2: WEATHER & STATS
        with tab_telemetry:
            st.caption(f"🗺️ Fixed Anchor: {lat:.4f}, {lon:.4f} | Target Context: {active_water_body}")
            w_col1, w_col2, w_col3, w_col4 = st.columns(4)
            w_col1.metric("🌡️ Water Temp", f"{estimated_water_temp:.1f}°F")
            w_col2.metric("🌤️ Air Temp", f"{current_air_temp:.1f}°F")
            w_col3.metric("💨 Wind", f"{current['wind_speed_10m']} mph")
            w_col4.metric("☁️ Sky", cloud_word)
            
            st.markdown("---")
            st.markdown("### 🌊 Real-Time Water Gauges")
            st.info(live_gauge_data)
            
            st.markdown("---")
            st.markdown(f"### 🚨 Legal Compliance ({detected_state})")
            regulation_links = {"Washington": "https://wdfw.wa.gov/fishing/regulations", "Oregon": "https://myodfw.com/fishing/regulations", "Texas": "https://tpwd.texas.gov/regulations/outdoor-annual/fishing/", "Pennsylvania": "https://www.fishandboat.com/Fish/Regulations/Pages/default.aspx"}
            pamphlet_url = regulation_links.get(detected_state, "https://www.eregulations.com/")
            st.link_button(f"📖 Open Official {detected_state} Fishing Pamphlet", pamphlet_url, type="secondary")

        # TAB 3: MAPS (GOOGLE HYBRID SATELLITE ENGINE & IN-APP SQLITE LOGGING)
        with tab_maps:
            st.markdown(f"### 🛰️ Interactive Structural Grid: {active_water_body}")
            st.caption("💡 **Tip:** Tap anywhere on the map below to capture the spot and log a new catch!")
            
            if "map_view" not in st.session_state or st.session_state.get("last_water_body") != active_water_body:
                st.session_state.map_view = {"center": [lat, lon], "zoom": 14}
                st.session_state.last_water_body = active_water_body
            # NOTE: do NOT reset map_view["center"] here on every rerun.
            # Doing so snaps the map back to the anchor whenever the script
            # re-executes, fighting the user's pan/zoom gestures.

            # USGS National Map layers: free, no key, public domain.
            # NOTE: ArcGIS REST endpoints use {z}/{y}/{x} order - do not 'fix'.
            m = folium.Map(
                location=st.session_state.map_view["center"], 
                zoom_start=st.session_state.map_view["zoom"],
                tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}",
                attr="USGS The National Map",
                name="USGS Imagery + Topo"
            )

            folium.TileLayer(
                tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
                attr="USGS The National Map",
                name="USGS Topo (National Map)",
                overlay=False,
                control=True,
                max_zoom=16
            ).add_to(m)

            folium.TileLayer(
                tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                attr="Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
                name="OpenTopoMap",
                overlay=False,
                control=True,
                max_zoom=17
            ).add_to(m)

            folium.TileLayer(
                tiles="OpenStreetMap",
                name="Standard Navigation Roadmap",
                overlay=False,
                control=True
            ).add_to(m)

            folium.Marker(
                location=[lat, lon],
                popup=f"🎯 Target Zone: {active_water_body}",
                icon=folium.Icon(color='red', icon='crosshairs', prefix='fa')
            ).add_to(m)

            try:
                conn = sqlite3.connect(DB_FILE)
                saved_catches = pd.read_sql_query("SELECT * FROM catch_log", conn)
                conn.close()
                for _, row in saved_catches.iterrows():
                    notes_display = f"<br>📝 <i>{row['substrate']}</i>" if 'substrate' in row and row['substrate'] else ""
                    folium.Marker(
                        location=[row['latitude'], row['longitude']],
                        popup=f"🎣 <b>{row['species']}</b> ({row['weight']} lbs)<br>📅 {row['timestamp']}{notes_display}",
                        icon=folium.Icon(color='blue', icon='fish', prefix='fa')
                    ).add_to(m)
            except Exception:
                saved_catches = pd.DataFrame()

            folium.LayerControl(position="topright", collapsed=True).add_to(m)
            m.add_child(folium.LatLngPopup())

            map_data = st_folium(
                m,
                use_container_width=True,
                height=450,
                # Constant key: st_folium hashes the map content itself, so a
                # float-based key only triggers spurious full remounts (tile
                # reload + view reset) when GPS coords jitter between runs.
                key="structural_grid",
                returned_objects=["last_clicked"]
            )

            last_click = map_data.get("last_clicked") if map_data else None
            
            if last_click:
                clicked_lat = last_click["lat"]
                clicked_lon = last_click["lng"]
                
                st.markdown("---")
                st.success(f"📍 **Map Spot Captured!** ({clicked_lat:.4f}, {clicked_lon:.4f})")
                
                with st.form("log_catch_form", clear_on_submit=True):
                    st.markdown("#### 📝 Log Your Catch Details")
                    
                    c_col1, c_col2 = st.columns(2)
                    with c_col1:
                        log_date = st.date_input("📅 Date Captured", value=datetime.today())
                        log_time = st.time_input("⏰ Time Captured", value=datetime.now().time())
                        log_species = st.text_input("🐟 Fish Species", value=target_fish if target_fish else "Crappie")
                    
                    with c_col2:
                        log_weight = st.number_input("⚖️ Weight (lbs)", min_value=0.0, max_value=200.0, value=1.5, step=0.1)
                        log_notes = st.text_area("📝 Tactical Notes / Lure Used", placeholder="e.g. 1/16oz jig along submerged logs, slow retrieve...")

                    submit_catch = st.form_submit_button("💾 Save Waypoint to Local Database", type="primary", use_container_width=True)
                    
                    if submit_catch:
                        formatted_dt = f"{log_date.strftime('%Y-%m-%d')} {log_time.strftime('%I:%M %p')}"
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO catch_log (timestamp, lake_name, species, weight, latitude, longitude, substrate)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (formatted_dt, active_water_body, log_species, log_weight, clicked_lat, clicked_lon, log_notes))
                        conn.commit()
                        conn.close()
                        st.toast("🎉 Catch logged to local SQLite database! Refreshing map pins...", icon="🎣")
                        st.rerun()

            st.markdown("---")
            b_col1, b_col2 = st.columns(2)
            
            with b_col1:
                clean_lake_name = active_water_body.replace("Lake", "").strip()
                url_encoded_title = urllib.parse.quote(f"{clean_lake_name} Fishing Chart")
                universal_chart_url = f"https://fishing-app.gpsnauticalcharts.com/i-boating-fishing-web-app/fishing-marine-charts-navigation.html?title={url_encoded_title}&background=satellite&bmi=3#13.5/{lat:.4f}/{lon:.4f}"
                st.link_button(f"🌊 Open {clean_lake_name} HD Depth Chart (i-Boating)", universal_chart_url, use_container_width=True, type="primary")

            with b_col2:
                try:
                    conn = sqlite3.connect(DB_FILE)
                    export_df = pd.read_sql_query("SELECT * FROM catch_log", conn)
                    conn.close()
                    if not export_df.empty:
                        csv_data = export_df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Download Database Copy to Phone (.CSV)",
                            data=csv_data,
                            file_name=f"my_fishing_log_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                except Exception:
                    pass

    except Exception as err: 
        st.error(f"Telemetry stream parsing failed: {err}")
