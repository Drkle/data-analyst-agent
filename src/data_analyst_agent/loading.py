"""Carga de archivos: detecta el formato y guarda el dataset normalizado en Parquet.

Principio: se normaliza el FORMATO (codificación, separador, decimal, miles, ceros
iniciales, hoja), nunca el CONTENIDO. Por eso:
- "-", "N/A", "NA" y similares se conservan tal cual (solo una celda vacía es un nulo).
- No se quitan duplicados ni se corrige ningún valor.
- Una columna solo pasa a número si TODOS sus valores son números claros. Las columnas
  mixtas, los códigos con ceros iniciales (05034007) y las de decimal ambiguo (todos los
  valores como 1.234) quedan como texto, y se dice por qué.

Este módulo se ejecuta dentro del sandbox (sandbox.run_program le pasa su código fuente),
por eso solo depende de la librería estándar y de pandas: no importa nada del paquete.
Salida: CARPETA/data/<tabla>.parquet y CARPETA/data/catalog.json (nombre de tabla, archivo
de origen, hoja, filas y columnas). La v1 usa una sola tabla; el formato admite varias.

Uso en el proceso hijo: python -c <este archivo> ORIGEN CARPETA_SALIDA [HOJA] [NOMBRE_ORIGINAL]
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

# Carpeta de datos de la sesión: un Parquet por tabla y un catálogo. La v1 usa una sola
# tabla, pero el formato ya admite varias (un modelo de datos con archivos relacionados).
DATA_DIR = "data"
CATALOG_NAME = "catalog.json"
CATALOG_VERSION = 1
PREVIEW_ROWS = 10
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")  # utf-8-sig también lee UTF-8 sin BOM
SEPARATORS = ",;\t|"
_SAMPLE_CHARS = 64_000
_SAMPLE_VALUES = 5_000

REASON_CODE = "código con ceros iniciales"
REASON_MIXED = "mezcla números y texto"
REASON_AMBIGUOUS = "decimal ambiguo (todos los valores como 1.234): revisar si es decimal o miles"


class LoadError(Exception):
    """El archivo no se puede cargar. El mensaje está en español y es apto para el usuario."""


def load_table(path: Path, sheet: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Lee un CSV o un XLSX y devuelve el DataFrame normalizado y la información de la carga."""
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        df, info = _read_excel(path, sheet)
    elif suffix in (".csv", ".txt", ".tsv"):
        if sheet:
            raise LoadError("Solo los archivos de Excel tienen hojas.")
        df, info = _read_csv(path)
    else:
        raise LoadError(f"Formato no soportado ({suffix or 'sin extensión'}): usa CSV o XLSX.")
    if df.columns.empty:
        raise LoadError("El archivo está vacío: no tiene columnas.")
    if df.empty:
        columns = ", ".join(map(str, df.columns))
        raise LoadError(f"El archivo solo tiene encabezados ({columns}), sin filas de datos.")
    info.update(rows=len(df), columns=len(df.columns))
    return df, info


def prepare(
    source: Path, output_dir: Path, sheet: str | None = None, display_name: str | None = None
) -> dict[str, Any]:
    """Carga `source` y la guarda como tabla en `output_dir/data/`, con su catálogo.

    Devuelve la información de la carga (rutas relativas a `output_dir`).
    """
    df, info = load_table(source, sheet)
    origin = display_name or source.name
    name = table_name(origin, info["sheet"], info["sheets"])
    data_dir = output_dir / DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    parquet = f"{DATA_DIR}/{name}.parquet"
    df.to_parquet(output_dir / parquet, index=False)
    catalog = {
        "version": CATALOG_VERSION,
        "tables": [
            {
                "name": name,
                "file": parquet,
                "source": origin,
                "sheet": info["sheet"],
                "rows": info["rows"],
                "columns": info["columns"],
            }
        ],
    }
    catalog_path = f"{DATA_DIR}/{CATALOG_NAME}"
    (output_dir / catalog_path).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    preview = df.head(PREVIEW_ROWS)
    info["preview"] = preview.to_json(orient="split", date_format="iso", force_ascii=False)
    info.update(table=name, parquet=parquet, catalog=catalog_path)
    return info


