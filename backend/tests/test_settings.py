from app.config.settings import Settings


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
