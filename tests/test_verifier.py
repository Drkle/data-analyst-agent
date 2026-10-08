"""Tests del verificador de cifras."""

import pytest

from data_analyst_agent.verifier import check_figures, extract_mentions, find_unverified

OUTPUT = """
  region    ingreso
0  Centro  275858.67
1     Sur  192470.52
Ingreso total: 965086.4299999999
Unidades: 1,767
Proporción: 0.3521
"""


@pytest.mark.parametrize(
    "answer",
    [
        "Centro generó 275 858,67.",  # miles con espacio, decimal con coma
        "Centro generó 275 858,67.",  # espacio duro
        "Centro generó 275.858,67.",  # miles con punto
        "Centro generó 275,858.67.",  # formato inglés
        "Centro generó 275858.67.",
        "El total fue 965 086,43.",  # la salida tiene más decimales
        "El total fue 965 086.",  # redondeado a enteros
        "El total fue de 965 mil.",  # abreviatura
        "El total fue de 0,97 M.",
        "Se vendieron 1 767 unidades.",  # la salida usa formato de miles
        "Representa el 35,2 % del total.",  # porcentaje impreso como fracción
    ],
)
def test_supported_figures_pass(answer: str) -> None:
    assert find_unverified(answer, [OUTPUT]) == []


def test_invented_figures_are_reported() -> None:
    answer = "Junio: 84 112,45 y julio: 92 341,07. Centro: 275 858,67."
    assert find_unverified(answer, [OUTPUT]) == ["84 112,45", "92 341,07"]


def test_wrong_rounding_is_reported() -> None:
    assert find_unverified("El total fue 965 087.", [OUTPUT]) == ["965 087"]


def test_derived_percentage_without_code_is_reported() -> None:
    assert find_unverified("Centro supera a Sur en un 43,3 %.", [OUTPUT]) == ["43,3 %"]


def test_ambiguous_separator_tries_both_readings() -> None:
    assert find_unverified("Se vendieron 1.767 unidades.", [OUTPUT]) == []
    assert find_unverified("La proporción es 0,352.", [OUTPUT]) == []
    readings = extract_mentions("1.234")[0].readings
    assert readings == ((1234.0, 0), (1.234, 3))


def test_years_dates_and_small_numbers_are_ignored() -> None:
    answer = (
        "En 2025, del 02‑01‑2025 al 31/12/2025 (mes 2025-02, 03/2025):\n"
        "1. Centro\n2. Sur\nHubo 5 regiones."
    )
    assert find_unverified(answer, []) == []


def test_numbers_from_the_question_are_ignored() -> None:
    question = "¿Cuántas ventas superan las 150 unidades?"
    assert find_unverified("Ninguna supera las 150 unidades.", [], question) == []


def test_any_tool_output_is_a_valid_source() -> None:
    sources = ["Gráfica creada (tipo: bar; 12 puntos)", "Filas: 500, columnas: 6"]
    assert find_unverified("Hay 500 filas y la gráfica tiene 12 puntos.", sources) == []


@pytest.mark.parametrize(
    "answer",
    [
        "Centro generó 275.858,67.",
        "En enero hubo 51.697,33 de ingresos.",  # formato colombiano pedido en el prompt
        "El total fue 965.086,43.",
        "El total fue 965.086.",  # punto de miles sin decimales (lectura ambigua)
        "Se vendieron 1.767 unidades.",
        "Representa el 35,2 % del total.",
    ],
)
def test_colombian_format_is_recognized(answer: str) -> None:
    sources = [OUTPUT, "enero 51697.33"]
    assert find_unverified(answer, sources) == []


def test_colombian_format_still_catches_invented_figures() -> None:
    assert find_unverified("Junio: 84.112,45.", [OUTPUT]) == ["84.112,45"]


def test_check_figures_counts_only_checked_mentions() -> None:
    check = check_figures("En 2025 Centro generó 275.858,67 (puesto 1).", [OUTPUT])
    assert check.checked == 1
    assert check.unverified == []
