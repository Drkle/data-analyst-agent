"""Capa de abstracción del proveedor de modelos.

El agente solo conoce los tipos de este módulo (Message, ToolCall, ToolDefinition,
LLMResponse). Cada adaptador traduce entre ellos y el formato de su proveedor.

- `OpenAICompatibleClient`: Groq y Gemini (cambia solo base_url y key).
- Adaptador de Anthropic: pendiente para la Fase 4 (benchmark).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from openai import APIError, OpenAI, RateLimitError

from data_analyst_agent.config import Settings

Role = Literal["system", "user", "assistant", "tool"]

MAX_RETRY_WAIT = 60.0
# Clave con la que se marcan argumentos de herramienta que no son JSON válido.
INVALID_ARGUMENTS_KEY = "_invalid_arguments"


class LLMError(Exception):
    """Fallo al llamar al modelo (incluye agotar los reintentos ante 429)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    total_tokens: int | None = None


class LLMClient(Protocol):
    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse: ...


class OpenAICompatibleClient:
    """Adaptador para proveedores con API compatible con OpenAI (Groq, Gemini)."""

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        # max_retries=0: los reintentos los gestiona esta clase, no el SDK.
        self._client = client or OpenAI(
            api_key=settings.api_key, base_url=settings.base_url, max_retries=0
        )
        self._sleep = sleep
        self._last_call: float | None = None

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [_to_openai_message(m) for m in messages],
            "max_tokens": self._settings.max_tokens,
        }
        if tools:
            request["tools"] = [_to_openai_tool(t) for t in tools]

        for attempt in range(self._settings.max_retries + 1):
            self._throttle()
            try:
                response = self._client.chat.completions.create(**request)
            except RateLimitError as exc:
                if attempt == self._settings.max_retries:
                    raise LLMError(
                        f"Límite de tasa persistente (429) tras {attempt + 1} intentos"
                    ) from exc
                self._sleep(_retry_delay(exc, attempt))
            except APIError as exc:
                raise LLMError(f"Error del proveedor {self._settings.provider}: {exc}") from exc
            else:
                return _from_openai_response(response)
        raise AssertionError("inalcanzable")

    def _throttle(self) -> None:
        """Respeta una pausa mínima entre llamadas para no agotar el cupo por minuto."""
        if self._last_call is not None:
            wait = self._settings.call_delay - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = time.monotonic()


def create_client(settings: Settings) -> LLMClient:
    """Devuelve el cliente del proveedor configurado en LLM_PROVIDER."""
    # Todos los proveedores soportados hoy (Groq, Gemini) son compatibles con OpenAI.
    return OpenAICompatibleClient(settings)


def _retry_delay(exc: RateLimitError, attempt: int) -> float:
    """Segundos a esperar: el `retry-after` del servidor o, si no viene, espera exponencial."""
    fallback = 2.0 ** (attempt + 1)
    try:
        delay = float(exc.response.headers.get("retry-after", fallback))
    except (TypeError, ValueError):
        delay = fallback
    return min(delay, MAX_RETRY_WAIT)


def _to_openai_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if not message.tool_calls:
        return {"role": message.role, "content": message.content}
    return {
        "role": message.role,
        "content": message.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ],
    }


def _to_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _from_openai_response(response: Any) -> LLMResponse:
    message = response.choices[0].message
    calls = [
        ToolCall(id=c.id, name=c.function.name, arguments=_parse_arguments(c.function.arguments))
        for c in message.tool_calls or []
    ]
    usage = getattr(response, "usage", None)
    return LLMResponse(
        text=message.content or "",
        tool_calls=calls,
        total_tokens=usage.total_tokens if usage else None,
    )


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {INVALID_ARGUMENTS_KEY: raw}
    return parsed if isinstance(parsed, dict) else {INVALID_ARGUMENTS_KEY: raw}
