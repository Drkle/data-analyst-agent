"""Entrega D: alertas de calidad de inspect_data (describen, no corrigen)."""

from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.inspection import MAX_ALERTS, inspect_report, quality_alerts
from data_analyst_agent.loading import load_table
from data_analyst_agent.tools import DataTools


def _alerts(df: pd.DataFrame) -> str:
    return "\n".join(quality_alerts(df))


def test_clean_data_has_no_alert_section() -> None:
    df = pd.DataFrame({"region": ["Norte", "Sur"], "unidades": [3, 5]})
    assert quality_alerts(df) == []
    assert "Posibles problemas" not in inspect_report(df)


def test_column_names_with_spaces() -> None:
    alerts = _alerts(pd.DataFrame({" Código Producto ": [1], "Precio  Unitario": [2]}))
    assert "espacios al inicio o al final: ' Código Producto '" in alerts
    assert "espacios dobles: 'Precio  Unitario'" in alerts


def test_almost_numeric_column_counts_odd_values() -> None:
    stock = ["10", "3", "-", "N/A", "7", "-", "N/A", "N/A", "12", "4", None]
    alerts = _alerts(pd.DataFrame({"STOCK": stock}))
    assert (
        "'STOCK': casi numérica: 5 valores numéricos y además 'N/A' ×3, '-' ×2, 1 vacíos" in alerts
    )
    assert "decide cómo tratarlos" in alerts


def test_numbers_stored_as_text_but_not_codes() -> None:
    df = pd.DataFrame({"precio": ["$33.350", "$1.250"], "codigo": ["05034007", "44420000"]})
    alerts = _alerts(df)
    assert "'precio': números guardados como texto (por ejemplo '$33.350')" in alerts
    assert "codigo" not in alerts


def test_mostly_text_and_dates_are_not_flagged() -> None:
    df = pd.DataFrame(
        {
            "nota": ["hola", "12", "adiós", "sin dato"],
            "fecha": ["17/04/2019", "01/02/2020", "x", "y"],
        }
    )
    assert quality_alerts(df) == []


def test_sentinels_at_the_extreme() -> None:
    df = pd.DataFrame({"pm25": [12.0, -999.0, 8.5, -999.0, 9.1], "t": [-999.0, 1.0, 2.0, 3.0, 4.0]})
    alerts = _alerts(df)
    assert "'pm25': el valor -999 aparece 2 veces" in alerts
    assert "'t'" not in alerts  # una sola vez no basta


def test_duplicated_rows_are_reported_not_removed() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    assert "Filas duplicadas exactas: 1 de 3. No se quitaron" in _alerts(df)
    assert len(df) == 3


def test_percentages_over_100_are_reported_neutrally() -> None:
    df = pd.DataFrame(
        {"COBERTURA_NETA": [95.1, 100.12], "Tasa (%)": [10.0, 20.0], "unidades": [150, 200]}
    )
    alerts = _alerts(df)
    assert (
        "'COBERTURA_NETA': 1 valores mayores que 100 (máximo 100.12). Revisar si es esperado"
        in alerts
    )
    assert "pueden superar el 100 % de forma legítima" in alerts
    assert "imposible" not in alerts and "error" not in alerts.lower()
    assert "Tasa" not in alerts and "unidades" not in alerts


def test_alerts_are_capped() -> None:
    df = pd.DataFrame({f" col{i} ": [1] for i in range(MAX_ALERTS + 3)})
    report = inspect_report(df)
    assert "... y 3 alertas más." in report


# --- Con los archivos del QA --------------------------------------------------------------------


def test_dirty_inventory_from_the_qa() -> None:
    df, _ = load_table(Path("data/test_sets/inventario_sucio.csv"))
    alerts = _alerts(df)
    assert "' Código Producto '" in alerts  # S12: espacios en el nombre
    assert "'STOCK': casi numérica" in alerts and "'-' ×4" in alerts  # S11
    assert "'N/A' ×5" in alerts
    assert "Filas duplicadas exactas: 6 de 86" in alerts  # S12
    assert "'Precio Unitario': números guardados como texto" in alerts


@pytest.mark.skipif(
    not Path("data/real/educacion_departamentos.csv").exists(), reason="dataset no descargado"
)
def test_coverage_over_100_in_the_real_dataset() -> None:
    df, _ = load_table(Path("data/real/educacion_departamentos.csv"))
    alerts = _alerts(df)
    assert "'COBERTURA_NETA': " in alerts and "Revisar si es esperado" in alerts


def test_inspect_data_shows_the_alerts_through_the_sandbox(tmp_path: Path) -> None:
    tools = DataTools(
        Path("data/test_sets/inventario_sucio.csv"), timeout=30, workdir=tmp_path / "s"
    )
    output = tools.inspect_data()
    assert "Posibles problemas de datos (revísalos antes de calcular):" in output
    assert "Filas duplicadas exactas: 6 de 86" in output
