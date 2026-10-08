"""Ejecución de código generado en un proceso aparte. (Fase 1 simple, Fase 3 segura)

Hoy: proceso separado, timeout y una carpeta de trabajo por sesión.
Pendiente (Fase 3): bloqueo de red, de imports peligrosos y de archivos fuera del área.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_ROOT = Path("sandbox_workspace")

# Código de salida del proceso hijo cuando la gráfica no pasa la validación.
CHART_INVALID_EXIT = 2

# Programa que corre en el proceso hijo. Argumentos: ruta del dataset, ruta donde guardar
# la gráfica ("" si no se pide gráfica) y máximo de puntos permitidos en la gráfica.
_RUNNER = """
import json
import sys
import traceback

import pandas as pd

# Que pandas no oculte filas ni columnas con "...": el recorte lo hace el host y lo avisa.
pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 200)

data_path, chart_path, max_points = sys.argv[1], sys.argv[2], int(sys.argv[3])
df = pd.read_excel(data_path) if data_path.lower().endswith(".xlsx") else pd.read_csv(data_path)
namespace = {"__name__": "__main__", "pd": pd, "df": df}
if chart_path:
    import plotly.express as px
    import plotly.graph_objects as go

    namespace.update(px=px, go=go)

code = sys.stdin.read()
try:
    exec(compile(code, "<codigo>", "exec"), namespace)
except Exception as exc:
    traceback.print_exception(type(exc), exc, exc.__traceback__.tb_next)
    sys.exit(1)


def invalid(message):
    print(message, file=sys.stderr)
    sys.exit(CHART_INVALID_EXIT)


def count_points(fig):
    total = 0
    for trace in fig.data:
        for attr in ("x", "y", "values", "z"):
            value = getattr(trace, attr, None)
            if value is not None:
                total += int(pd.DataFrame(value).size) if attr == "z" else len(value)
                break
    return total


if chart_path:
    fig = namespace.get("fig")
    if fig is None:
        invalid("El código debe asignar la gráfica a la variable `fig`.")
    if not isinstance(fig, go.Figure):
        invalid(
            "`fig` debe ser una figura de Plotly (plotly.graph_objects.Figure), "
            f"no {type(fig).__name__}."
        )
    if not fig.data:
        invalid("La figura no tiene datos.")
    points = count_points(fig)
    if points > max_points:
        invalid(
            f"La gráfica tiene {points} puntos y el máximo es {max_points}. "
            "Agrega los datos (por ejemplo con groupby o resample) antes de graficar."
        )
    info = {
        "figure": fig.to_json(),
        "types": sorted({trace.type for trace in fig.data}),
        "x": fig.layout.xaxis.title.text,
        "y": fig.layout.yaxis.title.text,
        "title": fig.layout.title.text,
        "points": points,
    }
    with open(chart_path, "w", encoding="utf-8") as f:
        json.dump(info, f)
""".replace("CHART_INVALID_EXIT", str(CHART_INVALID_EXIT))


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int | None = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0

    @property
    def chart_invalid(self) -> bool:
        return self.returncode == CHART_INVALID_EXIT


def run_code(
    code: str,
    data_path: Path,
    timeout: float,
    workdir: Path,
    chart_path: Path | None = None,
    max_points: int = 0,
) -> ExecutionResult:
    """Ejecuta `code` con el dataset de `data_path` cargado en `df`.

    Con `chart_path`, el código debe crear `fig`; si es válida se guarda en ese archivo.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    chart_arg = str(chart_path.resolve()) if chart_path else ""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-X",
                "utf8",
                "-c",
                _RUNNER,
                str(data_path.resolve()),
                chart_arg,
                str(max_points),
            ],
            input=code,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=workdir,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            returncode=None,
            timed_out=True,
        )
    return ExecutionResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def new_session_dir(root: Path = WORKSPACE_ROOT) -> Path:
    """Crea una carpeta de trabajo vacía con un id único para una sesión."""
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


def remove_session_dir(path: Path, root: Path = WORKSPACE_ROOT) -> None:
    """Borra la carpeta de una sesión. Solo acepta carpetas directamente dentro de `root`."""
    target = path.resolve()
    if target.parent != root.resolve():
        raise ValueError(f"{path} no es una carpeta de sesión dentro de {root}")
    shutil.rmtree(target, ignore_errors=True)


def _as_text(output: str | bytes | None) -> str:
    # TimeoutExpired puede traer bytes aunque el proceso se lanzara en modo texto.
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""
