"""Runs the analyst agent, and is prepared for it never to answer.

Every caller here already has something to show. The deterministic sentence is
written, the alert is sent, the figures are on the screen. Narration only ever
replaces wording with better wording, so every failure path returns None and
the caller keeps what it had.

Nothing in this file is allowed to make a caregiver wait. The timeout is hard,
the exception handling is total, and the one channel that uses it is the slow
one that runs five minutes after the fast one has already gone out.
"""

import asyncio
import json
import logging

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.adherence_analyst_agent import build_analyst
from app.config import get_settings

logger = logging.getLogger(__name__)

APP_NAME = "carebridge-analyst"

ESCALATION_TASK = """
Write the note a family member receives when a dose has gone unanswered and
CareBridge has given up waiting.

Say what happened, how many times it tried, and whether this dose has been
going wrong lately. If the brief says the phone was never reached, that is the
story - say the reminder never arrived and the phone needs checking, and do not
imply anything about whether the medicine was taken.

BRIEF:
{brief}
""".strip()

WEEKLY_TASK = """
Write the short weekly note a family member reads to answer "how is she doing".

Lead with what changed, using what_changed. If what_changed is empty, say the
week looked much like the ones before it. Mention the wait time only if it
appears in what_changed - a normal wait is not news.

BRIEF:
{brief}
""".strip()

TASKS = {"escalation": ESCALATION_TASK, "weekly": WEEKLY_TASK}


def _json(brief: dict) -> str:
    return json.dumps(brief, indent=2, default=str, ensure_ascii=False)


class NarrationService:

    def __init__(self, runner: Runner | None = None):
        self._runner = runner

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(
                app_name=APP_NAME,
                agent=build_analyst(),
                session_service=InMemorySessionService(),
            )
        return self._runner

    async def narrate(self, kind: str, brief: dict, key: str) -> str | None:
        """Returns better wording, or None. Never raises, never blocks forever.

        `key` names the session so a retry for the same dose or week reuses one
        rather than accumulating them.
        """
        settings = get_settings()
        if not settings.analyst_enabled:
            return None

        try:
            return await asyncio.wait_for(
                self._run(kind, brief, key),
                timeout=settings.analyst_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.info(
                "Analyst took longer than %ss for %s; keeping the plain wording",
                settings.analyst_timeout_seconds,
                key,
            )
        except Exception as exc:
            logger.warning("Analyst narration failed for %s: %s", key, exc)

        return None

    async def _run(self, kind: str, brief: dict, key: str) -> str | None:
        session_id = f"{kind}_{key}"
        service = self.runner.session_service

        existing = await service.get_session(
            app_name=APP_NAME, user_id=kind, session_id=session_id
        )
        if existing is None:
            await service.create_session(
                app_name=APP_NAME, user_id=kind, session_id=session_id
            )

        message = TASKS[kind].format(brief=_json(brief))

        parts: list[str] = []
        async for event in self.runner.run_async(
            user_id=kind,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            content = getattr(event, "content", None)
            if not content or not content.parts:
                continue
            for part in content.parts:
                if getattr(part, "text", None) and event.author != "user":
                    parts.append(part.text)

        return "".join(parts).strip() or None

    def narrate_blocking(self, kind: str, brief: dict, key: str) -> str | None:
        """For the worker, which is synchronous.

        Cloud Run serves sync endpoints on a threadpool, so there is no running
        loop here to conflict with. If that ever stops being true this returns
        None rather than deadlocking, which is the same as the analyst being
        unavailable — a case every caller already handles.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.narrate(kind, brief, key))

        logger.warning("Narration skipped: already inside an event loop")
        return None
