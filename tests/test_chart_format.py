"""Tests del formato de figuras: ejes de fechas con formato numérico."""

import json

import pandas as pd
import plotly.express as px

from data_analyst_agent.chart_format import (
    DATE_HOVERFORMAT,
    DATE_TICKFORMAT,
    format_figure,
)

DATES = pd.DataFrame(
    {"fecha": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]), "ingreso": [1, 2, 3]}
)


def _formatted(fig_json: str) -> dict:
    return json.loads(format_figure(fig_json))


def test_date_axis_gets_numeric_format() -> None:
    fig = _formatted(px.line(DATES, x="fecha", y="ingreso").to_json())
    xaxis = fig["layout"]["xaxis"]
    assert xaxis["tickformat"] == DATE_TICKFORMAT
    assert xaxis["hoverformat"] == DATE_HOVERFORMAT
    assert [stop["value"] for stop in xaxis["tickformatstops"]] == ["%d/%m/%Y", "%m/%Y", "%Y"]
    assert fig["data"][0]["xhoverformat"] == DATE_HOVERFORMAT
    assert "tickformat" not in fig["layout"]["yaxis"]


def test_dates_as_text_are_detected() -> None:
    texts = DATES.assign(fecha=DATES["fecha"].dt.strftime("%Y-%m-%d"))
    fig = _formatted(px.bar(texts, x="fecha", y="ingreso").to_json())
    assert fig["layout"]["xaxis"]["tickformat"] == DATE_TICKFORMAT


def test_horizontal_bars_format_the_y_axis() -> None:
    fig = _formatted(px.bar(DATES, x="ingreso", y="fecha", orientation="h").to_json())
    assert fig["layout"]["yaxis"]["tickformat"] == DATE_TICKFORMAT
    assert "tickformat" not in fig["layout"]["xaxis"]


def test_category_axes_are_untouched() -> None:
    categories = pd.DataFrame({"region": ["Norte", "Sur"], "ingreso": [1, 2]})
    fig = _formatted(px.bar(categories, x="region", y="ingreso").to_json())
    assert "tickformat" not in fig["layout"]["xaxis"]


def test_explicit_category_type_is_respected() -> None:
    fig = px.bar(DATES, x="fecha", y="ingreso")
    fig.update_xaxes(type="category")
    assert "tickformat" not in _formatted(fig.to_json())["layout"]["xaxis"]


def test_figures_without_axes_are_untouched() -> None:
    pie = px.pie(
        pd.DataFrame({"region": ["Norte", "Sur"], "ingreso": [1, 2]}),
        names="region",
        values="ingreso",
    )
    assert "xaxis" not in _formatted(pie.to_json())["layout"]


def test_numbers_use_colombian_separators() -> None:
    fig = _formatted(px.bar(pd.DataFrame({"r": ["a"], "v": [1.5]}), x="r", y="v").to_json())
    assert fig["layout"]["separators"] == ",."
