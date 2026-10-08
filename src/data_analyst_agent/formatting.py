"""Formato colombiano de números para lo que se muestra al usuario: 51.697,33."""

from __future__ import annotations

import pandas as pd


def format_number(value: float, decimals: int = 2) -> str:
    """51697.33 -> '51.697,33' (punto para miles, coma para decimales)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def format_preview(df: pd.DataFrame) -> pd.DataFrame:
    """Copia de `df` con las columnas decimales en formato colombiano.

    Los enteros se dejan tal cual para no deformar identificadores ni años (2025, no 2.025).
    """
    out = df.copy()
    for column in out.select_dtypes("float").columns:
        out[column] = out[column].map(lambda v: "" if pd.isna(v) else format_number(v))
    return out
