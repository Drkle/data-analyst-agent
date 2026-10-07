"""Ejecución de código generado en un proceso aparte. (Fase 1 simple, Fase 3 segura)

Hoy: proceso separado, timeout y directorio de trabajo acotado.
Pendiente (Fase 3): bloqueo de red, de imports peligrosos y de archivos fuera del área.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Programa que corre en el proceso hijo: carga el dataset en `df` y ejecuta el código
# recibido por stdin. El traceback omite el marco del propio runner.
_RUNNER = """
import sys
import traceback

import pandas as pd

path = sys.argv[1]
df = pd.read_excel(path) if path.lower().endswith(".xlsx") else pd.read_csv(path)
code = sys.stdin.read()
try:
    exec(compile(code, "<codigo>", "exec"), {"__name__": "__main__", "pd": pd, "df": df})
except Exception as exc:
    traceback.print_exception(type(exc), exc, exc.__traceback__.tb_next)
    sys.exit(1)
"""


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int | None = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def run_code(code: str, data_path: Path, timeout: float, workdir: Path) -> ExecutionResult:
    """Ejecuta `code` con el dataset de `data_path` cargado en `df`."""
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-c", _RUNNER, str(data_path.resolve())],
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


def _as_text(output: str | bytes | None) -> str:
    # TimeoutExpired puede traer bytes aunque el proceso se lanzara en modo texto.
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""
