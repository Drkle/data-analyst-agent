"""Tests del adaptador compatible con OpenAI, con un cliente falso (sin red)."""

from types import SimpleNamespace
from typing import Any

import httpx2 as httpx
import pytest
from openai import BadRequestError, RateLimitError

from data_analyst_agent.config import Settings
from data_analyst_agent.llm import (
    INVALID_ARGUMENTS_KEY,
    LLMError,
    Message,
    OpenAICompatibleClient,
    ToolCall,
    ToolDefinition,
)

SETTINGS = Settings(
    provider="groq", model="modelo", api_key="k", base_url="https://x", call_delay=0, max_retries=2
)


def _rate_limit(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://x"))
    return RateLimitError("rate limited", response=response, body=None)


def _completion(content: str = "", tool_calls: list[Any] | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=7)
    )


def _raw_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(outcomes: list[Any]) -> tuple[OpenAICompatibleClient, FakeCompletions, list[float]]:
    completions = FakeCompletions(outcomes)
    sleeps: list[float] = []
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatibleClient(SETTINGS, client=fake, sleep=sleeps.append), completions, sleeps


def test_returns_text_and_usage() -> None:
    client, _, _ = _client([_completion("hola")])
    response = client.chat([Message(role="user", content="hola")], [])
    assert response.text == "hola"
    assert response.tool_calls == []
    assert response.total_tokens == 7


def test_retries_429_using_retry_after_header() -> None:
    client, _, sleeps = _client([_rate_limit("3"), _completion("ok")])
    assert client.chat([Message(role="user", content="x")], []).text == "ok"
    assert sleeps == [3.0]


def test_retries_429_with_exponential_backoff() -> None:
    client, _, sleeps = _client([_rate_limit(), _rate_limit(), _completion("ok")])
    assert client.chat([Message(role="user", content="x")], []).text == "ok"
    assert sleeps == [2.0, 4.0]


def test_raises_llm_error_when_retries_exhausted() -> None:
    client, completions, _ = _client([_rate_limit(), _rate_limit(), _rate_limit()])
    with pytest.raises(LLMError, match="demasiadas peticiones") as error:
        client.chat([Message(role="user", content="x")], [])
    assert "429" in error.value.detail
    assert len(completions.requests) == 3


def _bad_request(code: str) -> BadRequestError:
    """Error 400 tal como lo construye el SDK con la respuesta de Groq."""
    body = {
        "message": "Failed to parse tool call arguments as JSON",
        "type": "invalid_request_error",
        "code": code,
    }
    response = httpx.Response(400, request=httpx.Request("POST", "https://x"))
    return BadRequestError(f"Error code: 400 - {body}", response=response, body=body)


def test_retries_tool_use_failed_and_counts_it() -> None:
    client, completions, _ = _client([_bad_request("tool_use_failed"), _completion("ok")])
    response = client.chat([Message(role="user", content="x")], [])
    assert response.text == "ok"
    assert response.tool_format_errors == 1
    assert len(completions.requests) == 2


def test_tool_use_failed_gives_up_with_clear_message() -> None:
    client, completions, _ = _client([_bad_request("tool_use_failed")] * 3)
    with pytest.raises(LLMError) as error:
        client.chat([Message(role="user", content="x")], [])

    message = str(error.value)
    assert message.startswith("El modelo no logró preparar el análisis")
    assert "400" not in message and "tool_use_failed" not in message and "{" not in message
    assert "tool_use_failed" in error.value.detail
    assert error.value.tool_format_errors == 3
    assert len(completions.requests) == 3  # 1 intento + 2 reintentos


def test_other_bad_requests_are_not_retried() -> None:
    client, completions, _ = _client([_bad_request("context_length_exceeded")])
    with pytest.raises(LLMError, match="error inesperado") as error:
        client.chat([Message(role="user", content="x")], [])
    assert error.value.tool_format_errors == 0
    assert len(completions.requests) == 1


def test_parses_tool_calls() -> None:
    raw = _raw_call("c1", "run_python", '{"code": "print(1)"}')
    client, _, _ = _client([_completion(tool_calls=[raw])])
    response = client.chat([Message(role="user", content="x")], [])
    assert response.tool_calls == [
        ToolCall(id="c1", name="run_python", arguments={"code": "print(1)"})
    ]


def test_marks_invalid_tool_arguments() -> None:
    raw = _raw_call("c1", "run_python", "{no es json")
    client, _, _ = _client([_completion(tool_calls=[raw])])
    response = client.chat([Message(role="user", content="x")], [])
    assert response.tool_calls[0].arguments == {INVALID_ARGUMENTS_KEY: "{no es json"}


def test_converts_history_and_tools_to_openai_format() -> None:
    client, completions, _ = _client([_completion("listo")])
    history = [
        Message(role="system", content="sistema"),
        Message(role="user", content="pregunta"),
        Message(role="assistant", tool_calls=[ToolCall("c1", "inspect_data", {})]),
        Message(role="tool", content="resultado", tool_call_id="c1"),
    ]
    tool = ToolDefinition(name="inspect_data", description="d", parameters={"type": "object"})
    client.chat(history, [tool])

    request = completions.requests[0]
    assert request["model"] == "modelo"
    assert request["messages"][2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "inspect_data", "arguments": "{}"},
            }
        ],
    }
    assert request["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "resultado"}
    assert request["tools"][0]["function"]["name"] == "inspect_data"
