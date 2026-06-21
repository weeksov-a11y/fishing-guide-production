from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
import os
import streamlit as st

# Check for keys in Streamlit secrets
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

# 🧠 Swapping out Groq for the massive free-tier limits of Gemini 2.5 Flash
gemini_llm = LLM(
    model="gemini/gemini-2.5-flash",
    temperature=0.7
)

@CrewBase
class FishingAgentApp():
    """FishingAgentApp crew for analyzing conditions, checking regional rules, and prescribing gear"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def weather_analyst(self) -> Agent:
        tgt_agent = Agent(
            config=self.agents_config['weather_analyst'],
            llm=gemini_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @agent
    def wdfw_compliance_officer(self) -> Agent:
        tgt_agent = Agent(
            config=self.agents_config['wdfw_compliance_officer'],
            llm=gemini_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @agent
    def lure_specialist(self) -> Agent:
        tgt_agent = Agent(
            config=self.agents_config['lure_specialist'],
            llm=gemini_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @task
    def analyze_weather_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_weather_task'],
            agent=self.weather_analyst()
        )

    @task
    def check_regulations_task(self) -> Task:
        return Task(
            config=self.tasks_config['check_regulations_task'],
            agent=self.wdfw_compliance_officer()
        )

    @task
    def prescribe_lures_task(self) -> Task:
        return Task(
            config=self.tasks_config['prescribe_lures_task'],
            agent=self.lure_specialist()
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents, 
            tasks=self.tasks, 
            process=Process.sequential,
            verbose=True,
            prompt_caching=False
        )
