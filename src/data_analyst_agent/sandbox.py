"""Ejecución de código generado en un proceso aparte.

Capa 0 (Windows y Linux):
- Entorno mínimo: el hijo no hereda variables del padre (ni API keys); HOME, TEMP y TMP
  apuntan a la carpeta de la sesión.
- Salida limitada a MAX_OUTPUT_BYTES por flujo; si se supera, el proceso se detiene.
- Al vencer el tiempo se mata todo el árbol de procesos, no solo el hijo.
- Como máximo MAX_CONCURRENT ejecuciones simultáneas en el servidor.
Pendiente (Fase 3): audit hooks (capa 1) y Landlock/seccomp/límites de recursos (capa 2).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO

WORKSPACE_ROOT = Path("sandbox_workspace")
MAX_OUTPUT_BYTES = 1_000_000
MAX_CONCURRENT = 2
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_READ_CHUNK = 65_536

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
# El dataset ya viene normalizado en Parquet (ver loading.py); CSV/XLSX quedan por si acaso.
if data_path.lower().endswith(".parquet"):
    df = pd.read_parquet(data_path)
elif data_path.lower().endswith(".xlsx"):
    df = pd.read_excel(data_path)
else:
    df = pd.read_csv(data_path)
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
    output_exceeded: bool = False  # superó MAX_OUTPUT_BYTES y se detuvo

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.output_exceeded and self.returncode == 0

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
    chart_arg = str(chart_path.resolve()) if chart_path else ""
    args = [str(data_path.resolve()), chart_arg, str(max_points)]
    return run_program(_RUNNER, args, stdin=code, timeout=timeout, workdir=workdir)


def run_program(
    program: str, args: list[str], stdin: str, timeout: float, workdir: Path
) -> ExecutionResult:
    """Ejecuta el código fuente `program` en un proceso aislado (capa 0), con `args` en
    sys.argv[1:] y `stdin` como entrada estándar."""
    workdir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-I", "-X", "utf8", "-c", program, *args]
    with _slots:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=child_env(workdir),
            # Grupo de procesos propio, para poder matar también a los nietos.
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        exceeded = threading.Event()
        stdout = _CappedReader(proc, proc.stdout, exceeded)
        stderr = _CappedReader(proc, proc.stderr, exceeded)
        try:
            assert proc.stdin is not None
            proc.stdin.write(stdin.encode("utf-8"))
            proc.stdin.close()
        except OSError:  # el hijo terminó antes de leer el código
            pass
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree(proc)
            proc.wait()
        stdout.join()
        stderr.join()
    return ExecutionResult(
        stdout=stdout.text(),
        stderr=stderr.text(),
        returncode=None if timed_out else proc.returncode,
        timed_out=timed_out,
        output_exceeded=exceeded.is_set(),
    )


def child_env(workdir: Path) -> dict[str, str]:
    """Entorno mínimo del hijo: nada del padre salvo lo imprescindible para arrancar."""
    home = str(workdir.resolve())
    env = {
        "HOME": home,
        "TEMP": home,
        "TMP": home,
        "TMPDIR": home,
        # Un solo hilo en las librerías numéricas: menos CPU compartida y menos memoria.
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env.update(
            SYSTEMROOT=system_root,
            USERPROFILE=home,
            PATH=str(Path(system_root) / "System32"),
        )
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Mata el hijo y todos los procesos que haya creado."""
    try:
        if os.name == "nt":
            taskkill = (
                Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            subprocess.run(
                [str(taskkill), "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    proc.kill()


class _CappedReader:
    """Lee un flujo del hijo en segundo plano y lo detiene si supera MAX_OUTPUT_BYTES."""

    def __init__(
        self, proc: subprocess.Popen[bytes], stream: IO[bytes] | None, exceeded: threading.Event
    ) -> None:
        self._proc = proc
        self._stream = stream
        self._exceeded = exceeded
        self._chunks: list[bytes] = []
        self._size = 0
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._stream is not None
        while chunk := self._stream.read1(_READ_CHUNK):
            if self._size < MAX_OUTPUT_BYTES:
                self._chunks.append(chunk[: MAX_OUTPUT_BYTES - self._size])
            self._size += len(chunk)
            if self._size > MAX_OUTPUT_BYTES and not self._exceeded.is_set():
                self._exceeded.set()
                kill_process_tree(self._proc)

    def join(self) -> None:
        self._thread.join()

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


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
