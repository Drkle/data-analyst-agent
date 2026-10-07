"""Tests de las herramientas inspect_data y run_python."""

from pathlib import Path

import pytest

from data_analyst_agent.llm import INVALID_ARGUMENTS_KEY
from data_analyst_agent.tools import MAX_OUTPUT_CHARS, DataTools


@pytest.fixture
def tools(tmp_path: Path) -> DataTools:
    csv = tmp_path / "ventas.csv"
    csv.write_text(
        "producto,categoria,unidades\nLaptop,Electrónica,3\nCuaderno,Papelería,5\nLaptop,Electrónica,1\n",
        encoding="utf-8",
    )
    return DataTools(csv, timeout=15, workdir=tmp_path / "trabajo")


def test_inspect_data_describes_dataset(tools: DataTools) -> None:
    output = tools.inspect_data()
    assert "Filas: 3, columnas: 3" in output
    assert "- unidades: int64, 0 nulos" in output
    assert "Electrónica" in output


def test_run_python_has_dataset_loaded(tools: DataTools) -> None:
    assert tools.run_python("print(df['unidades'].sum())") == "9"


def test_run_python_keeps_non_ascii_text(tools: DataTools) -> None:
    assert tools.run_python("print(df['categoria'].iloc[1])") == "Papelería"


def test_run_python_reports_errors(tools: DataTools) -> None:
    output = tools.run_python("print(df['no_existe'])")
    assert output.startswith("Error al ejecutar el código")
    assert "KeyError" in output


def test_run_python_without_print_explains(tools: DataTools) -> None:
    assert "print()" in tools.run_python("x = 1")


def test_run_python_stops_on_timeout(tools: DataTools) -> None:
    tools.timeout = 5
    assert "tiempo máximo" in tools.run_python("while True:\n    pass")


def test_run_python_truncates_long_output(tools: DataTools) -> None:
    output = tools.run_python("print('x' * 10000)")
    assert "salida recortada" in output
    assert len(output) < MAX_OUTPUT_CHARS + 100


def test_execute_rejects_bad_calls(tools: DataTools) -> None:
    assert "desconocida" in tools.execute("borrar_todo", {})
    assert "'code'" in tools.execute("run_python", {})
    assert "JSON" in tools.execute("run_python", {INVALID_ARGUMENTS_KEY: "{roto"})


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        DataTools(tmp_path / "no_existe.csv")
