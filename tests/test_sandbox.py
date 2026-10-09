"""Tests del sandbox: carpetas de sesión y capa 0 de aislamiento."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from data_analyst_agent import sandbox
from data_analyst_agent.sandbox import new_session_dir, remove_session_dir
from data_analyst_agent.tools import DataTools

CANARY = "canario-secreto-123"


def test_each_session_gets_its_own_dir(tmp_path: Path) -> None:
    first = new_session_dir(tmp_path)
    second = new_session_dir(tmp_path)
    assert first != second
    assert first.is_dir() and second.is_dir()


def test_remove_session_dir_deletes_contents(tmp_path: Path) -> None:
    session = new_session_dir(tmp_path)
    (session / "datos.csv").write_text("a\n1\n", encoding="utf-8")
    remove_session_dir(session, tmp_path)
    assert not session.exists()


def test_remove_session_dir_refuses_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "raiz"
    root.mkdir()
    with pytest.raises(ValueError):
        remove_session_dir(tmp_path, root)


# --- Capa 0: entorno limpio, salida limitada, árbol de procesos y concurrencia ---


@pytest.fixture
def tools(tmp_path: Path) -> DataTools:
    csv = tmp_path / "ventas.csv"
    csv.write_text("region,unidades\nNorte,3\nSur,5\n", encoding="utf-8")
    return DataTools(csv, timeout=20, workdir=tmp_path / "sesion")


def _same_path(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def test_child_does_not_inherit_secrets(tools: DataTools, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", CANARY)
    monkeypatch.setenv("GEMINI_API_KEY", CANARY)
    monkeypatch.setenv("OTRO_TOKEN", CANARY)
    output = tools.run_python("import os, json\nprint(json.dumps(dict(os.environ)))")

    env = json.loads(output)
    assert CANARY not in output
    assert not {"GROQ_API_KEY", "GEMINI_API_KEY", "OTRO_TOKEN"} & env.keys()


def test_home_and_temp_point_to_session_dir(tools: DataTools) -> None:
    code = (
        "import os, tempfile, json\n"
        "print(json.dumps([os.path.expanduser('~'), tempfile.gettempdir(),"
        " os.environ['TEMP'], os.environ['TMP']]))"
    )
    paths = json.loads(tools.run_python(code))
    assert all(_same_path(path, tools.workdir) for path in paths)


def test_child_only_gets_a_copy_of_the_dataset(tools: DataTools, tmp_path: Path) -> None:
    assert tools.data_path.parent == tools.workdir
    child_path = tools.run_python("import sys\nprint(sys.argv[1])")
    assert _same_path(child_path, tools.data_path)
    assert not _same_path(child_path, tmp_path / "ventas.csv")


def test_output_flood_is_stopped(tools: DataTools) -> None:
    start = time.monotonic()
    output = tools.run_python("while True:\n    print('x' * 1000)")
    assert "imprimió más de 1 MB" in output
    assert time.monotonic() - start < 15  # se detuvo por la salida, no por el tiempo máximo


def test_timeout_kills_grandchildren(tools: DataTools) -> None:
    marker = tools.workdir / "nieto_vivo.txt"
    grandchild = (
        f"import time, pathlib; time.sleep(4); pathlib.Path({str(marker)!r}).write_text('vivo')"
    )
    code = (
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "while True:\n    pass"
    )
    tools.timeout = 4
    assert "tiempo máximo" in tools.run_python(code)
    time.sleep(5)
    assert not marker.exists()


def test_concurrent_executions_are_limited(
    tools: DataTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "_slots", threading.BoundedSemaphore(1))
    code = "import time\nstart = time.time()\ntime.sleep(1)\nprint(start, time.time())"
    outputs: list[str] = []
    threads = [
        threading.Thread(target=lambda: outputs.append(tools.run_python(code))) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    (_, end_a), (start_b, _) = sorted(tuple(map(float, o.split())) for o in outputs)
    assert end_a <= start_b  # la segunda empezó cuando terminó la primera


def test_python_executable_is_the_project_one(tools: DataTools) -> None:
    assert _same_path(tools.run_python("import sys\nprint(sys.executable)"), Path(sys.executable))
