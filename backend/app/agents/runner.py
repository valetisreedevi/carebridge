import logging
from functools import lru_cache

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.care_companion_agent import root_agent
from app.services.conversation_service import ConversationService
from app.tools.medication_tools import AgentContext, set_context

logger = logging.getLogger(__name__)

APP_NAME = "carebridge"


@lru_cache
def get_runner() -> Runner:
    return Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=InMemorySessionService(),
    )


class AgentService:
    """Bridges an HTTP turn to one ADK invocation."""

    def __init__(self):
        self.runner = get_runner()
        self.conversations = ConversationService()

    async def _ensure_session(self, user_id: str, session_id: str) -> None:
        service = self.runner.session_service
        existing = await service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if existing is None:
            await service.create_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )

    async def chat(
        self,
        elder_id: str,
        event_id: str | None,
        message: str,
    ) -> dict:
        # Tools read the elder and event from here, never from model arguments.
        set_context(AgentContext(elder_id=elder_id, event_id=event_id))

        session_id = self.conversations.get_or_create_session(elder_id, event_id)
        await self._ensure_session(elder_id, session_id)

        self.conversations.add_message(session_id, "elder", message)

        reply_parts: list[str] = []
        tool_calls: list[str] = []

        async for event in self.runner.run_async(
            user_id=elder_id,
            session_id=session_id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=message)]
            ),
        ):
            content = getattr(event, "content", None)
            if not content or not content.parts:
                continue

            for part in content.parts:
                if getattr(part, "function_call", None):
                    tool_calls.append(part.function_call.name)
                elif getattr(part, "text", None) and event.author != "user":
                    reply_parts.append(part.text)

        reply = "".join(reply_parts).strip()

        self.conversations.add_message(
            session_id, "agent", reply, tool_calls=tool_calls
        )

        return {
            "reply": reply,
            "tool_calls": tool_calls,
            "session_id": session_id,
            "event_id": event_id,
        }
