"""Agent construction via langchain.agents.create_agent (the current, non-deprecated
LangChain agent API; create_react_agent is deprecated in LangGraph v1) with an
AsyncSqliteSaver checkpointer for multi-turn memory."""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings
from app.prompts import SYSTEM_PROMPT
from app.tools.get_actuator import get_actuator_by_part_number
from app.tools.recommend import recommend_actuators


def build_agent(memory: AsyncSqliteSaver, prompt: str = SYSTEM_PROMPT):
    # prompt is overridable so the eval harness can A/B prompt variants; defaults to production.
    llm = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=30,
        max_retries=2,
    )
    tools = [get_actuator_by_part_number, recommend_actuators]
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=prompt,
        checkpointer=memory,
    )
