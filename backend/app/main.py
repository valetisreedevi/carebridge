import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    agent,
    caregivers,
    elders,
    internal,
    medications,
    pairing,
    reminders,
    speech,
)
from app.config import get_settings
from app.models.medication_event import InvalidTransition
from app.services.reminder_service import NoSuchDose

logging.basicConfig(level=logging.INFO)

settings = get_settings()

app = FastAPI(
    title="CareBridge API",
    description="AI medication companion for elderly care",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(elders.router)
app.include_router(caregivers.router)
app.include_router(medications.router)
app.include_router(pairing.router)
app.include_router(reminders.router)
app.include_router(agent.router)
app.include_router(speech.router)
app.include_router(internal.router)


@app.exception_handler(InvalidTransition)
def invalid_transition_handler(request: Request, exc: InvalidTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(NoSuchDose)
def no_such_dose_handler(request: Request, exc: NoSuchDose):
    """A refusal the caregiver can act on, not a server error."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "carebridge-api",
        "project": settings.gcp_project_id,
        "auth_enabled": settings.auth_enabled,
        "model": settings.gemini_model,
    }
