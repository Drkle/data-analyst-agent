"""Tests del historial acotado por turnos."""

from data_analyst_agent.history import Turn, estimate_tokens, select_history
from data_analyst_agent.llm import Message, ToolCall


def _turn(n: int, output: str = "resultado") -> Turn:
    return Turn(
        question=f"pregunta {n}",
        messages=[
            Message(role="user", content=f"pregunta {n}"),
            Message(role="assistant", tool_calls=[ToolCall(f"c{n}", "run_python", {"code": "x"})]),
            Message(role="tool", content=output, tool_call_id=f"c{n}"),
            Message(role="assistant", content=f"respuesta {n}"),
        ],
        answer=f"respuesta {n}",
    )


def _contents(messages: list[Message]) -> list[tuple[str, str]]:
    return [(m.role, m.content) for m in messages]


def test_last_turn_full_and_older_turns_compacted() -> None:
    history = select_history([_turn(1), _turn(2), _turn(3)], full_turns=1, token_budget=10_000)

    assert _contents(history[:4]) == [
        ("user", "pregunta 1"),
        ("assistant", "respuesta 1"),
        ("user", "pregunta 2"),
        ("assistant", "respuesta 2"),
    ]
    assert history[4:] == _turn(3).messages


def test_compacted_turns_have_no_tool_calls_or_outputs() -> None:
    history = select_history([_turn(1), _turn(2)], full_turns=0, token_budget=10_000)
    assert all(m.role in ("user", "assistant") for m in history)
    assert all(not m.tool_calls for m in history)


def test_every_tool_call_keeps_its_result() -> None:
    history = select_history([_turn(1), _turn(2), _turn(3)], full_turns=2, token_budget=10_000)
    call_ids = {c.id for m in history for c in m.tool_calls}
    result_ids = {m.tool_call_id for m in history if m.role == "tool"}
    assert call_ids == result_ids == {"c2", "c3"}


def test_budget_drops_oldest_turns_first() -> None:
    turns = [_turn(1), _turn(2), _turn(3)]
    budget = estimate_tokens(turns[1].compact()) + estimate_tokens(turns[2].compact())
    history = select_history(turns, full_turns=0, token_budget=budget)
    assert [m.content for m in history if m.role == "user"] == ["pregunta 2", "pregunta 3"]


def test_recent_turn_too_big_is_sent_compacted() -> None:
    big = _turn(1, output="x" * 9000)
    history = select_history([big], full_turns=1, token_budget=100)
    assert _contents(history) == [("user", "pregunta 1"), ("assistant", "respuesta 1")]


def test_nothing_fits_returns_empty_history() -> None:
    assert select_history([_turn(1)], full_turns=1, token_budget=0) == []
