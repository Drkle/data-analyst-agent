"""Entrega B de punta a punta: la carga corre en el sandbox y todo lee el mismo Parquet."""

from pathlib import Path

import pytest

from data_analyst_agent.tools import DataTools, LoadError

COLOMBIA = Path("data/test_sets/ventas_excel_colombia.csv")
TWO_SHEETS = Path("data/robustness/finanzas_dos_hojas.xlsx")


def _tools(path: Path, tmp_path: Path, **kwargs: object) -> DataTools:
    return DataTools(path, timeout=30, workdir=tmp_path / "sesion", **kwargs)  # type: ignore[arg-type]


def test_colombian_csv_is_loaded_in_the_sandbox(tmp_path: Path) -> None:
    tools = _tools(COLOMBIA, tmp_path)
    assert tools.table == "ventas_excel_colombia"
    assert tools.data_path == tools.workdir / "data" / "ventas_excel_colombia.parquet"
    total = tools.run_python(
        "print(round(df.loc[df['Ciudad'] == 'Bogotá', 'Valor total'].sum(), 2))"
    )
    assert total == "90950117.89"  # referencia de t-vco-01


def test_inspect_data_explains_how_the_file_was_read(tmp_path: Path) -> None:
    output = _tools(COLOMBIA, tmp_path).inspect_data()
    assert "Archivo: ventas_excel_colombia.csv" in output
    assert "Formato detectado: codificación cp1252, separador ';', decimal ','" in output
    assert "- Valor total: float64, 0 nulos" in output


def test_inspect_data_lists_text_columns_with_their_reason(tmp_path: Path) -> None:
    csv = tmp_path / "hurtos.csv"
    csv.write_text(
        "municipio,codigo,stock\nAndes,05034007,3\nCali,76001000,-\nX,05001000,5\n",
        encoding="utf-8",
    )
    output = _tools(csv, tmp_path).inspect_data()
    assert "Columnas leídas como texto a propósito (no se modificó ningún valor):" in output
    assert "- 'codigo': código con ceros iniciales" in output
    assert "- 'stock': mezcla números y texto" in output


def test_codes_and_placeholders_reach_the_agent_unchanged(tmp_path: Path) -> None:
    csv = tmp_path / "datos_raros.csv"
    csv.write_text("codigo,stock\n05034007,-\n44420000,N/A\n05001000,7\n", encoding="utf-8")
    tools = _tools(csv, tmp_path)
    assert (
        tools.run_python("print(df['codigo'].tolist())") == "['05034007', '44420000', '05001000']"
    )
    assert tools.run_python("print(df['stock'].tolist())") == "['-', 'N/A', '7']"


def test_excel_sheets_are_listed_and_selectable(tmp_path: Path) -> None:
    first = _tools(TWO_SHEETS, tmp_path / "a")
    assert first.sheet == "Ingresos"
    output = first.inspect_data()
    assert "Hojas del Excel: Ingresos (en uso), Gastos." in output
    assert "el usuario debe elegirla" in output

    gastos = _tools(TWO_SHEETS, tmp_path / "b", sheet="Gastos")
    assert gastos.sheet == "Gastos"
    assert gastos.run_python("print(int(df['gasto'].sum()))") == "35093000"  # qa-xls-02


def test_preview_is_what_the_agent_sees(tmp_path: Path) -> None:
    csv = tmp_path / "datos.csv"
    csv.write_text("codigo;valor\n05034007;1.234,5\n44420000;7,25\n", encoding="utf-8")
    preview = _tools(csv, tmp_path, display_name="original.csv").preview()
    assert preview["codigo"].tolist() == ["05034007", "44420000"]
    assert preview["valor"].tolist() == [1234.5, 7.25]


def test_display_name_is_the_original_one(tmp_path: Path) -> None:
    csv = tmp_path / "datos.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    assert (
        "Archivo: mis_ventas.csv"
        in _tools(csv, tmp_path, display_name="mis_ventas.csv").inspect_data()
    )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (Path("data/robustness/solo_encabezados.csv"), "solo tiene encabezados"),
        (Path("data/robustness/texto_no_tabular.csv"), "no parece una tabla"),
    ],
)
def test_load_errors_reach_the_user_in_spanish(tmp_path: Path, path: Path, message: str) -> None:
    with pytest.raises(LoadError, match=message):
        _tools(path, tmp_path)


def test_missing_sheet_is_a_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="La hoja «Ventas» no existe"):
        _tools(TWO_SHEETS, tmp_path, sheet="Ventas")
