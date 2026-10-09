"""Esquemas e implementación de herramientas.

- inspect_data: esquema, tipos y muestra del dataset
- run_python:   ejecuta código pandas en el sandbox
- create_chart: ejecuta código Plotly en el sandbox y valida la figura resultante
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from data_analyst_agent import loading
from data_analyst_agent.chart_format import format_figure
from data_analyst_agent.llm import INVALID_ARGUMENTS_KEY, ToolDefinition
from data_analyst_agent.loading import LoadError
from data_analyst_agent.sandbox import (
    MAX_OUTPUT_BYTES,
    ExecutionResult,
    new_session_dir,
    run_code,
    run_program,
)

MAX_OUTPUT_CHARS = 4000
MAX_CHART_POINTS = 5000
MAX_FILE_BYTES = 50 * 1024 * 1024
LOAD_TIMEOUT = 60.0

DATA_RESTORED_BEFORE = (
    "[Aviso: el archivo de datos había cambiado desde la carga; se restauró el original "
    "antes de esta ejecución.]"
)
DATA_RESTORED_AFTER = (
    "[Aviso: este código modificó los datos guardados de la sesión; se restauró el original. "
    "Trabaja sobre df en memoria y no escribas en la carpeta data/.]"
)

__all__ = ["DataTools", "LoadError", "ToolResult"]

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


ToolStatus = Literal["evidence", "info", "error"]


@dataclass
class ToolResult:
    """Lo que devuelve una herramienta: el texto para el modelo y, si la hay, la gráfica.

    `status` dice qué valor tiene la salida para el verificador de cifras:
    - evidence: salida de código que terminó bien; puede respaldar cifras de la respuesta
    - info:     descripción de los datos (inspect_data); no cuenta como cálculo
    - error:    la ejecución falló o la llamada era inválida
    """

    text: str
    chart: Chart | None = None
    status: ToolStatus = "evidence"


# Lo ejecuta inspect_data en el sandbox, sobre el Parquet ya normalizado (df).
_INSPECT_CODE = """
print(f"Filas: {len(df)}, columnas: {len(df.columns)}")
print()
print("Columnas:")
for col, dtype, nulls in zip(df.columns, df.dtypes, df.isna().sum()):
    print(f"- {col}: {dtype}, {nulls} nulos")
print()
print("Primeras 5 filas:")
print(df.head().to_string())
numeric = df.select_dtypes("number")
if not numeric.empty:
    print()
    print("Estadísticas de columnas numéricas:")
    print(numeric.describe().round(2).to_string())
"""


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Recorta salidas largas para no saturar el contexto, avisando de lo que falta."""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > limit:
            break
        kept.append(line)
        size += len(line) + 1
    if not kept:  # una sola línea enorme
        return (
            f"{text[:limit]}\n[salida recortada: se omitieron {len(text) - limit} caracteres. "
            "Te faltan datos: imprime solo lo necesario.]"
        )
    omitted = len(lines) - len(kept)
    return (
        "\n".join(kept) + f"\n[salida recortada: se omitieron {omitted} de {len(lines)} líneas. "
        "Te faltan datos: agrega o imprime solo lo necesario antes de dar cifras.]"
    )


