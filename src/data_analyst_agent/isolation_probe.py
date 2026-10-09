"""Sondeo del aislamiento disponible para el sandbox (Fase 3).

Detecta qué mecanismos del sistema se pueden usar para aislar el código generado: Landlock,
seccomp, libseccomp, user namespaces y límites de memoria. Las pruebas que restringen al
proceso se ejecutan en procesos hijos, para no afectar a quien llama.

Solo usa la librería estándar, para poder ejecutarse en cualquier entorno.

Uso: python -m data_analyst_agent.isolation_probe [--json]
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from typing import Any

FUNCIONA = "funciona"

# Las pruebas usan los números de syscall de Landlock (444-446), que son iguales en x86_64
# y aarch64, y prctl para seccomp (PR_SET_NO_NEW_PRIVS=38, PR_SET_SECCOMP=22).

_LANDLOCK_FS_TEST = """
import ctypes, sys
libc = ctypes.CDLL(None, use_errno=True)

class Attr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]

attr = Attr(1 << 2)  # LANDLOCK_ACCESS_FS_READ_FILE, sin reglas: no se puede leer nada
fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
if fd < 0:
    print(f"no disponible (errno {ctypes.get_errno()})"); sys.exit()
libc.prctl(38, 1, 0, 0, 0)
if libc.syscall(446, fd, 0) < 0:
    print(f"no se pudo aplicar (errno {ctypes.get_errno()})"); sys.exit()
try:
    open(sys.executable, "rb").read(1)
    print("NO aplicado: se pudo leer un archivo prohibido")
except PermissionError:
    print("funciona")
"""

_LANDLOCK_NET_TEST = """
import ctypes, socket, sys
libc = ctypes.CDLL(None, use_errno=True)

class Attr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]

attr = Attr(0, 1 << 1)  # LANDLOCK_ACCESS_NET_CONNECT_TCP (ABI 4+), sin reglas
fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
if fd < 0:
    print(f"no disponible (errno {ctypes.get_errno()})"); sys.exit()
libc.prctl(38, 1, 0, 0, 0)
if libc.syscall(446, fd, 0) < 0:
    print(f"no se pudo aplicar (errno {ctypes.get_errno()})"); sys.exit()
s = socket.socket()
s.settimeout(2)
try:
    s.connect(("127.0.0.1", 9))
    print("NO aplicado: conectó")
except PermissionError:
    print("funciona")
except OSError as exc:
    print(f"NO aplicado: {type(exc).__name__}")
"""

_SECCOMP_TEST = """
import ctypes, platform, socket, sys
nr = {"x86_64": 41, "aarch64": 198}.get(platform.machine())  # syscall socket()
if nr is None:
    print(f"arquitectura no soportada: {platform.machine()}"); sys.exit()

class Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8),
                ("k", ctypes.c_uint32)]

class Prog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(Filter))]

program = (Filter * 4)(
    Filter(0x20, 0, 0, 0),             # cargar el número de syscall
    Filter(0x15, 0, 1, nr),            # si es socket()...
    Filter(0x06, 0, 0, 0x00050000 | 1),  # ...devolver EPERM
    Filter(0x06, 0, 0, 0x7FFF0000),    # el resto, permitir
)
prog = Prog(4, ctypes.cast(program, ctypes.POINTER(Filter)))
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(38, 1, 0, 0, 0) != 0:
    print(f"no_new_privs falló (errno {ctypes.get_errno()})"); sys.exit()
if libc.prctl(22, 2, ctypes.byref(prog), 0, 0) != 0:
    print(f"no se pudo instalar (errno {ctypes.get_errno()})"); sys.exit()
try:
    socket.socket()
    print("NO aplicado: se creó el socket")
except PermissionError:
    print("funciona")
"""

_UNSHARE_TEST = """
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
result = libc.unshare(0x10000000)  # CLONE_NEWUSER
print("permitido" if result == 0 else f"bloqueado (errno {ctypes.get_errno()})")
"""

# Comprueba si un límite de memoria de 1 GB rompe la importación de las librerías numéricas.
_RLIMIT_TEST = """
import resource
limit = 1024 ** 3
resource.setrlimit(resource.__LIMIT__, (limit, limit))
results = []
for module in ("numpy", "pandas", "pyarrow"):
    try:
        __import__(module)
        results.append(f"{module}: ok")
    except ModuleNotFoundError:
        results.append(f"{module}: no instalado")
    except Exception as exc:
        results.append(f"{module}: falla ({type(exc).__name__}: {exc})")
try:
    import numpy as np
    np.ones(25_000_000).sum()  # 200 MB
    results.append("reservar 200 MB: ok")
except Exception as exc:
    results.append(f"reservar 200 MB: falla ({type(exc).__name__})")
