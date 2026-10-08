"""Tests de la carga de configuración (sin leer el .env real)."""

import pytest

from data_analyst_agent.config import ConfigError, load_settings

ENV_VARS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "MAX_ITERATIONS",
    "MAX_RETRIES",
    "CALL_DELAY_SECONDS",
    "MAX_TOKENS",
    "SANDBOX_TIMEOUT",
    "HISTORY_FULL_TURNS",
    "HISTORY_TOKEN_BUDGET",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_groq_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    settings = load_settings(env_file=None)
    assert settings.provider == "groq"
    assert settings.base_url == "https://api.groq.com/openai/v1"
    assert settings.model == "openai/gpt-oss-120b"
    assert settings.max_iterations == 8


def test_overrides_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "Gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("LLM_MODEL", "otro-modelo")
    monkeypatch.setenv("MAX_ITERATIONS", "3")
    monkeypatch.setenv("CALL_DELAY_SECONDS", "0.5")
    settings = load_settings(env_file=None)
    assert settings.provider == "gemini"
    assert settings.model == "otro-modelo"
    assert settings.max_iterations == 3
    assert settings.call_delay == 0.5


def test_missing_api_key_raises() -> None:
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_settings(env_file=None)


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "otro")
    with pytest.raises(ConfigError, match="no soportado"):
        load_settings(env_file=None)


def test_invalid_number_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("MAX_ITERATIONS", "muchas")
    with pytest.raises(ConfigError, match="MAX_ITERATIONS"):
        load_settings(env_file=None)


def test_history_defaults_fit_groq_free_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    settings = load_settings(env_file=None)
    assert settings.history_full_turns == 1
    assert settings.history_token_budget == 1500

    monkeypatch.setenv("HISTORY_FULL_TURNS", "3")
    monkeypatch.setenv("HISTORY_TOKEN_BUDGET", "4000")
    settings = load_settings(env_file=None)
    assert (settings.history_full_turns, settings.history_token_budget) == (3, 4000)