def table_name(origin: str, sheet: str | None, sheets: list[str]) -> str:
    """Nombre de tabla válido como identificador: 'Ventas 2025.xlsx' + hoja 'Gastos' ->
    'ventas_2025_gastos'. La hoja solo se añade si el Excel tiene varias."""
    name = _slug(Path(origin).stem) or "tabla"
    if sheet and len(sheets) > 1:
        name = f"{name}_{_slug(sheet) or 'hoja'}"
    return f"t_{name}" if name[0].isdigit() else name


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


# --- CSV ----------------------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = path.read_bytes()
    if not raw.strip():
        raise LoadError("El archivo está vacío.")
    text, encoding = _decode(raw)
    separator = _detect_separator(text)
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=separator,
            dtype=str,
            keep_default_na=False,  # "N/A", "NA", "-"... se quedan como texto
            na_values=[""],
        )
    except pd.errors.EmptyDataError as exc:
        raise LoadError("El archivo está vacío.") from exc
    except pd.errors.ParserError as exc:
        raise LoadError(_parser_message(str(exc))) from exc

    decimal = _detect_decimal(frame)
    text_columns: dict[str, str] = {}
    for column in frame.columns:
        converted, reason = _to_number(frame[column], decimal)
        frame[column] = converted
        if reason:
            text_columns[str(column)] = reason
    info = {
        "type": "csv",
        "encoding": "utf-8" if encoding == "utf-8-sig" else encoding,
        "separator": separator,
        "decimal": decimal,
        "thousands": "." if decimal == "," else ",",
        "sheet": None,
        "sheets": [],
        "text_columns": text_columns,
    }
    return frame, info


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise LoadError("No se reconoce la codificación del archivo.")  # latin-1 no falla nunca


def _detect_separator(text: str) -> str:
    sample = text[:_SAMPLE_CHARS]
    try:
        return csv.Sniffer().sniff(sample, delimiters=SEPARATORS).delimiter
    except csv.Error:
        return ","


def _parser_message(error: str) -> str:
    match = re.search(r"Expected (\d+) fields in line (\d+), saw (\d+)", error)
    if match:
        expected, line, seen = match.groups()
        return (
            f"El archivo no parece una tabla: la línea {line} tiene {seen} campos y se "
            f"esperaban {expected}. Revisa que sea un CSV con el mismo número de columnas en "
            "todas las filas."
        )
    return "El archivo no parece una tabla: no se pudo separar en columnas."


