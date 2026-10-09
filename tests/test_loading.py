"""Tests del cargador: normaliza el formato, nunca el contenido."""

import json
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.loading import (
    REASON_AMBIGUOUS,
    REASON_CODE,
    REASON_MIXED,
    LoadError,
    load_table,
    prepare,
)


def _csv(tmp_path: Path, text: str, encoding: str = "utf-8", name: str = "datos.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


# --- Formato: codificación, separador, decimal y miles ------------------------------------------


def test_plain_utf8_csv() -> None:
    df, info = load_table(Path("data/sample/ventas.csv"))
    assert info["encoding"] == "utf-8" and info["separator"] == "," and info["decimal"] == "."
    assert df["unidades"].dtype == "int64"
    assert df["precio"].dtype == "float64"
    assert df["fecha"].iloc[0] == "2025-01-02"  # las fechas quedan como texto


def test_excel_colombia_export(tmp_path: Path) -> None:
    text = "Ciudad;Cantidad;Valor total\nBogotá;3;1.234,56\nMedellín;10;98,5\n"
    df, info = load_table(_csv(tmp_path, text, encoding="cp1252"))
    assert (info["encoding"], info["separator"], info["decimal"]) == ("cp1252", ";", ",")
    assert df["Ciudad"].tolist() == ["Bogotá", "Medellín"]
    assert df["Valor total"].tolist() == [1234.56, 98.5]
    assert df["Cantidad"].dtype == "int64"


def test_real_colombian_file_loads() -> None:
    df, info = load_table(Path("data/test_sets/ventas_excel_colombia.csv"))
    assert info["encoding"] == "cp1252"
    bogota = df.loc[df["Ciudad"] == "Bogotá", "Valor total"].sum()
    assert round(bogota, 2) == 90950117.89  # referencia de t-vco-01


def test_utf8_with_bom_and_tabs(tmp_path: Path) -> None:
    df, info = load_table(_csv(tmp_path, "﻿a\tb\n1\t2\n", name="datos.tsv"))
    assert info["separator"] == "\t" and info["encoding"] == "utf-8"
    assert list(df.columns) == ["a", "b"]


def test_ambiguous_decimal_column_stays_text(tmp_path: Path) -> None:
    text = "monto;precio\n1.234;10,5\n2.500;3,25\n"
    df, info = load_table(_csv(tmp_path, text))
    assert info["text_columns"]["monto"] == REASON_AMBIGUOUS
    assert df["monto"].tolist() == ["1.234", "2.500"]
    assert df["precio"].tolist() == [10.5, 3.25]


# --- Contenido: nada se convierte ni se quita ---------------------------------------------------


def test_placeholders_are_kept_as_text(tmp_path: Path) -> None:
    # Como en inventario_sucio.csv: casi todo son números, con algunos marcadores de faltante.
    text = "producto,stock\nA,10\nB,-\nC,N/A\nD,NA\nE,\nF,12\nG,7\n"
    df, info = load_table(_csv(tmp_path, text))
    assert df["stock"].tolist()[:4] == ["10", "-", "N/A", "NA"]
    assert pd.isna(df["stock"].iloc[4])  # solo la celda vacía es un nulo
    assert info["text_columns"]["stock"] == REASON_MIXED


def test_mostly_text_column_is_not_flagged_as_mixed(tmp_path: Path) -> None:
    df, info = load_table(_csv(tmp_path, "nota\nhola\n12\nadiós\nsin dato\n"))
    assert df["nota"].tolist() == ["hola", "12", "adiós", "sin dato"]
    assert "nota" not in info["text_columns"]


def test_duplicates_are_kept(tmp_path: Path) -> None:
    df, _ = load_table(_csv(tmp_path, "a,b\n1,2\n1,2\n1,2\n"))
    assert len(df) == 3


def test_codes_with_leading_zeros_stay_text(tmp_path: Path) -> None:
    df, info = load_table(
        _csv(tmp_path, "municipio,codigo,poblacion\nAndes,05034007,1200\nX,44420000,90\n")
    )
    assert df["codigo"].tolist() == ["05034007", "44420000"]
    assert info["text_columns"]["codigo"] == REASON_CODE
    assert df["poblacion"].dtype == "int64"


def test_integers_with_gaps_use_nullable_type(tmp_path: Path) -> None:
    df, _ = load_table(_csv(tmp_path, "a,b\n1,x\n,y\n3,z\n"))
    assert str(df["a"].dtype) == "Int64"
    assert pd.isna(df["a"].iloc[1])


def test_text_column_with_prices_is_not_touched(tmp_path: Path) -> None:
    df, info = load_table(_csv(tmp_path, "producto,precio\nA,$33.350\nB,$1.250\n"))
    assert df["precio"].tolist() == ["$33.350", "$1.250"]
    assert "precio" not in info["text_columns"]  # texto normal, no hay nada que señalar


# --- Errores en español -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "está vacío"),
        ("   \n", "está vacío"),
        ("fecha,producto,valor\n", "solo tiene encabezados (fecha, producto, valor)"),
        ("Acta\nAsistentes varios\nSe revisó, se aprobó y, al final, se cerró\n", "la línea 3"),
    ],
)
def test_load_errors_are_clear(tmp_path: Path, content: str, message: str) -> None:
    with pytest.raises(LoadError, match=message.replace("(", r"\(").replace(")", r"\)")):
        load_table(_csv(tmp_path, content))