print("; ".join(results))
"""


def run_probe() -> dict[str, Any]:
    """Ejecuta todas las comprobaciones y devuelve un informe."""
    report: dict[str, Any] = {"sistema": _system_info()}
    if sys.platform.startswith("linux"):
        report["linux"] = {
            "landlock_abi": _landlock_abi(),
            "landlock_archivos": _in_child(_LANDLOCK_FS_TEST),
            "landlock_red": _in_child(_LANDLOCK_NET_TEST),
            "seccomp_filtro": _in_child(_SECCOMP_TEST),
            "libseccomp": _libseccomp(),
            "user_namespaces": _in_child(_UNSHARE_TEST),
            "estado_proceso": _proc_status(),
            "limites": _rlimits(),
            "memoria_cgroup": _read("/sys/fs/cgroup/memory.max"),
            "lsm_activos": _read("/sys/kernel/security/lsm"),
            "rlimit_as_1gb": _in_child(_RLIMIT_TEST.replace("__LIMIT__", "RLIMIT_AS")),
            "rlimit_data_1gb": _in_child(_RLIMIT_TEST.replace("__LIMIT__", "RLIMIT_DATA")),
        }
    report["herramientas"] = {
        name: shutil.which(name) or "no encontrada" for name in ("bwrap", "nsjail", "node", "deno")
    }
    report["red_saliente"] = _egress()
    report["nivel"] = _level(report)
    return report


def format_markdown(report: dict[str, Any]) -> str:
    level = report["nivel"]
    lines = ["## Sondeo de aislamiento", "", f"**Nivel:** {level['nivel']}", ""]
    for section, values in report.items():
        if section == "nivel" or not isinstance(values, dict):
            continue
        lines += [f"### {section}", "", "| Comprobación | Resultado |", "|---|---|"]
        for key, value in values.items():
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            lines.append(f"| {key} | {str(text).replace('|', '/')} |")
        lines.append("")
    lines += [f"**Red saliente:** {report['red_saliente']}", ""]
    return "\n".join(lines)


def _level(report: dict[str, Any]) -> dict[str, Any]:
    linux = report.get("linux")
    if linux is None:
        return {
            "nivel": f"solo desarrollo ({platform.system()}: sin Landlock ni seccomp)",
            "suficiente": False,
        }
    files = linux["landlock_archivos"] == FUNCIONA
    syscalls = linux["seccomp_filtro"] == FUNCIONA
    if files and syscalls:
        network = " y red por Landlock" if linux["landlock_red"] == FUNCIONA else ""
        return {"nivel": f"fuerte: Landlock (archivos{network}) + seccomp", "suficiente": True}
    if syscalls:
        text = "parcial: seccomp sin Landlock (archivos sin protección del kernel)"
    elif files:
        text = "parcial: Landlock sin seccomp (procesos y red sin protección del kernel)"
    else:
        text = "insuficiente: ni Landlock ni seccomp"
    return {"nivel": f"{text}. La app cerraría; evaluar el plan B (Pyodide)", "suficiente": False}


def _in_child(code: str) -> str:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "error: tiempo agotado"
    if proc.stdout.strip():
        return proc.stdout.strip()
    last_error = proc.stderr.strip().splitlines()[-1:] or [f"código {proc.returncode}"]
    return f"error: {last_error[0]}"


def _system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "sistema": platform.system(),
        "kernel": platform.release(),
        "arquitectura": platform.machine(),
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
    }
    if hasattr(os, "getuid"):
        info["uid"] = os.getuid()
    if sys.platform.startswith("linux"):
        info["distribucion"] = _os_release()
        cgroup = _read("/proc/1/cgroup")
        markers = ("docker", "kubepods", "containerd")
        info["contenedor"] = os.path.exists("/.dockerenv") or any(m in cgroup for m in markers)
    return info


def _landlock_abi() -> str:
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, None, 0, 1)  # LANDLOCK_CREATE_RULESET_VERSION
    return str(abi) if abi >= 0 else f"no disponible (errno {ctypes.get_errno()})"


def _libseccomp() -> str:
    name = ctypes.util.find_library("seccomp")
    if not name:
        return "no encontrada"
    try:
        lib = ctypes.CDLL(name)

        class Version(ctypes.Structure):
            _fields_ = [(field, ctypes.c_uint) for field in ("major", "minor", "micro")]

        lib.seccomp_version.restype = ctypes.POINTER(Version)
        version = lib.seccomp_version().contents
        return f"{version.major}.{version.minor}.{version.micro} ({name})"
    except (OSError, AttributeError) as exc:
        return f"encontrada ({name}) pero no se pudo cargar: {exc}"


def _proc_status() -> dict[str, str]:
    wanted = ("Seccomp", "Seccomp_filters", "NoNewPrivs", "CapEff")
    status = {}
    for line in _read("/proc/self/status").splitlines():
        key, _, value = line.partition(":")
        if key in wanted:
            status[key] = value.strip()
    return status


def _rlimits() -> dict[str, str]:
    import resource  # solo existe en Unix

    def show(value: int) -> str:
        return "sin límite" if value == resource.RLIM_INFINITY else str(value)

    limits = {}
    for name in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_NPROC", "RLIMIT_NOFILE", "RLIMIT_FSIZE"):
        soft, hard = resource.getrlimit(getattr(resource, name))
        limits[name] = f"{show(soft)} / {show(hard)}"
    return limits


def _egress() -> str:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return "permitida"
    except OSError as exc:
        return f"bloqueada ({type(exc).__name__})"


def _os_release() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return "desconocida"


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as file:
            return file.read().strip()
    except OSError as exc:
        return f"no legible ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sondeo del aislamiento disponible.")
    parser.add_argument("--json", action="store_true", help="salida en JSON en vez de Markdown")
    args = parser.parse_args(argv)
    report = run_probe()
    print(
        json.dumps(report, indent=2, ensure_ascii=False) if args.json else format_markdown(report)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
