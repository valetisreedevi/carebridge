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