def test_unsupported_format_and_sheet_on_csv(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="Formato no soportado"):
        load_table(_csv(tmp_path, "a\n1\n", name="datos.json"))
    with pytest.raises(LoadError, match="Solo los archivos de Excel tienen hojas"):
        load_table(_csv(tmp_path, "a\n1\n"), sheet="Hoja1")


# --- Excel --------------------------------------------------------------------------------------

XLSX = Path("data/robustness/finanzas_dos_hojas.xlsx")


def test_excel_lists_sheets_and_uses_the_first_by_default() -> None:
    df, info = load_table(XLSX)
    assert info["sheets"] == ["Ingresos", "Gastos"]
    assert info["sheet"] == "Ingresos"
    assert list(df.columns) == ["mes", "ingreso"]


def test_excel_other_sheet() -> None:
    df, info = load_table(XLSX, sheet="Gastos")
    assert info["sheet"] == "Gastos"
    assert df["gasto"].sum() == 35093000  # referencia de qa-xls-02


def test_excel_missing_sheet_and_invalid_file(tmp_path: Path) -> None:
    with pytest.raises(
        LoadError, match="La hoja «Ventas» no existe. Hojas del archivo: Ingresos, Gastos"
    ):
        load_table(XLSX, sheet="Ventas")
    fake = tmp_path / "datos.xlsx"
    fake.write_text("esto no es un excel", encoding="utf-8")
    with pytest.raises(LoadError, match="no es un Excel válido"):
        load_table(fake)


def test_excel_mixed_and_code_columns(tmp_path: Path) -> None:
    path = tmp_path / "datos.xlsx"
    pd.DataFrame(
        {"stock": [10, "N/A", 5], "codigo": ["05034007", "44420000", "05001000"]}
    ).to_excel(path, index=False)
    df, info = load_table(path)
    assert info["text_columns"] == {"stock": REASON_MIXED, "codigo": REASON_CODE}
    assert df["stock"].tolist() == ["10", "N/A", "5"]
    assert df["codigo"].iloc[0] == "05034007"


# --- Parquet y vista previa ---------------------------------------------------------------------


def test_prepare_writes_parquet_and_preview(tmp_path: Path) -> None:
    source = _csv(tmp_path, "codigo;valor\n05034007;1.234,5\n44420000;7,25\n")
    info = prepare(source, tmp_path)
    df = pd.read_parquet(tmp_path / info["parquet"])
    assert df["codigo"].tolist() == ["05034007", "44420000"]
    assert df["valor"].tolist() == [1234.5, 7.25]
    preview = json.loads(info["preview"])
    assert preview["columns"] == ["codigo", "valor"]
    assert preview["data"][0] == ["05034007", 1234.5]