def _number_patterns(decimal: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    thousands = re.escape("." if decimal == "," else ",")
    dec = re.escape(decimal)
    number = re.compile(rf"[-+]?(?:\d{{1,3}}(?:{thousands}\d{{3}})+|\d+)(?:{dec}\d+)?")
    integer = re.compile(rf"[-+]?(?:\d{{1,3}}(?:{thousands}\d{{3}})+|\d+)")
    return number, integer


def _detect_decimal(frame: pd.DataFrame) -> str:
    """Decide el separador decimal del archivo por los números que no dejan dudas."""
    values = pd.Series(frame.to_numpy().ravel()).dropna().astype(str).str.strip()
    values = values.head(_SAMPLE_VALUES)
    comma = values.str.fullmatch(r"[-+]?\d+,(?:\d{1,2}|\d{4,})|[-+]?\d{1,3}(?:\.\d{3})+,\d+")
    dot = values.str.fullmatch(r"[-+]?\d+\.(?:\d{1,2}|\d{4,})|[-+]?\d{1,3}(?:,\d{3})+\.\d+")
    return "," if comma.sum() > dot.sum() else "."


def _to_number(series: pd.Series, decimal: str) -> tuple[pd.Series, str | None]:
    """Convierte la columna a número solo si todos sus valores lo son sin ambigüedad."""
    values = series.dropna().str.strip()
    if values.empty:
        return series, None
    if values.str.fullmatch(r"[-+]?\d+").all() and values.str.fullmatch(r"0\d+").any():
        return series, REASON_CODE
    number, integer = _number_patterns(decimal)
    is_number = values.str.fullmatch(number)
    if not is_number.all():
        return series, REASON_MIXED if is_number.mean() >= 0.5 else None
    if values.str.fullmatch(r"[-+]?\d{1,3}[.,]\d{3}").all():
        return series, REASON_AMBIGUOUS
    thousands = "." if decimal == "," else ","
    plain = values.str.replace(thousands, "", regex=False).str.replace(decimal, ".", regex=False)
    numbers = pd.to_numeric(plain)
    if values.str.fullmatch(integer).all():
        dtype = "int64" if len(values) == len(series) else "Int64"
        return numbers.astype(dtype).reindex(series.index), None
    return numbers.astype("float64").reindex(series.index), None


# --- Excel --------------------------------------------------------------------------------------


def _read_excel(path: Path, sheet: str | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        book = pd.ExcelFile(path)
    except (zipfile.BadZipFile, ValueError, KeyError, OSError) as exc:
        raise LoadError("El archivo no es un Excel válido (.xlsx).") from exc
    sheets = [str(name) for name in book.sheet_names]
    if not sheets:
        raise LoadError("El Excel no tiene hojas.")
    chosen = sheet or sheets[0]
    if chosen not in sheets:
        raise LoadError(f"La hoja «{chosen}» no existe. Hojas del archivo: {', '.join(sheets)}.")
    # dtype=object: cada celda conserva su tipo en el Excel. Sin esto, pandas convierte en
    # número las celdas de TEXTO con solo dígitos y "05034007" perdería el cero.
    frame = book.parse(chosen, dtype=object, keep_default_na=False, na_values=[""])
    text_columns: dict[str, str] = {}
    for column in frame.columns:
        series = frame[column]
        values = series.dropna()
        kinds = {type(v) for v in values}
        if not kinds:
            continue
        if all(issubclass(k, (int, float)) and k is not bool for k in kinds):
            frame[column] = pd.to_numeric(series)
        elif all(issubclass(k, (datetime.datetime, datetime.date)) for k in kinds):
            frame[column] = pd.to_datetime(series)
        elif kinds == {str}:
            frame[column] = series.astype("str").where(series.notna())
            if values.str.fullmatch(r"\d+").all() and values.str.fullmatch(r"0\d+").any():
                text_columns[str(column)] = REASON_CODE
        else:  # p. ej. números y "N/A": se guarda todo como texto, sin cambiar ningún valor
            frame[column] = series.map(lambda v: v if pd.isna(v) else str(v))
            text_columns[str(column)] = REASON_MIXED
    info = {
        "type": "xlsx",
        "encoding": None,
        "separator": None,
        "decimal": None,
        "thousands": None,
        "sheet": chosen,
        "sheets": sheets,
        "text_columns": text_columns,
    }
    return frame, info


# --- Ejecución en el proceso aislado --------------------------------------------------------------


def _main(argv: list[str]) -> None:
    source, output_dir = Path(argv[0]), Path(argv[1])
    sheet = argv[2] if len(argv) > 2 and argv[2] else None
    display_name = argv[3] if len(argv) > 3 and argv[3] else None
    try:
        info = prepare(source, output_dir, sheet, display_name)
        result: dict[str, Any] = {"ok": True, "info": info}
    except LoadError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - cualquier otro fallo se informa en español
        result = {"ok": False, "error": f"No se pudo leer el archivo ({type(exc).__name__})."}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    _main(sys.argv[1:])
