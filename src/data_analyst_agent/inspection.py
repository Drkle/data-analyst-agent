"""Descripción del dataset para inspect_data, con alertas de calidad.

Se ejecuta dentro del sandbox: tools.py pasa este código fuente al proceso aislado, donde
`df` ya está cargado, y al ejecutarse como __main__ imprime el informe. Solo depende de
pandas y de la librería estándar, y también se puede importar para los tests.

Las alertas describen, no corrigen: el agente decide qué hacer y lo dice en la respuesta.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

MAX_ALERTS = 12
SENTINELS = (-99, -999, -9999, -99999, 9999, 99999)
# Columnas que probablemente son porcentajes o tasas, por su nombre.
PERCENT_HINTS = ("%", "porcentaje", "porc", "tasa", "cobertura", "pct", "proporcion", "percent")
_NUMBER_LIKE = re.compile(r"[-+]?\$?\s*\d[\d.,]*")
_DIGITS = re.compile(r"\d+")


def inspect_report(df: pd.DataFrame) -> str:
    lines = overview(df)
    alerts = quality_alerts(df)
    if alerts:
        lines += ["", "Posibles problemas de datos (revísalos antes de calcular):"]
        lines += [f"- {alert}" for alert in alerts[:MAX_ALERTS]]
        if len(alerts) > MAX_ALERTS:
            lines.append(f"- ... y {len(alerts) - MAX_ALERTS} alertas más.")
    return "\n".join(lines)


def overview(df: pd.DataFrame) -> list[str]:
    lines = [f"Filas: {len(df)}, columnas: {len(df.columns)}", "", "Columnas:"]
    lines += [
        f"- {col}: {dtype}, {nulls} nulos"
        for col, dtype, nulls in zip(df.columns, df.dtypes, df.isna().sum())
    ]
    lines += ["", "Primeras 5 filas:", df.head().to_string()]
    numeric = df.select_dtypes("number")
    if not numeric.empty:
        lines += [
            "",
            "Estadísticas de columnas numéricas:",
            numeric.describe().round(2).to_string(),
        ]
    return lines


def quality_alerts(df: pd.DataFrame) -> list[str]:
    alerts: list[str] = []
    for column in df.columns:
        alerts += _name_alerts(str(column))
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            alerts += _sentinel_alerts(column, series)
            alerts += _percent_alerts(column, series)
        elif not pd.api.types.is_datetime64_any_dtype(series):
            alerts += _text_number_alerts(column, series)
    duplicated = int(df.duplicated().sum())
    if duplicated:
        alerts.append(
            f"Filas duplicadas exactas: {duplicated} de {len(df)}. No se quitaron: decide si "
            "cuentan según la pregunta y dilo."
        )
    return alerts


def _name_alerts(name: str) -> list[str]:
    alerts = []
    if name != name.strip():
        alerts.append(
            f"Nombre de columna con espacios al inicio o al final: {name!r}. Usa el nombre "
            "exacto, con los espacios."
        )
    if "  " in name.strip():
        alerts.append(f"Nombre de columna con espacios dobles: {name!r}.")
    return alerts


def _text_number_alerts(column: object, series: pd.Series) -> list[str]:
    values = series.dropna().astype(str).str.strip()
    if values.empty:
        return []
    number_like = values.str.fullmatch(_NUMBER_LIKE)
    if not number_like.any():
        return []
    others = values[~number_like]
    if others.empty:
        if values.str.fullmatch(_DIGITS).all():
            return []  # códigos o identificadores: texto a propósito
        example = values.iloc[0]
        message = (
            f"{column!r}: números guardados como texto (por ejemplo {example!r}). Conviértelos "
            "antes de calcular y di cómo lo hiciste."
        )
        return [message]
    if number_like.mean() < 0.5:
        return []
    counts = others.value_counts().head(5)
    detail = ", ".join(f"{value!r} ×{count}" for value, count in counts.items())
    nulls = int(series.isna().sum())
    empty = f", {nulls} vacíos" if nulls else ""
    message = (
        f"{column!r}: casi numérica: {int(number_like.sum())} valores numéricos y además "
        f"{detail}{empty}. Esos valores no son números: decide cómo tratarlos (por ejemplo, "
        "como faltantes) y dilo en la respuesta."
    )
    return [message]


def _sentinel_alerts(column: object, series: pd.Series) -> list[str]:
    values = series.dropna()
    if values.empty:
        return []
    alerts = []
    for sentinel in SENTINELS:
        count = int((values == sentinel).sum())
        if count >= 2 and sentinel in (values.min(), values.max()):
            alerts.append(
                f"{column!r}: el valor {sentinel} aparece {count} veces, en el extremo de la "
                "columna; puede ser un código de 'sin dato'. Revísalo antes de promediar."
            )
    return alerts


def _percent_alerts(column: object, series: pd.Series) -> list[str]:
    name = unicodedata.normalize("NFKD", str(column)).encode("ascii", "ignore").decode().lower()
    if not any(hint in name or hint in str(column) for hint in PERCENT_HINTS):
        return []
    over = series[series > 100]
    if over.empty:
        return []
    message = (
        f"{column!r}: {len(over)} valores mayores que 100 (máximo {over.max():g}). Revisar si "
        "es esperado: algunas tasas, como la cobertura bruta, pueden superar el 100 % de forma "
        "legítima."
    )
    return [message]


if __name__ == "__main__":
    print(inspect_report(df))  # noqa: F821 - `df` lo define el proceso aislado
