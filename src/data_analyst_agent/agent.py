"""Ciclo del agente: razonar -> herramienta -> observar -> repetir."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from data_analyst_agent.config import Settings
from data_analyst_agent.history import Turn, select_history
from data_analyst_agent.llm import LLMClient, LLMError, Message, ToolDefinition
from data_analyst_agent.prompts import SYSTEM_PROMPT
from data_analyst_agent.tools import Chart, ToolResult
from data_analyst_agent.verifier import check_figures

# Tope duro de gráficas por respuesta. El prompt pide además una sola si no se pidió.
MAX_CHARTS_PER_ANSWER = 3
# Veces que el verificador devuelve la respuesta al modelo antes de entregarla marcada.
MAX_VERIFICATIONS = 2


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
class VerificationStats:
    """Actividad del verificador de cifras en una respuesta."""

    triggers: int = 0  # veces que devolvió la respuesta al modelo
    flagged: int = 0  # cifras sin respaldo en la primera comprobación
    checked: int = 0  # cifras comprobadas en la respuesta final
    unverified: list[str] = field(default_factory=list)  # cifras sin respaldo al final
    # La respuesta final trae cifras, pero la última ejecución de código de la pregunta falló.
    last_execution_failed: bool = False

    @property
    def corrected(self) -> int:
        """Cifras señaladas que el modelo recalculó o quitó."""
        return max(self.flagged - len(self.unverified), 0)


@dataclass
class AgentResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0
    hit_limit: bool = False
    verification: VerificationStats = field(default_factory=VerificationStats)
    # Errores tool_use_failed del proveedor que se recuperaron con reintentos.
    tool_format_errors: int = 0
    # Tokens de todas las llamadas al modelo de esta respuesta (según el proveedor).
    total_tokens: int = 0

    @property
    def charts(self) -> list[Chart]:
        return [step.chart for step in self.steps if step.chart is not None]


class Agent:
    """Agente con historial: cada pregunta continúa la conversación anterior.

    Cada pregunta es una transacción: sus mensajes solo pasan al historial cuando termina.
    Si una llamada falla a mitad, el historial queda como estaba antes de la pregunta.
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolExecutor,
        max_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
        max_charts: int = MAX_CHARTS_PER_ANSWER,
        max_verifications: int = MAX_VERIFICATIONS,
        history_full_turns: int = 1,
        history_token_budget: int = 1500,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.max_charts = max_charts
        self.max_verifications = max_verifications
        self.history_full_turns = history_full_turns
        self.history_token_budget = history_token_budget
        self.system_message = Message(role="system", content=system_prompt)
        self.turns: list[Turn] = []

    @classmethod
    def from_settings(cls, llm: LLMClient, tools: ToolExecutor, settings: Settings) -> Agent:
        return cls(
            llm,
            tools,
            max_iterations=settings.max_iterations,
            history_full_turns=settings.history_full_turns,
            history_token_budget=settings.history_token_budget,
        )

    def run(self, question: str) -> AgentResult:
        current = [Message(role="user", content=question)]
        steps: list[Step] = []
        stats = VerificationStats()
        format_errors = 0
        tokens = 0
        evidence: list[str] = []  # salidas de código de esta pregunta que terminaron bien
        last_execution_failed = False

        for iteration in range(1, self.max_iterations + 1):
            try:
                response = self.llm.chat(self._context(current), self.tools.definitions)
            except LLMError as exc:
                # Totales de la pregunta, no solo de la llamada que falló.
                exc.tool_format_errors += format_errors
                exc.total_tokens += tokens
                raise
            format_errors += response.tool_format_errors
            tokens += response.total_tokens or 0
            current.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                answer = response.text.strip() or "(El modelo no devolvió una respuesta.)"
                check = check_figures(answer, self._sources(evidence), question)
                # Cifras tras una ejecución fallida: no salen de un cálculo que haya terminado.
                failed = last_execution_failed and check.checked > 0
                if stats.triggers == 0:
                    stats.flagged = len(check.unverified)
                can_retry = iteration < self.max_iterations
                needs_fix = check.unverified or failed
                if needs_fix and can_retry and stats.triggers < self.max_verifications:
                    stats.triggers += 1
                    feedback = _verification_feedback(question, check.unverified, failed)
                    current.append(Message(role="user", content=feedback))
                    continue
                stats.checked = check.checked
                stats.unverified = check.unverified
                stats.last_execution_failed = failed
                self.turns.append(Turn(question, current, answer, evidence))
                return AgentResult(
                    answer=answer,
                    steps=steps,
                    iterations=iteration,
                    verification=stats,
                    tool_format_errors=format_errors,
                    total_tokens=tokens,
                )

            for call in response.tool_calls:
                result = self._execute(call.name, call.arguments)
                if result.chart is not None and sum(s.chart is not None for s in steps) >= (
                    self.max_charts
                ):
                    result = ToolResult(
                        f"Error: ya hay {self.max_charts} gráficas en esta respuesta, que es el "
                        "máximo. No crees más gráficas.",
                        status="info",
                    )
                if result.status == "evidence":
                    evidence.append(result.text)
                    last_execution_failed = False
                elif result.status == "error":
                    last_execution_failed = True
                steps.append(
                    Step(call.name, call.arguments, output=result.text, chart=result.chart)
                )
                current.append(Message(role="tool", content=result.text, tool_call_id=call.id))

        answer = (
            f"No llegué a una respuesta dentro del límite de {self.max_iterations} iteraciones."
        )
        self.turns.append(Turn(question, current, answer, evidence))
        return AgentResult(
            answer=answer,
            steps=steps,
            iterations=self.max_iterations,
            hit_limit=True,
            verification=stats,
            tool_format_errors=format_errors,
            total_tokens=tokens,
        )

    def _context(self, current: list[Message]) -> list[Message]:
        """Lo que se envía al modelo: sistema, historial acotado y la pregunta en curso."""
        history = select_history(self.turns, self.history_full_turns, self.history_token_budget)
        return [self.system_message, *history, *current]

    def _execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            return self.tools.execute(name, arguments)
        except Exception as exc:  # noqa: BLE001 - un fallo de herramienta no debe detener el ciclo
            return ToolResult(f"Error interno en la herramienta {name}: {exc}", status="error")

    def _sources(self, evidence: list[str]) -> list[str]:
        """Fuentes válidas de cifras: salidas de código que terminó bien, en toda la
        conversación (también las que ya no se envían al modelo). inspect_data y las
        ejecuciones fallidas no cuentan."""
        return [text for turn in self.turns for text in turn.evidence] + evidence


def _verification_feedback(question: str, unverified: list[str], last_failed: bool) -> str:
    parts = ["[Verificador automático]"]
    if last_failed:
        parts.append(
            "Tu última ejecución de código falló, así que las cifras de tu respuesta no salen "
            "de un cálculo que haya terminado bien. Corrige el código y ejecútalo de nuevo "
            "antes de responder."
        )
    if unverified:
        parts.append(
            f"Estas cifras de tu respuesta no aparecen en ninguna salida de código que haya "
            f"terminado bien: {'; '.join(unverified)}. inspect_data no cuenta como cálculo. "
            "Calcúlalas con run_python, incluidas las derivadas (porcentajes, diferencias, "
            "totales), imprimiendo todos los valores que vas a dar, o quítalas."
        )
    parts.append(
        f"La pregunta que debes responder es: «{question}». Después escribe de nuevo la "
        "respuesta completa a esa pregunta."
    )
    return " ".join(parts)
