"""Tests de las herramientas inspect_data, run_python y create_chart."""

import json
from pathlib import Path

import pytest

from data_analyst_agent import tools as tools_module
from data_analyst_agent.llm import INVALID_ARGUMENTS_KEY
from data_analyst_agent.tools import MAX_OUTPUT_CHARS, DataTools

GROUPED_BAR = (
    "datos = df.groupby('producto', as_index=False)['unidades'].sum()\n"
    "fig = px.bar(datos, x='producto', y='unidades', title='Unidades por producto')"
)


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
    assert len(output) < MAX_OUTPUT_CHARS + 150


def test_run_python_reports_omitted_lines(tools: DataTools) -> None:
    output = tools.run_python("for i in range(2000):\n    print(f'fila {i}')")
    assert "fila 0" in output
    assert "[salida recortada: se omitieron" in output
    assert "de 2000 líneas" in output


def test_run_python_prints_all_rows_of_medium_tables(tools: DataTools) -> None:
    output = tools.run_python("print(pd.DataFrame({'n': range(100)}))")
    assert "99" in output
    assert "..." not in output


def test_create_chart_returns_figure_and_summary(tools: DataTools) -> None:
    result = tools.create_chart(GROUPED_BAR)
    assert result.chart is not None
    assert json.loads(result.chart.figure_json)["data"][0]["type"] == "bar"
    assert "tipo: bar" in result.text
    assert "eje X: producto" in result.text
    assert "eje Y: unidades" in result.text
    assert "2 puntos" in result.text
    assert "run_python" in result.text


def test_create_chart_requires_fig(tools: DataTools) -> None:
    result = tools.create_chart("x = 1")
    assert result.chart is None
    assert "variable `fig`" in result.text


def test_create_chart_rejects_non_plotly_fig(tools: DataTools) -> None:
    result = tools.create_chart("fig = df")
    assert result.chart is None
    assert "figura de Plotly" in result.text


def test_create_chart_rejects_too_many_points(tools: DataTools) -> None:
    tools.max_chart_points = 2
    result = tools.create_chart("fig = px.scatter(df, x='producto', y='unidades')")
    assert result.chart is None
    assert "3 puntos y el máximo es 2" in result.text
    assert "Agrega los datos" in result.text


def test_create_chart_reports_code_errors(tools: DataTools) -> None:
    result = tools.create_chart("fig = px.bar(df, x='no_existe')")
    assert result.chart is None
    assert result.text.startswith("Error al ejecutar el código")


def test_execute_rejects_bad_calls(tools: DataTools) -> None:
    assert "desconocida" in tools.execute("borrar_todo", {}).text
    assert "'code'" in tools.execute("run_python", {}).text
    assert "'code'" in tools.execute("create_chart", {"code": " "}).text
    assert "JSON" in tools.execute("run_python", {INVALID_ARGUMENTS_KEY: "{roto"}).text


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        DataTools(tmp_path / "no_existe.csv")


def test_file_over_size_limit_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv = tmp_path / "grande.csv"
    csv.write_text("a\n" + "1\n" * 100, encoding="utf-8")
    monkeypatch.setattr(tools_module, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="máximo"):
        DataTools(csv, workdir=tmp_path / "trabajo")
