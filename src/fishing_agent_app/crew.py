from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
import os
import streamlit as st

# 🛠️ Securely fetch the key from Streamlit's private backend cloud settings
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

# 🧠 Configure a base LLM object cleanly omitting default caching flags
groq_llm = LLM(
    model="groq/llama-3.1-8b-instant",
    temperature=0.7
)

@CrewBase
class FishingAgentApp():
    """FishingAgentApp crew for analyzing conditions, checking WDFW rules, and prescribing gear"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def weather_analyst(self) -> Agent:
        tgt_agent = Agent(
            config=self.agents_config['weather_analyst'],
            llm=groq_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @agent
    def wdfw_compliance_officer(self) -> Agent:
        """💡 Added: The Fishery Regulations & Catch Limits Guardrail Agent"""
        tgt_agent = Agent(
            config=self.agents_config['wdfw_compliance_officer'],
            llm=groq_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @agent
    def lure_specialist(self) -> Agent:
        tgt_agent = Agent(
            config=self.agents_config['lure_specialist'],
            llm=groq_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @task
    def analyze_weather_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_weather_task'],
        )

    @task
    def check_regulations_task(self) -> Task:
        """💡 Added: The Compliance Check Task"""
        return Task(
            config=self.tasks_config['check_regulations_task'],
        )

    @task
    def prescribe_lures_task(self) -> Task:
        return Task(
            config=self.tasks_config['prescribe_lures_task'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the fishing advice crew pipeline"""
        return Crew(
            agents=self.agents, 
            tasks=self.tasks, 
            process=Process.sequential,
            verbose=True,
            prompt_caching=False
        )