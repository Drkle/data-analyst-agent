"""Tests del ciclo del agente con un modelo y herramientas falsos (sin red)."""

from typing import Any

from data_analyst_agent.agent import Agent
from data_analyst_agent.llm import LLMResponse, Message, ToolCall, ToolDefinition
from data_analyst_agent.tools import Chart, ToolResult

CHART = Chart(figure_json="{}", kind="bar", x_label="x", y_label="y", title="t", points=3)


class ScriptedLLM:
    """Devuelve respuestas predefinidas y guarda el historial que recibió en cada llamada."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        self.calls.append(list(messages))
        return self.responses.pop(0)


class FakeTools:
    def __init__(self, fail: bool = False) -> None:
        self.definitions: list[ToolDefinition] = []
        self.fail = fail

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self.fail:
            raise RuntimeError("se rompió")
        if name == "create_chart":
            return ToolResult("Gráfica creada", chart=CHART)
        return ToolResult(f"resultado de {name}")


def _tool_response(call_id: str = "c1", name: str = "run_python") -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(call_id, name, {"code": "print(1)"})])


def test_runs_tool_then_answers() -> None:
    llm = ScriptedLLM([_tool_response(), LLMResponse(text="La respuesta es 1.")])
    result = Agent(llm, FakeTools()).run("¿Cuánto es?")

    assert result.answer == "La respuesta es 1."
    assert result.iterations == 2
    assert not result.hit_limit
    assert [s.tool for s in result.steps] == ["run_python"]
    tool_message = llm.calls[1][-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "c1"
    assert tool_message.content == "resultado de run_python"


def test_stops_at_iteration_limit() -> None:
    llm = ScriptedLLM([_tool_response(f"c{i}") for i in range(3)])
    result = Agent(llm, FakeTools(), max_iterations=3).run("pregunta")

    assert result.hit_limit
    assert result.iterations == 3
    assert len(result.steps) == 3
    assert "límite de 3" in result.answer


def test_keeps_history_between_questions() -> None:
    llm = ScriptedLLM([LLMResponse(text="primera"), LLMResponse(text="segunda")])
    agent = Agent(llm, FakeTools())
    agent.run("pregunta 1")
    agent.run("pregunta 2")

    roles_and_content = [(m.role, m.content) for m in llm.calls[1]]
    assert roles_and_content[1:] == [
        ("user", "pregunta 1"),
        ("assistant", "primera"),
        ("user", "pregunta 2"),
    ]


def test_tool_exception_is_reported_to_model() -> None:
    llm = ScriptedLLM([_tool_response(), LLMResponse(text="ok")])
    result = Agent(llm, FakeTools(fail=True)).run("pregunta")

    assert result.steps[0].output.startswith("Error interno en la herramienta run_python")
    assert result.answer == "ok"


def test_chart_reaches_result_but_not_model() -> None:
    llm = ScriptedLLM([_tool_response(name="create_chart"), LLMResponse(text="listo")])
    result = Agent(llm, FakeTools()).run("grafica")

    assert result.charts == [CHART]
    assert llm.calls[1][-1].content == "Gráfica creada"


def test_charts_beyond_limit_are_rejected() -> None:
    llm = ScriptedLLM(
        [_tool_response(f"c{i}", name="create_chart") for i in range(2)]
        + [LLMResponse(text="listo")]
    )
    result = Agent(llm, FakeTools(), max_charts=1).run("grafica")

    assert len(result.charts) == 1
    assert "máximo" in result.steps[1].output
