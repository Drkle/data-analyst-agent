"""Catálogo de tablas y protección de los datos de la sesión (hash + restauración)."""

import json
import os
from pathlib import Path

import pytest

from data_analyst_agent.loading import table_name
from data_analyst_agent.tools import DATA_RESTORED_AFTER, DATA_RESTORED_BEFORE, DataTools


@pytest.fixture
def tools(tmp_path: Path) -> DataTools:
    csv = tmp_path / "datos.csv"
    csv.write_text("region,unidades\nNorte,3\nSur,5\n", encoding="utf-8")
    return DataTools(csv, timeout=30, workdir=tmp_path / "sesion", display_name="Ventas 2025.csv")


# --- Catálogo ------------------------------------------------------------------------------------


def test_catalog_describes_the_table(tools: DataTools) -> None:
    catalog = json.loads((tools.workdir / "data" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["version"] == 1
    assert catalog["tables"] == [
        {
            "name": "ventas_2025",
            "file": "data/ventas_2025.parquet",
            "source": "Ventas 2025.csv",
            "sheet": None,
            "rows": 2,
            "columns": 2,
        }
    ]
    assert tools.data_path == tools.workdir / "data" / "ventas_2025.parquet"


@pytest.mark.parametrize(
    ("origin", "sheet", "sheets", "expected"),
    [
        ("Ventas 2025.xlsx", "Gastos", ["Ingresos", "Gastos"], "ventas_2025_gastos"),
        ("Ventas 2025.xlsx", "Hoja1", ["Hoja1"], "ventas_2025"),  # una sola hoja: no se añade
        ("Población Ñuble.csv", None, [], "poblacion_nuble"),
        ("2025.csv", None, [], "t_2025"),  # un identificador no empieza por número
        ("###.csv", None, [], "tabla"),
    ],
)
def test_table_names_are_valid_identifiers(
    origin: str, sheet: str | None, sheets: list[str], expected: str
) -> None:
    assert table_name(origin, sheet, sheets) == expected


# --- Protección de los datos ---------------------------------------------------------------------


def test_code_that_modifies_the_data_is_reverted(tools: DataTools) -> None:
    attack = "import pathlib\npathlib.Path('data/ventas_2025.parquet').write_bytes(b'basura')"
    output = tools.run_python(attack)
    assert DATA_RESTORED_AFTER in output
    assert tools.restorations == 1
    assert tools.run_python("print(df['unidades'].sum())") == "8"


def test_deleted_data_and_catalog_are_restored(tools: DataTools) -> None:
    output = tools.run_python("import shutil\nshutil.rmtree('data')")
    assert DATA_RESTORED_AFTER in output
    assert (tools.workdir / "data" / "catalog.json").is_file()
    assert tools.run_python("print(len(df))") == "2"


def test_change_detected_before_running(tools: DataTools) -> None:
    (tools.workdir / "data" / "catalog.json").write_text("{}", encoding="utf-8")
    output = tools.run_python("print(len(df))")
    assert output.startswith("2")
    assert DATA_RESTORED_BEFORE in output


def test_untouched_data_gives_no_notice(tools: DataTools) -> None:
    assert tools.run_python("print(len(df))") == "2"
    assert "Aviso" not in tools.inspect_data()
    assert tools.restorations == 0


def test_restore_never_writes_through_a_symlink(tools: DataTools, tmp_path: Path) -> None:
    victim = tmp_path / "fuera_de_la_sesion.txt"
    victim.write_text("no tocar", encoding="utf-8")
    parquet = tools.data_path
    parquet.unlink()
    try:
        os.symlink(victim, parquet)
    except OSError:
        pytest.skip("este sistema no permite crear enlaces simbólicos sin privilegios")
    output = tools.run_python("print(len(df))")
    assert DATA_RESTORED_BEFORE in output
    assert victim.read_text(encoding="utf-8") == "no tocar"
    assert not parquet.is_symlink() and parquet.is_file()
