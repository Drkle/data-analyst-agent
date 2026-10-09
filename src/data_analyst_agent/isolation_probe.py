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


# bubblewrap de verdad: crea los namespaces y monta solo Python y la carpeta de la sesión
# (con data/ en solo lectura). Dentro comprueba qué se puede y qué no.
_BWRAP_TEST = r"""
import json, os, shutil, subprocess, sys, tempfile
bwrap = shutil.which("bwrap")
if not bwrap:
    print("no instalado"); sys.exit()
import pandas as pd
base = tempfile.mkdtemp()
session = os.path.join(base, "sesion")
data = os.path.join(session, "data")
os.makedirs(data)
pd.DataFrame({"a": [1, 2, 3]}).to_parquet(os.path.join(data, "t.parquet"))
outside = os.path.join(base, "fuera_de_la_sesion.txt")
with open(outside, "w") as f:
    f.write("secreto")
inner = '''
import json, socket
r = {}
import pandas as pd
r["lee_datos"] = int(pd.read_parquet("data/t.parquet")["a"].sum()) == 6
def blocked(action):
    try:
        action()
        return False
    except OSError:
        return True
r["escribe_en_sesion"] = not blocked(lambda: open("salida.txt", "w").write("ok"))
r["bloquea_escritura_en_data"] = blocked(lambda: open("data/x.txt", "w").write("x"))
r["bloquea_archivo_externo"] = blocked(lambda: open(OUTSIDE).read())
r["bloquea_etc_passwd"] = blocked(lambda: open("/etc/passwd").read())
r["bloquea_red"] = blocked(lambda: socket.create_connection(("1.1.1.1", 443), timeout=3))
print(json.dumps(r))
'''.replace("OUTSIDE", repr(outside))
mounts = [
    "--die-with-parent", "--new-session",
    "--ro-bind", "/usr", "/usr",
    "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
    "--symlink", "usr/bin", "/bin",
    "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
    "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--bind", session, "/sesion", "--ro-bind", data, "/sesion/data",
    "--chdir", "/sesion", "--clearenv", "--setenv", "HOME", "/sesion",
]
for prefix in sorted({os.path.realpath(p) for p in (sys.prefix, sys.base_prefix)}):
    if not prefix.startswith("/usr"):
        mounts += ["--ro-bind", prefix, prefix]

def attempt(namespaces):
    proc = subprocess.run(
        [bwrap, *namespaces, *mounts, sys.executable, "-I", "-c", inner],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        error = (proc.stderr.strip().splitlines() or ["sin mensaje"])[-1]
        return f"falla al crear el sandbox: {error[:200]}"
    results = json.loads(proc.stdout.strip().splitlines()[-1])
    failed = [name for name, ok in results.items() if not ok]
    return "funciona" if not failed else f"incompleto: falla {', '.join(failed)}"

full = attempt(["--unshare-all"])
# Si no se pudo aislar la red (p. ej. el loopback), se prueba sin namespace de red: la red
# se puede cortar con seccomp, y lo importante es saber si el aislamiento de archivos sirve.
no_net = ["--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-uts",
          "--unshare-cgroup-try"]
partial = attempt(no_net) if full != "funciona" else "no hizo falta"
print(json.dumps({"completo": full, "sin_namespace_de_red": partial}, ensure_ascii=False))
"""

