import logging

from fastapi import APIRouter, Depends, HTTPException

from app.agents.runner import AgentService
from app.api.auth import current_elder_id
from app.api import deps
from app.api.schemas import AgentChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
async def chat(
    request: AgentChatRequest,
    elder_id: str = Depends(current_elder_id),
):
    """One conversational turn with the elder.

    The elder id comes from the caller's credentials, never from the body, and
    the event is checked against it before the model sees anything.
    """
    if request.elder_id != elder_id:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this elder",
        )

    if not deps.firestore_service().get_elder(elder_id):
        raise HTTPException(status_code=404, detail="Elder not found")

    event_id = request.event_id
    if event_id:
        event = deps.event_service().get_event(event_id)
        if not event or event["elder_id"] != elder_id:
            raise HTTPException(status_code=404, detail="Reminder not found")
    else:
        active = deps.event_service().get_active_event_for_elder(elder_id)
        event_id = active["id"] if active else None

    result = await AgentService().chat(
        elder_id=elder_id,
        event_id=event_id,
        message=request.message,
    )

    # The client re-reads state from the backend rather than trusting the
    # model's account of what happened.
    if event_id:
        event = deps.event_service().get_event(event_id)
        result["event_status"] = event["status"] if event else None

    return result


@router.get("/conversations/{session_id}")
def get_conversation(
    session_id: str,
    elder_id: str = Depends(current_elder_id),
):
    if not session_id.startswith(f"{elder_id}_"):
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "session_id": session_id,
        "messages": deps.conversation_service().get_messages(session_id),
    }
