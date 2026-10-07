"""Ciclo del agente: razonar -> herramienta -> observar -> repetir."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from data_analyst_agent.llm import LLMClient, Message, ToolDefinition
from data_analyst_agent.prompts import SYSTEM_PROMPT
from data_analyst_agent.tools import Chart, ToolResult

# Tope duro de gráficas por respuesta. El prompt pide además una sola si no se pidió.
MAX_CHARTS_PER_ANSWER = 3


class ToolExecutor(Protocol):
    definitions: list[ToolDefinition]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


@dataclass
class Step:
    """Una llamada a herramienta: qué se pidió, qué devolvió y la gráfica si la hubo."""

    tool: str
    arguments: dict[str, Any]
    output: str
    chart: Chart | None = None


@dataclass
class AgentResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0
    hit_limit: bool = False

    @property
    def charts(self) -> list[Chart]:
        return [step.chart for step in self.steps if step.chart is not None]


class Agent:
    """Agente con historial: cada pregunta continúa la conversación anterior."""

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolExecutor,
        max_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
        max_charts: int = MAX_CHARTS_PER_ANSWER,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.max_charts = max_charts
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    def run(self, question: str) -> AgentResult:
        self.messages.append(Message(role="user", content=question))
        steps: list[Step] = []

        for iteration in range(1, self.max_iterations + 1):
            response = self.llm.chat(self.messages, self.tools.definitions)
            self.messages.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                answer = response.text.strip() or "(El modelo no devolvió una respuesta.)"
                return AgentResult(answer=answer, steps=steps, iterations=iteration)

            for call in response.tool_calls:
                result = self._execute(call.name, call.arguments)
                if result.chart is not None and sum(s.chart is not None for s in steps) >= (
                    self.max_charts
                ):
                    result = ToolResult(
                        f"Error: ya hay {self.max_charts} gráficas en esta respuesta, que es el "
                        "máximo. No crees más gráficas."
                    )
                steps.append(
                    Step(call.name, call.arguments, output=result.text, chart=result.chart)
                )
                self.messages.append(
                    Message(role="tool", content=result.text, tool_call_id=call.id)
                )

        return AgentResult(
            answer=f"No llegué a una respuesta dentro del límite de {self.max_iterations} "
            "iteraciones.",
            steps=steps,
            iterations=self.max_iterations,
            hit_limit=True,
        )

    def _execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            return self.tools.execute(name, arguments)
        except Exception as exc:  # noqa: BLE001 - un fallo de herramienta no debe detener el ciclo
            return ToolResult(f"Error interno en la herramienta {name}: {exc}")
