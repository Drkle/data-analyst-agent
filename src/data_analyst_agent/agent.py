"""Ciclo del agente: razonar -> herramienta -> observar -> repetir."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from data_analyst_agent.llm import LLMClient, Message, ToolDefinition
from data_analyst_agent.prompts import SYSTEM_PROMPT


class ToolExecutor(Protocol):
    definitions: list[ToolDefinition]

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


@dataclass
class Step:
    """Una llamada a herramienta: qué se pidió y qué devolvió."""

    tool: str
    arguments: dict[str, Any]
    output: str


@dataclass
class AgentResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0
    hit_limit: bool = False


class Agent:
    """Agente con historial: cada pregunta continúa la conversación anterior."""

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolExecutor,
        max_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
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
                output = self._execute(call.name, call.arguments)
                steps.append(Step(tool=call.name, arguments=call.arguments, output=output))
                self.messages.append(Message(role="tool", content=output, tool_call_id=call.id))

        return AgentResult(
            answer=f"No llegué a una respuesta dentro del límite de {self.max_iterations} "
            "iteraciones.",
            steps=steps,
            iterations=self.max_iterations,
            hit_limit=True,
        )

    def _execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            return self.tools.execute(name, arguments)
        except Exception as exc:  # noqa: BLE001 - un fallo de herramienta no debe detener el ciclo
            return f"Error interno en la herramienta {name}: {exc}"
