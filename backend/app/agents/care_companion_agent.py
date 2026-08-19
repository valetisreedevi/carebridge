from google.adk.agents import Agent

from app.agents.prompts import CARE_COMPANION_INSTRUCTION
from app.config import get_settings
from app.tools.medication_tools import ALL_TOOLS

root_agent = Agent(
    name="care_companion_agent",
    model=get_settings().gemini_model,
    description="Speaks with an elder about a medication reminder.",
    instruction=CARE_COMPANION_INSTRUCTION,
    tools=ALL_TOOLS,
)