# seccomp sin apertura de archivos: precarga librerías y datos, deja abierto el descriptor de
# salida, niega open/openat/openat2/creat y prueba un análisis y gráficas normales.
_SECCOMP_NO_OPEN_TEST = r"""
import ctypes, json, os, platform, sys, tempfile
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
nrs = {
    "x86_64": [2, 257, 437, 85],   # open, openat, openat2, creat
    "aarch64": [56, 437],          # openat, openat2 (no tiene open ni creat)
}.get(platform.machine())
if nrs is None:
    print(f"arquitectura no soportada: {platform.machine()}"); sys.exit()
base = tempfile.mkdtemp()
path = os.path.join(base, "t.parquet")
pd.DataFrame({"cat": list("abcab"), "v": [1, 2, 3, 4, 5]}).to_parquet(path)
df = pd.read_parquet(path)
# Precarga amplia: operaciones y tipos de gráfica habituales, para que Python importe antes
# del filtro los módulos que cargaría sobre la marcha.
df["fecha"] = pd.to_datetime(pd.Series(["2025-01-01"] * 5)) + pd.to_timedelta(range(5), "D")
for warm in (
    lambda: df.describe(include="all").to_string(),
    lambda: df.groupby("cat")["v"].agg(["sum", "mean", "count", "median", "std"]).to_string(),
    lambda: df.pivot_table(index="cat", values="v", aggfunc="sum").to_string(),
    lambda: df.set_index("fecha")["v"].resample("D").sum().rolling(2).mean().to_string(),
    lambda: df.merge(df, on="cat").sort_values("v_x").value_counts().head().to_string(),
    lambda: df[["v"]].corr().round(2).to_string(),
    lambda: df["v"].quantile([0.25, 0.5]).to_string(),
    lambda: px.bar(df, x="cat", y="v").to_json(),
    lambda: px.line(df, x="fecha", y="v").to_json(),
    lambda: px.scatter(df, x="v", y="v").to_json(),
    lambda: px.pie(df, names="cat", values="v").to_json(),
    lambda: px.histogram(df, x="v").to_json(),
    lambda: px.box(df, y="v").to_json(),
    lambda: px.area(df, x="fecha", y="v").to_json(),
):
    warm()
out = open(os.path.join(base, "grafica.json"), "w")  # salida abierta antes del filtro

class Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8),
                ("k", ctypes.c_uint32)]

class Prog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(Filter))]

rules = [Filter(0x20, 0, 0, 0)]  # cargar el número de syscall
for i, nr in enumerate(nrs):
    rules.append(Filter(0x15, len(nrs) - i, 0, nr))  # si coincide, saltar a "denegar"
rules.append(Filter(0x06, 0, 0, 0x7FFF0000))         # permitir
rules.append(Filter(0x06, 0, 0, 0x00050000 | 1))     # denegar con EPERM
program = (Filter * len(rules))(*rules)
prog = Prog(len(rules), ctypes.cast(program, ctypes.POINTER(Filter)))
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(22, 2, ctypes.byref(prog), 0, 0) != 0:
    print(f"no se pudo instalar (errno {ctypes.get_errno()})"); sys.exit()

def attempt(action):
    try:
        action()
        return "ok"
    except Exception as exc:
        # El final del mensaje dice qué archivo (módulo) intentó abrir.
        return f"falla ({type(exc).__name__}: ...{str(exc)[-100:]})"

r = {
    "analisis": attempt(lambda: df.groupby("cat")["v"].agg(["sum", "mean"]).describe().to_string()),
    "analisis_no_precargado": attempt(lambda: df["v"].cumsum().pct_change().round(3).to_string()),
    "grafica_precargada": attempt(lambda: px.pie(df, names="cat", values="v").to_json()),
    "grafica_no_precargada": attempt(lambda: px.violin(df, y="v").to_json()),
    "escribe_en_salida_abierta": attempt(lambda: (out.write("{}"), out.flush())),
}
blocked = attempt(lambda: open("/etc/hostname").read())
r["bloquea_abrir_archivos"] = "ok" if "PermissionError" in blocked else f"NO ({blocked})"
print(json.dumps(r, ensure_ascii=False))
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
            "bwrap_sandbox": _json_child(_BWRAP_TEST),
            "seccomp_sin_open": _json_child(_SECCOMP_NO_OPEN_TEST),
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
    bwrap = linux.get("bwrap_sandbox")
    if syscalls and isinstance(bwrap, dict):
        if bwrap.get("completo") == FUNCIONA:
            return {"nivel": "fuerte: bubblewrap (namespaces) + seccomp", "suficiente": True}
        if bwrap.get("sin_namespace_de_red") == FUNCIONA:
            return {
                "nivel": "fuerte: bubblewrap (archivos) + seccomp (red y procesos)",
                "suficiente": True,
            }
    no_open = linux.get("seccomp_sin_open")
    preloaded = ("analisis", "grafica_precargada", "escribe_en_salida_abierta")
    if (
        syscalls
        and isinstance(no_open, dict)
        and all(no_open.get(key) == "ok" for key in (*preloaded, "bloquea_abrir_archivos"))
    ):
        return {
            "nivel": "suficiente: seccomp con precarga (sin abrir archivos tras cargar)",
            "suficiente": True,
        }
    if syscalls:
        text = "parcial: seccomp sin Landlock (archivos sin protección del kernel)"
    elif files:
        text = "parcial: Landlock sin seccomp (procesos y red sin protección del kernel)"
    else:
        text = "insuficiente: ni Landlock ni seccomp"
    return {"nivel": f"{text}. La app cerraría; evaluar el plan B (Pyodide)", "suficiente": False}


def _json_child(code: str) -> dict[str, str] | str:
    """Ejecuta una prueba que imprime un JSON; si imprime otra cosa (p. ej. 'no instalado'
    o un error), devuelve ese texto."""
    output = _in_child(code)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


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
    parser.add_argument(
        "--github",
        action="store_true",
        help="además, anotaciones de GitHub Actions (se leen sin iniciar sesión)",
    )
    args = parser.parse_args(argv)
    report = run_probe()
    print(
        json.dumps(report, indent=2, ensure_ascii=False) if args.json else format_markdown(report)
    )
    if args.github:
        print(github_annotation("Sondeo: nivel", report["nivel"]["nivel"]))
        for section in ("sistema", "linux", "herramientas"):
            if section in report:
                print(github_annotation(f"Sondeo: {section}", report[section]))
    return 0


def github_annotation(title: str, value: Any) -> str:
    """Línea ::notice:: de GitHub Actions; el mensaje va en una sola línea, escapado."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::notice title={title}::{text}"


if __name__ == "__main__":
    raise SystemExit(main())
