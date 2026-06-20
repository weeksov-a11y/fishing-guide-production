#!/usr/bin/env python
import sys
import os
import streamlit as st

# Fix the path to look inside 'src'
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# 🛠️ Securely fetch the key from Streamlit's private backend cloud settings
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

# 🪝 THE ULTIMATE MONKEY PATCH: Strip cache keys right before the API call
import litellm
original_completion = litellm.completion

def clean_groq_completion(*args, **kwargs):
    if "messages" in kwargs:
        for msg in kwargs["messages"]:
            if isinstance(msg, dict):
                # Rip out the exact property Groq is failing on
                msg.pop("cache_breakpoint", None)
    return original_completion(*args, **kwargs)

# Swap LiteLLM's method with our clean version
litellm.completion = clean_groq_completion

from fishing_agent_app.crew import FishingAgentApp

def run():
    """
    Run the fishing advisory crew with today's local conditions.
    """
    inputs = {
        'target_fish': 'Crappie',
        'water_temp': '62°F',      
        'barometric_pressure': 'Falling rapidly', 
        'cloud_cover': 'Overcast',
        'wind_speed': '8 mph',
        'water_clarity': 'Slightly stained'
    }
    
    print("\n--- Gathering your PNW Fishing Crew... ---\n")
    FishingAgentApp().crew().kickoff(inputs=inputs)

if __name__ == "__main__":
    run()