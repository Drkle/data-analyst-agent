"""Tests del formato colombiano de números."""

import pandas as pd
import pytest

from data_analyst_agent.formatting import format_number, format_preview


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (51697.33, 2, "51.697,33"),
        (1234567.891, 2, "1.234.567,89"),
        (5.5, 2, "5,50"),
        (1767, 0, "1.767"),
        (-965086.43, 2, "-965.086,43"),
    ],
)
def test_format_number(value: float, decimals: int, expected: str) -> None:
    assert format_number(value, decimals) == expected


def test_format_preview_formats_only_decimal_columns() -> None:
    df = pd.DataFrame({"anio": [2025], "precio": [51697.33], "producto": ["Laptop"]})
    preview = format_preview(df)
    assert preview["precio"].tolist() == ["51.697,33"]
    assert preview["anio"].tolist() == [2025]
    assert df["precio"].tolist() == [51697.33]  # no modifica el original
