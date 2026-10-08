"""Verificador de cifras: comprueba que cada número de la respuesta salga de una herramienta.

Reglas de comparación:
- La cifra de la respuesta se compara con los números de las salidas de las herramientas,
  redondeando la salida a la precisión que usa la respuesta (965 086 acepta 965086.43).
- Acepta abreviaturas: "965 mil", "1,2 M", "3 millones", "10 k".
- Si un separador es ambiguo ("1.234", "1,234"), prueba como miles y como decimal.
- Un porcentaje acepta también su fracción impresa por el código (35,2 % ↔ 0.352).
- Se ignoran años, fechas, enteros de un dígito, marcadores de lista y los números que
  aparecen en la pregunta del usuario.
Las cifras derivadas (porcentajes, diferencias) que no salgan del código se marcan igual
que cualquier otra: deben calcularse con código.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Número escrito por el modelo: miles con espacio, espacio duro, punto o coma; decimales con
# punto o coma; sufijo opcional de porcentaje o abreviatura.
_ANSWER_NUMBER = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:[   .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s?(?P<pct>%)|\s?(?P<abbr>mil millones|millones|millón|mil|MM|M|k|K)\b)?"
)
# Número impreso por Python: 275858.67, 1,767 (con formato de miles) o 1.2e+05.
_SOURCE_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?")
_DATE = re.compile(
    r"\b\d{1,4}[-/‑–.]\d{1,2}[-/‑–.]\d{1,4}\b"  # 02/01/2025, 2025-01-02
    r"|\b\d{4}[-‑]\d{2}\b"  # 2025-02
    r"|\b\d{1,2}/\d{4}\b"  # 02/2025
)
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
_SCALES = {
    "mil millones": 1e9,
    "millones": 1e6,
    "millón": 1e6,
    "MM": 1e6,
    "M": 1e6,
    "mil": 1e3,
    "k": 1e3,
    "K": 1e3,
}


@dataclass(frozen=True)
class Mention:
    """Una cifra de la respuesta con sus posibles lecturas (valor, decimales)."""

    text: str
    readings: tuple[tuple[float, int], ...]
    scale: float = 1.0
    percent: bool = False


@dataclass
class FigureCheck:
    checked: int  # cifras comprobadas (sin contar las ignoradas)
    unverified: list[str]  # cifras sin respaldo en ninguna salida


def check_figures(answer: str, sources: Iterable[str], question: str = "") -> FigureCheck:
    """Comprueba las cifras de `answer` contra los números de las `sources`."""
    source_values = _source_values(sources)
    question_values = {value for m in extract_mentions(question) for value in _values(m)}
    checked = 0
    unverified: list[str] = []
    for mention in extract_mentions(answer):
        if _is_ignorable(mention) or question_values & set(_values(mention)):
            continue
        checked += 1
        if not _is_supported(mention, source_values) and mention.text not in unverified:
            unverified.append(mention.text)
    return FigureCheck(checked=checked, unverified=unverified)


def find_unverified(answer: str, sources: Iterable[str], question: str = "") -> list[str]:
    """Devuelve las cifras de `answer` que no aparecen en ninguna de las `sources`."""
    return check_figures(answer, sources, question).unverified


def extract_mentions(text: str) -> list[Mention]:
    text = _LIST_MARKER.sub(" ", _DATE.sub(" ", text))
    mentions = []
    for match in _ANSWER_NUMBER.finditer(text):
        abbr = match.group("abbr")
        mentions.append(
            Mention(
                text=match.group(0).strip(),
                readings=tuple(_readings(match.group("num"))),
                scale=_SCALES[abbr] if abbr else 1.0,
                percent=match.group("pct") is not None,
            )
        )
    return mentions


def _readings(raw: str) -> list[tuple[float, int]]:
    """Lecturas posibles de un número según sus separadores."""
    s = re.sub(r"[   ]", "", raw)
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
        return [_parse(s, thousands="," if decimal == "." else ".", decimal=decimal)]
    separator = "." if has_dot else "," if has_comma else None
    if separator is None:
        return [(float(s), 0)]
    parts = s.split(separator)
    if len(parts) > 2:
        return [_parse(s, thousands=separator)]
    if len(parts[1]) == 3:  # ambiguo: 1.234 puede ser 1234 o 1,234
        return [_parse(s, thousands=separator), _parse(s, decimal=separator)]
    return [_parse(s, decimal=separator)]


def _parse(s: str, thousands: str | None = None, decimal: str | None = None) -> tuple[float, int]:
    if thousands:
        s = s.replace(thousands, "")
    if not decimal:
        return float(s), 0
    whole, fraction = s.split(decimal)
    return float(f"{whole}.{fraction}"), len(fraction)


def _values(mention: Mention) -> list[float]:
    return [value * mention.scale for value, _ in mention.readings]


def _is_ignorable(mention: Mention) -> bool:
    if mention.scale != 1.0 or mention.percent or len(mention.readings) != 1:
        return False
    value, decimals = mention.readings[0]
    if decimals:
        return False
    is_year = 1900 <= value <= 2100 and mention.text.isdigit()
    return is_year or value < 10


def _source_values(sources: Iterable[str]) -> list[float]:
    values: set[float] = set()
    for text in sources:
        values.update(float(token.replace(",", "")) for token in _SOURCE_NUMBER.findall(text))
        values.update(value for mention in extract_mentions(text) for value in _values(mention))
    return sorted(values)


def _is_supported(mention: Mention, source_values: list[float]) -> bool:
    for value, decimals in mention.readings:
        # Una cifra redondeada a `decimals` cubre ±media unidad de su última posición.
        targets = [(value * mention.scale, 0.5 * 10**-decimals * mention.scale)]
        if mention.percent:
            targets.append((value / 100, 0.5 * 10 ** -(decimals + 2)))
        for target, tolerance in targets:
            if any(abs(source - target) <= tolerance + 1e-9 for source in source_values):
                return True
    return False
