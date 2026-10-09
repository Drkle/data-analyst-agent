"""Comprueba que las reglas clave siguen en el prompt de sistema."""

import re

from data_analyst_agent.prompts import SYSTEM_PROMPT


def test_prompt_forbids_substituting_metrics() -> None:
    assert "Nunca sustituyas una métrica por otra" in SYSTEM_PROMPT
    assert "dilo explícitamente" in SYSTEM_PROMPT


def test_prompt_asks_to_sort_bars() -> None:
    assert "de mayor a menor" in SYSTEM_PROMPT


def test_prompt_asks_for_colombian_number_format() -> None:
    assert "formato colombiano" in SYSTEM_PROMPT
    assert "51.697,33" in SYSTEM_PROMPT


def test_prompt_forbids_inventing_currencies_or_units() -> None:
    assert "Usa solo las monedas y unidades que aparecen" in SYSTEM_PROMPT
    assert "da el número sin unidad" in SYSTEM_PROMPT


def test_prompt_separates_identifiers_from_entities_and_states_scope() -> None:
    assert "Un identificador de respuesta o de fila no es un cliente" in SYSTEM_PROMPT
    assert '"en este registro"' in SYSTEM_PROMPT
    assert "no generalices" in SYSTEM_PROMPT


def test_prompt_forbids_forecasts() -> None:
    assert "No pronostiques ni estimes valores futuros" in SYSTEM_PROMPT


def test_prompt_asks_to_report_gaps_and_neutral_over_100() -> None:
    assert "faltan periodos" in SYSTEM_PROMPT
    assert "menciónalo de forma neutral" in SYSTEM_PROMPT
    assert "conviene revisar si es esperado" in SYSTEM_PROMPT
    assert "No lo declares imposible" in SYSTEM_PROMPT


def test_prompt_says_not_allowed_instead_of_not_capable() -> None:
    assert "di que no está permitido" in SYSTEM_PROMPT


def test_prompt_rules_are_numbered_in_order() -> None:
    numbers = [int(n) for n in re.findall(r"(?m)^(\d+)\. ", SYSTEM_PROMPT)]
    assert numbers == list(range(1, len(numbers) + 1))
