from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
import os
import streamlit as st
import time  # 💡 Added for the rate limit breathing room

if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["CREWAI_DISABLE_PROMPT_CACHING"] = "true"

groq_llm = LLM(
    model="groq/llama-3.1-8b-instant",
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
            llm=groq_llm,
            verbose=True
        )
        if hasattr(tgt_agent, 'cache_prompt'):
            tgt_agent.cache_prompt = False
        return tgt_agent

    @agent
    def wdfw_compliance_officer(self) -> Agent:
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
            agent=self.weather_analyst()
        )

    @task
    def check_regulations_task(self) -> Task:
        # 💡 Force a quick pause before the compliance officer calls Groq to clear the TPM rate limit window
        time.sleep(2) 
        return Task(
            config=self.tasks_config['check_regulations_task'],
            agent=self.wdfw_compliance_officer()
        )

    @task
    def prescribe_lures_task(self) -> Task:
        # 💡 Force a quick pause before the lure specialist calls Groq to clear the TPM rate limit window
        time.sleep(2)
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
