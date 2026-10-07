"""Esquemas e implementación de herramientas. (Fases 1-2)

- inspect_data: esquema, tipos y muestra del dataset
- run_python:   ejecuta código pandas en el sandbox
- create_chart: genera una gráfica (Fase 2)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_analyst_agent.llm import INVALID_ARGUMENTS_KEY, ToolDefinition
from data_analyst_agent.sandbox import run_code

MAX_OUTPUT_CHARS = 4000
DEFAULT_WORKDIR = Path("sandbox_workspace")

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
    parameters={
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Código Python a ejecutar."}},
        "required": ["code"],
    },
)


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
    """Herramientas del agente ligadas a un dataset concreto."""

    def __init__(
        self, data_path: Path, timeout: float = 30.0, workdir: Path = DEFAULT_WORKDIR
    ) -> None:
        if not data_path.exists():
            raise FileNotFoundError(f"No existe el archivo {data_path}")
        self.data_path = data_path
        self.timeout = timeout
        self.workdir = workdir
        self.definitions: list[ToolDefinition] = [INSPECT_DATA, RUN_PYTHON]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Ejecuta la herramienta `name` y devuelve el texto que verá el modelo."""
        if INVALID_ARGUMENTS_KEY in arguments:
            raw = arguments[INVALID_ARGUMENTS_KEY]
            return f"Error: los argumentos no son un objeto JSON válido: {raw!r}"
        if name == "inspect_data":
            return self.inspect_data()
        if name == "run_python":
            code = arguments.get("code")
            if not isinstance(code, str) or not code.strip():
                return "Error: run_python necesita el argumento 'code' con código Python."
            return self.run_python(code)
        return f"Error: herramienta desconocida {name!r}. Disponibles: inspect_data, run_python."

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
            return f"Error: el código superó el tiempo máximo de {self.timeout:g} s y se detuvo."
        if not result.ok:
            return truncate(f"Error al ejecutar el código:\n{result.stderr.strip()}")
        output = result.stdout.strip()
        return truncate(output) if output else "(El código no imprimió nada. Usa print().)"
