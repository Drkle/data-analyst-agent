"""Historial de la conversación por turnos y su versión acotada para enviar al modelo.

Cada llamada al modelo reenvía el contexto completo, así que el historial se acota:
- Los últimos `full_turns` turnos van completos (código y salidas de herramientas).
- Los anteriores van compactados: solo pregunta y respuesta final. Se quitan también las
  llamadas a herramientas, porque la API exige que cada llamada tenga su resultado.
- Si aun así se supera `token_budget`, se descartan los turnos más antiguos.
El turno en curso siempre va completo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from data_analyst_agent.llm import Message

# Estimación conservadora: con Groq se midieron unos 2,7 caracteres por token.
CHARS_PER_TOKEN = 3


@dataclass
class Turn:
    """Una pregunta terminada: todos sus mensajes y la respuesta final."""

    question: str
    messages: list[Message]  # empieza por la pregunta del usuario
    answer: str
    # Salidas de código que terminó bien: lo único que respalda cifras ante el verificador.
    evidence: list[str] = field(default_factory=list)

    def compact(self) -> list[Message]:
        return [
            Message(role="user", content=self.question),
            Message(role="assistant", content=self.answer),
        ]


def estimate_tokens(messages: list[Message]) -> int:
    chars = sum(
        len(m.content) + sum(len(json.dumps(c.arguments, ensure_ascii=False)) for c in m.tool_calls)
        for m in messages
    )
    return chars // CHARS_PER_TOKEN


def select_history(turns: list[Turn], full_turns: int, token_budget: int) -> list[Message]:
    """Mensajes de los turnos anteriores que caben en el presupuesto, en orden cronológico.

    Recorre de más reciente a más antiguo y se detiene en el primer turno que no cabe, para
    no dejar huecos en la conversación. Un turno reciente que no cabe completo se intenta
    compactado.
    """
    selected: list[list[Message]] = []
    used = 0
    for age, turn in enumerate(reversed(turns)):
        options = [turn.messages, turn.compact()] if age < full_turns else [turn.compact()]
        for option in options:
            cost = estimate_tokens(option)
            if used + cost <= token_budget:
                selected.append(option)
                used += cost
                break
        else:
            break
    return [message for messages in reversed(selected) for message in messages]
