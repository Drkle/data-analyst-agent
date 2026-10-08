"""Tests del ciclo del agente con un modelo y herramientas falsos (sin red)."""

from typing import Any

import pytest

from data_analyst_agent.agent import Agent
from data_analyst_agent.llm import LLMError, LLMResponse, Message, ToolCall, ToolDefinition
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
    def __init__(self, fail: bool = False, output: str | None = None) -> None:
        self.definitions: list[ToolDefinition] = []
        self.fail = fail
        self.output = output

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self.fail:
            raise RuntimeError("se rompió")
        if name == "create_chart":
            return ToolResult("Gráfica creada", chart=CHART)
        return ToolResult(self.output or f"resultado de {name}")


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


def test_verified_answer_does_not_trigger_verifier() -> None:
    llm = ScriptedLLM([_tool_response(), LLMResponse(text="Centro: 275 858,67.")])
    result = Agent(llm, FakeTools(output="Centro 275858.67")).run("¿Región con más ingresos?")

    assert result.verification.triggers == 0
    assert result.verification.unverified == []
    assert result.iterations == 2


def test_verifier_sends_invented_figures_back_to_model() -> None:
    llm = ScriptedLLM(
        [
            _tool_response(),
            LLMResponse(text="Centro: 275 858,67. Junio: 84 112,45."),
            LLMResponse(text="Centro: 275 858,67."),
        ]
    )
    result = Agent(llm, FakeTools(output="Centro 275858.67")).run("¿Ingresos?")

    feedback = llm.calls[2][-1]
    assert feedback.role == "user"
    assert "84 112,45" in feedback.content
    assert result.answer == "Centro: 275 858,67."
    assert result.verification.triggers == 1
    assert result.verification.flagged == 1
    assert result.verification.corrected == 1
    assert result.verification.unverified == []


def test_verifier_gives_up_and_marks_figures() -> None:
    invented = LLMResponse(text="Junio: 84 112,45.")
    llm = ScriptedLLM([invented, invented, invented])
    result = Agent(llm, FakeTools(), max_verifications=2).run("¿Ingresos?")

    assert result.answer == "Junio: 84 112,45."
    assert result.verification.triggers == 2
    assert result.verification.unverified == ["84 112,45"]
    assert result.verification.corrected == 0


class FailingThenScriptedLLM(ScriptedLLM):
    """Como ScriptedLLM, pero lanza las excepciones que encuentre en el guion."""

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        self.calls.append(list(messages))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_tool_format_errors_are_added_up_per_answer() -> None:
    first = _tool_response()
    first.tool_format_errors = 1
    final = LLMResponse(text="listo", tool_format_errors=2)
    result = Agent(ScriptedLLM([first, final]), FakeTools()).run("pregunta")

    assert result.tool_format_errors == 3


def test_llm_error_carries_the_answer_total() -> None:
    first = _tool_response()
    first.tool_format_errors = 1
    failure = LLMError("El modelo no logró preparar el análisis.", tool_format_errors=3)
    llm = FailingThenScriptedLLM([first, failure])  # type: ignore[list-item]

    with pytest.raises(LLMError) as error:
        Agent(llm, FakeTools()).run("pregunta")
    assert error.value.tool_format_errors == 4


def test_checked_counts_figures_of_the_final_answer() -> None:
    llm = ScriptedLLM([_tool_response(), LLMResponse(text="Centro: 275.858,67. Sur: 192.470,52.")])
    output = "Centro 275858.67\nSur 192470.52"
    result = Agent(llm, FakeTools(output=output)).run("¿Ingresos por región?")

    assert result.verification.checked == 2
    assert result.verification.unverified == []


def test_failure_mid_question_leaves_history_unchanged() -> None:
    failure = LLMError("El proveedor del modelo devolvió un error inesperado.")
    llm = FailingThenScriptedLLM(
        [LLMResponse(text="primera"), _tool_response(), failure, LLMResponse(text="tercera")]  # type: ignore[list-item]
    )
    agent = Agent(llm, FakeTools())
    agent.run("pregunta 1")
    with pytest.raises(LLMError):
        agent.run("pregunta 2")
    agent.run("pregunta 3")

    assert [turn.question for turn in agent.turns] == ["pregunta 1", "pregunta 3"]
    assert [(m.role, m.content) for m in llm.calls[-1][1:]] == [
        ("user", "pregunta 1"),
        ("assistant", "primera"),
        ("user", "pregunta 3"),
    ]


def test_old_turns_are_sent_compacted() -> None:
    llm = ScriptedLLM(
        [_tool_response("a"), LLMResponse(text="uno"), _tool_response("b")]
        + [LLMResponse(text="dos"), LLMResponse(text="tres")]
    )
    agent = Agent(llm, FakeTools(), history_full_turns=1)
    for question in ("pregunta 1", "pregunta 2", "pregunta 3"):
        agent.run(question)

    sent = llm.calls[-1]
    assert [(m.role, m.content) for m in sent[1:3]] == [
        ("user", "pregunta 1"),
        ("assistant", "uno"),
    ]
    assert {m.tool_call_id for m in sent if m.role == "tool"} == {"b"}


def test_verifier_still_sees_outputs_no_longer_sent() -> None:
    llm = ScriptedLLM(
        [_tool_response(), LLMResponse(text="Centro: 275.858,67."), LLMResponse(text="ok")]
        + [LLMResponse(text="Como dije, Centro: 275.858,67.")]
    )
    agent = Agent(llm, FakeTools(output="Centro 275858.67"), history_full_turns=0)
    agent.run("¿Región con más ingresos?")
    agent.run("Gracias")
    result = agent.run("¿Cuánto era?")

    assert all(m.role != "tool" for m in llm.calls[-1])
    assert result.verification.unverified == []
    assert result.verification.triggers == 0


def test_total_tokens_are_added_up() -> None:
    first = _tool_response()
    first.total_tokens = 900
    result = Agent(
        ScriptedLLM([first, LLMResponse(text="ok", total_tokens=1000)]), FakeTools()
    ).run("pregunta")
    assert result.total_tokens == 1900
