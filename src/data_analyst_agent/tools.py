"""Esquemas e implementación de herramientas.

- inspect_data: esquema, tipos y muestra del dataset
- run_python:   ejecuta código pandas en el sandbox
- create_chart: ejecuta código Plotly en el sandbox y valida la figura resultante
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_analyst_agent.chart_format import format_figure
from data_analyst_agent.llm import INVALID_ARGUMENTS_KEY, ToolDefinition
from data_analyst_agent.sandbox import new_session_dir, run_code

MAX_OUTPUT_CHARS = 4000
MAX_CHART_POINTS = 5000
MAX_FILE_BYTES = 50 * 1024 * 1024

_CODE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"code": {"type": "string", "description": "Código Python a ejecutar."}},
    "required": ["code"],
}

INSPECT_DATA = ToolDefinition(
    name="inspect_data",
    description=(
        "Muestra la estructura del dataset: número de filas, columnas, tipos, nulos, "
        "filas de ejemplo y estadísticas. Úsala antes de escribir código."
    ),
    parameters={"type": "object", "properties": {}},
)

RUN_PYTHON = ToolDefinition(
    name="run_python",
    description=(
        "Ejecuta código Python con pandas. El dataset ya está cargado en la variable `df` "
        "y pandas está importado como `pd`. Cada ejecución empieza de cero: las variables "
        "no se conservan entre llamadas. Usa print() para ver los resultados."
    ),
    parameters=_CODE_PARAMETERS,
)

CREATE_CHART = ToolDefinition(
    name="create_chart",
    description=(
        "Crea una gráfica con Plotly. `df`, `pd`, `px` (plotly.express) y `go` "
        "(plotly.graph_objects) ya están disponibles. El código debe agregar los datos y "
        f"asignar la figura a la variable `fig`. Máximo {MAX_CHART_POINTS} puntos."
    ),
    parameters=_CODE_PARAMETERS,
)


@dataclass
class Chart:
    """Gráfica creada por create_chart, lista para mostrarse en la interfaz."""

    figure_json: str
    kind: str
    x_label: str | None
    y_label: str | None
    title: str | None
    points: int

    def summary(self) -> str:
        return (
            f"Gráfica creada (tipo: {self.kind}; eje X: {self.x_label or 'sin título'}; "
            f"eje Y: {self.y_label or 'sin título'}; {self.points} puntos; "
            f"título: {self.title or 'sin título'}). Las cifras de tu respuesta deben salir "
            "de run_python, no de la gráfica."
        )


@dataclass
class ToolResult:
    """Lo que devuelve una herramienta: el texto para el modelo y, si la hay, la gráfica."""

    text: str
    chart: Chart | None = None


def load_dataframe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path)
    return pd.read_csv(path)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Recorta salidas largas para no saturar el contexto del modelo."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [salida recortada: {len(text) - limit} caracteres omitidos]"


class DataTools:
    """Herramientas del agente ligadas a un dataset y a una carpeta de trabajo."""

    def __init__(
        self,
        data_path: Path,
        timeout: float = 30.0,
        workdir: Path | None = None,
        max_chart_points: int = MAX_CHART_POINTS,
    ) -> None:
        if not data_path.exists():
            raise FileNotFoundError(f"No existe el archivo {data_path}")
        size = data_path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(
                f"El archivo pesa {size / 1024 / 1024:.1f} MB y el máximo es "
                f"{MAX_FILE_BYTES // 1024 // 1024} MB."
            )
        self.data_path = data_path
        self.timeout = timeout
        self.workdir = workdir if workdir is not None else new_session_dir()
        self.max_chart_points = max_chart_points
        self.definitions: list[ToolDefinition] = [INSPECT_DATA, RUN_PYTHON, CREATE_CHART]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Ejecuta la herramienta `name` y devuelve su resultado."""
        if INVALID_ARGUMENTS_KEY in arguments:
            raw = arguments[INVALID_ARGUMENTS_KEY]
            return ToolResult(f"Error: los argumentos no son un objeto JSON válido: {raw!r}")
        if name == "inspect_data":
            return ToolResult(self.inspect_data())
        if name in ("run_python", "create_chart"):
            code = arguments.get("code")
            if not isinstance(code, str) or not code.strip():
                return ToolResult(f"Error: {name} necesita el argumento 'code' con código Python.")
            return (
                ToolResult(self.run_python(code))
                if name == "run_python"
                else self.create_chart(code)
            )
        names = ", ".join(d.name for d in self.definitions)
        return ToolResult(f"Error: herramienta desconocida {name!r}. Disponibles: {names}.")

    def inspect_data(self) -> str:
        df = load_dataframe(self.data_path)
        lines = [
            f"Archivo: {self.data_path.name}",
            f"Filas: {len(df)}, columnas: {len(df.columns)}",
            "",
            "Columnas:",
            *(
                f"- {col}: {dtype}, {nulls} nulos"
                for col, dtype, nulls in zip(df.columns, df.dtypes, df.isna().sum())
            ),
            "",
            "Primeras 5 filas:",
            df.head().to_string(),
        ]
        numeric = df.select_dtypes("number")
        if not numeric.empty:
            lines += [
                "",
                "Estadísticas de columnas numéricas:",
                numeric.describe().round(2).to_string(),
            ]
        return truncate("\n".join(lines))

    def run_python(self, code: str) -> str:
        result = run_code(code, self.data_path, self.timeout, self.workdir)
        if result.timed_out:
            return self._timeout_message()
        if not result.ok:
            return truncate(f"Error al ejecutar el código:\n{result.stderr.strip()}")
        output = result.stdout.strip()
        return truncate(output) if output else "(El código no imprimió nada. Usa print().)"

    def create_chart(self, code: str) -> ToolResult:
        chart_path = self.workdir / "charts" / f"{uuid.uuid4().hex}.json"
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        result = run_code(
            code,
            self.data_path,
            self.timeout,
            self.workdir,
            chart_path=chart_path,
            max_points=self.max_chart_points,
        )
        if result.timed_out:
            return ToolResult(self._timeout_message())
        if result.chart_invalid:
            return ToolResult(f"Error en la gráfica: {result.stderr.strip()}")
        if not result.ok:
            return ToolResult(truncate(f"Error al ejecutar el código:\n{result.stderr.strip()}"))

        info = json.loads(chart_path.read_text(encoding="utf-8"))
        chart = Chart(
            figure_json=format_figure(info["figure"]),
            kind=", ".join(info["types"]),
            x_label=info["x"],
            y_label=info["y"],
            title=info["title"],
            points=info["points"],
        )
        return ToolResult(chart.summary(), chart=chart)

    def _timeout_message(self) -> str:
        return f"Error: el código superó el tiempo máximo de {self.timeout:g} s y se detuvo."
