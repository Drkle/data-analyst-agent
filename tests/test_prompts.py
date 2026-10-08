"""Comprueba que las reglas clave siguen en el prompt de sistema."""

from data_analyst_agent.prompts import SYSTEM_PROMPT


def test_prompt_forbids_substituting_metrics() -> None:
    assert "Nunca sustituyas una métrica por otra" in SYSTEM_PROMPT
    assert "dilo explícitamente" in SYSTEM_PROMPT


def test_prompt_asks_to_sort_bars() -> None:
    assert "de mayor a menor" in SYSTEM_PROMPT


def test_prompt_asks_for_colombian_number_format() -> None:
    assert "formato colombiano" in SYSTEM_PROMPT
    assert "51.697,33" in SYSTEM_PROMPT