class DataTools:
    """Herramientas del agente ligadas a un dataset y a una carpeta de trabajo."""

    def __init__(
        self,
        data_path: Path,
        timeout: float = 30.0,
        workdir: Path | None = None,
        max_chart_points: int = MAX_CHART_POINTS,
        sheet: str | None = None,
        display_name: str | None = None,
    ) -> None:
        """Copia el archivo a la carpeta de la sesión y lo carga en el sandbox.

        Lanza LoadError (mensaje en español) si el archivo no se puede cargar.
        """
        if not data_path.exists():
            raise FileNotFoundError(f"No existe el archivo {data_path}")
        size = data_path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(
                f"El archivo pesa {size / 1024 / 1024:.1f} MB y el máximo es "
                f"{MAX_FILE_BYTES // 1024 // 1024} MB."
            )
        self.timeout = timeout
        self.workdir = workdir if workdir is not None else new_session_dir()
        self.display_name = display_name or data_path.name
        self.max_chart_points = max_chart_points
        self.definitions: list[ToolDefinition] = [INSPECT_DATA, RUN_PYTHON, CREATE_CHART]
        # La app nunca lee el archivo subido: el proceso aislado lo carga y lo normaliza.
        source = _copy_into_workdir(data_path, self.workdir)
        self.load_info = _prepare_in_sandbox(source, self.workdir, sheet, self.display_name)
        self.sheet: str | None = self.load_info["sheet"]
        self.table: str = self.load_info["table"]
        self.data_path = self.workdir / self.load_info["parquet"]
        # Hasta la capa 2, el código del modelo puede escribir en su carpeta: se guarda una
        # copia en memoria (fuera de su alcance) para detectar y deshacer cambios a los datos.
        self._originals = {
            rel: (self.workdir / rel).read_bytes()
            for rel in (self.load_info["parquet"], self.load_info["catalog"])
        }
        self._hashes = {
            rel: hashlib.sha256(data).hexdigest() for rel, data in self._originals.items()
        }
        self.restorations = 0  # veces que hubo que restaurar los datos

    def preview(self) -> pd.DataFrame:
        """Primeras filas tal como las ve el agente (las escribió el cargador, en el sandbox)."""
        return pd.read_json(
            io.StringIO(self.load_info["preview"]),
            orient="split",
            dtype=False,
            convert_dates=False,
        )

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Ejecuta la herramienta `name` y devuelve su resultado."""
        if INVALID_ARGUMENTS_KEY in arguments:
            raw = arguments[INVALID_ARGUMENTS_KEY]
            return _error(f"Error: los argumentos no son un objeto JSON válido: {raw!r}")
        if name == "inspect_data":
            return ToolResult(self.inspect_data(), status="info")
        if name in ("run_python", "create_chart"):
            code = arguments.get("code")
            if not isinstance(code, str) or not code.strip():
                return _error(f"Error: {name} necesita el argumento 'code' con código Python.")
            return self._run_python(code) if name == "run_python" else self.create_chart(code)
        names = ", ".join(d.name for d in self.definitions)
        return _error(f"Error: herramienta desconocida {name!r}. Disponibles: {names}.")

    def inspect_data(self) -> str:
        result, notice = self._guarded_run(_INSPECT_CODE)
        if failure := self._stopped_message(result):
            return _with_notice(failure, notice)
        if not result.ok:
            return _with_notice(
                f"Error al inspeccionar los datos:\n{result.stderr.strip()}", notice
            )
        text = truncate("\n".join([*self._load_summary(), "", result.stdout.strip()]))
        return _with_notice(text, notice)

    def _guarded_run(self, code: str, **kwargs: Any) -> tuple[ExecutionResult, str]:
        """Ejecuta en el sandbox comprobando antes y después que los datos no cambiaron."""
        notices = []
        if self._restore_data():
            notices.append(DATA_RESTORED_BEFORE)
        result = run_code(code, self.data_path, self.timeout, self.workdir, **kwargs)
        if self._restore_data():
            notices.append(DATA_RESTORED_AFTER)
        return result, "\n".join(notices)

    def _restore_data(self) -> bool:
        """Si el Parquet o el catálogo cambiaron desde la carga, restaura los originales."""
        changed = [
            rel for rel, digest in self._hashes.items() if _sha256(self.workdir / rel) != digest
        ]
        if not changed:
            return False
        data_dir = self.workdir / loading.DATA_DIR
        # Nunca se escribe a través de un enlace: podría apuntar a un archivo fuera de la sesión.
        if data_dir.is_symlink() or (data_dir.exists() and not data_dir.is_dir()):
            data_dir.unlink()
        data_dir.mkdir(exist_ok=True)
        for rel in changed:
            path = self.workdir / rel
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            path.write_bytes(self._originals[rel])
        self.restorations += 1
        return True

    def _load_summary(self) -> list[str]:
        """Cómo se leyó el archivo: formato, hojas y columnas que quedaron como texto."""
        info = self.load_info
        lines = [f"Archivo: {self.display_name}"]
        if info["sheets"]:
            sheets = ", ".join(
                f"{name} (en uso)" if name == info["sheet"] else name for name in info["sheets"]
            )
            lines.append(f"Hojas del Excel: {sheets}.")
            if len(info["sheets"]) > 1:
                lines.append(
                    "Solo se analiza la hoja en uso. Para otra hoja, el usuario debe elegirla "
                    "(en la barra lateral de la app o con --hoja en la terminal)."
                )
        else:
            separator = "tabulador" if info["separator"] == "\t" else repr(info["separator"])
            lines.append(
                f"Formato detectado: codificación {info['encoding']}, separador {separator}, "
                f"decimal {info['decimal']!r}, miles {info['thousands']!r}."
            )
        if info["text_columns"]:
            lines.append("Columnas leídas como texto a propósito (no se modificó ningún valor):")
            lines += [f"- {col!r}: {reason}" for col, reason in info["text_columns"].items()]
        return lines

    def run_python(self, code: str) -> str:
        return self._run_python(code).text

    def _run_python(self, code: str) -> ToolResult:
        result, notice = self._guarded_run(code)
        return _add_notice(self._code_result(result), notice)

    def _code_result(self, result: ExecutionResult) -> ToolResult:
        if failure := self._stopped_message(result):
            return _error(failure)
        if not result.ok:
            return _error(truncate(f"Error al ejecutar el código:\n{result.stderr.strip()}"))
        output = result.stdout.strip()
        return ToolResult(
            truncate(output) if output else "(El código no imprimió nada. Usa print().)"
        )

    def create_chart(self, code: str) -> ToolResult:
        chart_path = self.workdir / "charts" / f"{uuid.uuid4().hex}.json"
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        result, notice = self._guarded_run(
            code, chart_path=chart_path, max_points=self.max_chart_points
        )
        return _add_notice(self._chart_result(result, chart_path), notice)

    def _chart_result(self, result: ExecutionResult, chart_path: Path) -> ToolResult:
        if failure := self._stopped_message(result):
            return _error(failure)
        if result.chart_invalid:
            return _error(f"Error en la gráfica: {result.stderr.strip()}")
        if not result.ok:
            return _error(truncate(f"Error al ejecutar el código:\n{result.stderr.strip()}"))

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

    def _stopped_message(self, result: ExecutionResult) -> str | None:
        """Mensaje si el sandbox detuvo el proceso (tiempo o salida excesiva)."""
        if result.timed_out:
            return f"Error: el código superó el tiempo máximo de {self.timeout:g} s y se detuvo."
        if result.output_exceeded:
            return (
                f"Error: el código imprimió más de {MAX_OUTPUT_BYTES // 1_000_000} MB y se "
                "detuvo. Imprime solo lo necesario o agrega los datos antes."
            )
        return None


def _error(text: str) -> ToolResult:
    return ToolResult(text, status="error")


def _with_notice(text: str, notice: str) -> str:
    return f"{text}\n{notice}" if notice else text


def _add_notice(result: ToolResult, notice: str) -> ToolResult:
    result.text = _with_notice(result.text, notice)
    return result


def _sha256(path: Path) -> str | None:
    """Hash del archivo, o None si no existe o no es un archivo normal."""
    if path.is_symlink() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_in_sandbox(
    source: Path, workdir: Path, sheet: str | None, display_name: str
) -> dict[str, Any]:
    """Carga y normaliza el archivo en un proceso aislado (ver loading.py)."""
    program = Path(loading.__file__).read_text(encoding="utf-8")
    args = [str(source.resolve()), str(workdir.resolve()), sheet or "", display_name]
    result = run_program(program, args, stdin="", timeout=LOAD_TIMEOUT, workdir=workdir)
    if result.timed_out:
        raise LoadError(f"La carga del archivo superó {LOAD_TIMEOUT:g} s y se detuvo.")
    try:
        outcome = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LoadError("No se pudo leer el archivo.") from exc
    if not outcome["ok"]:
        raise LoadError(outcome["error"])
    return outcome["info"]


def _copy_into_workdir(data_path: Path, workdir: Path) -> Path:
    """Copia el dataset a la carpeta de la sesión, salvo que ya esté ahí."""
    workdir.mkdir(parents=True, exist_ok=True)
    if data_path.resolve().parent == workdir.resolve():
        return data_path
    target = workdir / f"datos{data_path.suffix.lower()}"
    shutil.copyfile(data_path, target)
    return target
