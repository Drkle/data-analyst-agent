"""Configuración del proyecto desde variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Proveedores con endpoint compatible con la API de OpenAI: (URL base, modelo por defecto).
PROVIDERS: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
}


class ConfigError(Exception):
    """La configuración del entorno es inválida o está incompleta."""


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    base_url: str
    max_iterations: int = 8
    max_retries: int = 3
    call_delay: float = 1.0
    max_tokens: int = 2048
    sandbox_timeout: float = 30.0
    # Pensados para la capa gratuita de Groq (8.000 tokens por minuto): el historial previo
    # se reenvía en cada llamada, unas 3 por pregunta.
    history_full_turns: int = 1
    history_token_budget: int = 1500


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Lee la configuración del entorno, cargando antes `env_file` si existe."""
    if env_file is not None and env_file.exists():
        load_dotenv(env_file)

    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVIDERS:
        options = ", ".join(PROVIDERS)
        raise ConfigError(f"LLM_PROVIDER no soportado: {provider!r}. Opciones: {options}")
    base_url, default_model = PROVIDERS[provider]

    prefix = provider.upper()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(f"Falta {prefix}_API_KEY en el .env")

    return Settings(
        provider=provider,
        model=os.getenv("LLM_MODEL") or os.getenv(f"{prefix}_MODEL") or default_model,
        api_key=api_key,
        base_url=base_url,
        max_iterations=_env_int("MAX_ITERATIONS", Settings.max_iterations),
        max_retries=_env_int("MAX_RETRIES", Settings.max_retries),
        call_delay=_env_float("CALL_DELAY_SECONDS", Settings.call_delay),
        max_tokens=_env_int("MAX_TOKENS", Settings.max_tokens),
        sandbox_timeout=_env_float("SANDBOX_TIMEOUT", Settings.sandbox_timeout),
        history_full_turns=_env_int("HISTORY_FULL_TURNS", Settings.history_full_turns),
        history_token_budget=_env_int("HISTORY_TOKEN_BUDGET", Settings.history_token_budget),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número entero, no {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número, no {raw!r}") from exc
