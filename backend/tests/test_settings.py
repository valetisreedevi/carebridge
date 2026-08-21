import pytest

from app.config.settings import DEV_WORKER_TOKEN, Settings


def test_worker_token_from_env_is_trimmed(monkeypatch):
    """The trimming must survive pydantic-settings reading the environment.

    A stripped default does not work here: BaseSettings populates the field
    straight from WORKER_TOKEN and overwrites whatever default was computed,
    which is how a trailing newline reached the comparison in production and
    silently stopped every scheduled reminder.
    """
    monkeypatch.setenv("WORKER_TOKEN", "secret-value\r\n")

    assert Settings().worker_token == "secret-value"


def test_worker_token_survives_a_bare_carriage_return(monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", "secret-value\r")

    assert Settings().worker_token == "secret-value"


def test_worker_token_without_whitespace_is_unchanged(monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", "secret-value")

    assert Settings().worker_token == "secret-value"


def test_cors_origins_accept_a_delimited_string(monkeypatch):
    """A list-typed field would be JSON-parsed at the env-source layer.

    That happens before validators run, so a plain delimited string would stop
    the app from starting rather than fall back to something sensible.
    Semicolons are supported because gcloud --set-env-vars claims the comma.
    """
    monkeypatch.setenv(
        "CORS_ORIGINS_RAW", "https://web.run.app;http://localhost:5173"
    )

    assert Settings().cors_origins == [
        "https://web.run.app",
        "http://localhost:5173",
    ]


def test_cors_origins_default_covers_local_development(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS_RAW", raising=False)

    assert "http://localhost:5173" in Settings().cors_origins


def test_the_placeholder_worker_token_is_fine_locally(monkeypatch):
    """Local runs and demos have no Secret Manager and need none."""
    monkeypatch.delenv("WORKER_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "false")

    assert Settings().worker_token == DEV_WORKER_TOKEN


def test_the_placeholder_worker_token_refuses_to_deploy(monkeypatch):
    """Guarding the worker endpoint with a string published in this repository
    is not a configuration mistake that should produce a healthy service."""
    monkeypatch.delenv("WORKER_TOKEN", raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")

    with pytest.raises(ValueError, match="development placeholder"):
        Settings()


def test_a_real_worker_token_starts_normally(monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", "9f2c1a" * 8)
    monkeypatch.setenv("AUTH_ENABLED", "true")

    assert Settings().worker_token == "9f2c1a" * 8
