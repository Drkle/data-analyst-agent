"""Ajustes de formato de las figuras de Plotly, aplicados después de crearlas.

Se aplican al JSON de la figura fuera del sandbox y no dependen del modelo.

- Números en formato colombiano (51.697,33) en ejes y hover.
- Ejes de fechas: formato numérico (%m/%Y), que pasa a días o años según el zoom, para
  no mostrar nombres de meses en inglés. Al pasar el ratón, la fecha completa (%d/%m/%Y).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

# Formato colombiano en ejes y hover: coma decimal y punto de miles (51.697,33).
NUMBER_SEPARATORS = ",."
DATE_TICKFORMAT = "%m/%Y"
DATE_HOVERFORMAT = "%d/%m/%Y"
# Formato de las marcas según la distancia entre ellas, para que el zoom siga siendo legible.
DATE_TICKFORMATSTOPS = [
    {"dtickrange": [None, "M1"], "value": "%d/%m/%Y"},
    {"dtickrange": ["M1", "M12"], "value": DATE_TICKFORMAT},
    {"dtickrange": ["M12", None], "value": "%Y"},
]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$")
_SAMPLE_SIZE = 20


def format_figure(figure_json: str) -> str:
    """Devuelve el JSON de la figura con los ajustes de formato aplicados."""
    fig = pio.from_json(figure_json)
    format_date_axes(fig)
    fig.update_layout(separators=NUMBER_SEPARATORS)
    return fig.to_json()


def format_date_axes(fig: go.Figure) -> None:
    """Pone formato numérico en los ejes de fechas y en su texto al pasar el ratón."""
    layout = fig.layout.to_plotly_json()
    date_axes: set[str] = set()
    for trace in fig.data:
        for letter in ("x", "y"):
            values = getattr(trace, letter, None)
            if values is None:
                continue
            axis_ref = getattr(trace, f"{letter}axis", None) or letter  # "x", "x2"...
            axis_key = axis_ref.replace(letter, f"{letter}axis", 1)  # "xaxis", "xaxis2"...
            if not _is_date_axis(values, layout.get(axis_key, {}).get("type")):
                continue
            date_axes.add(axis_key)
            try:
                trace.update({f"{letter}hoverformat": DATE_HOVERFORMAT})
            except ValueError:  # tipos de traza sin formato de hover propio
                pass

    for axis_key in date_axes:
        fig.layout[axis_key].update(
            tickformat=DATE_TICKFORMAT,
            tickformatstops=DATE_TICKFORMATSTOPS,
            hoverformat=DATE_HOVERFORMAT,
        )


def _is_date_axis(values: Any, axis_type: str | None) -> bool:
    if axis_type == "date":
        return True
    if axis_type not in (None, "-"):
        return False
    if isinstance(values, np.ndarray) and np.issubdtype(values.dtype, np.datetime64):
        return True
    if isinstance(values, dict):  # array numérico codificado por Plotly ({"dtype", "bdata"})
        return False
    sample = list(values[:_SAMPLE_SIZE])
    return bool(sample) and all(
        isinstance(v, date) or (isinstance(v, str) and _ISO_DATE.match(v)) for v in sample
    )
