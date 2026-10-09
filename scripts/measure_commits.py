"""Mide los mismos casos en dos commits (antes y después de una entrega) y los compara.

Cada commit se ejecuta en un git worktree temporal, con su propio código, y los resultados
quedan en evals/results/<etiqueta>-antes.jsonl y <etiqueta>-despues.jsonl. Si la corrida se
corta (por ejemplo, por cupo agotado), vuelve a ejecutar el mismo comando: retoma donde iba.

Uso (desde la raíz del proyecto):
    python scripts/measure_commits.py --label entregaE --before e847516 --after cbd08ed \
        --repeat 3 -- --ids t-enc-04,qa-hur-01
    python scripts/measure_commits.py ... --dry-run     # solo lista los casos, sin el modelo

Lo que va después de `--` se pasa tal cual a evals/run_evals.py (selección de casos).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
WORKTREES = Path(tempfile.gettempdir()) / "data-analyst-agent-worktrees"
# Archivos que no están en git pero que los casos necesitan.
UNTRACKED_DATA = ("data/real",)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="nombre de la medición (p. ej. entregaE)")
    parser.add_argument("--before", required=True, help="commit de antes")
    parser.add_argument("--after", required=True, help="commit de después")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="solo lista los casos")
    parser.add_argument("--keep", action="store_true", help="no borra los worktrees al final")
    args, selection = parser.parse_known_args(argv)
    selection = [arg for arg in selection if arg != "--"]

    # Las claves se cargan en el entorno de este proceso y las heredan las corridas; nunca se
    # muestran ni se copian al worktree.
    load_dotenv(ROOT / ".env")
    outputs = {}
    for side, revision in (("antes", args.before), ("despues", args.after)):
        tree = _worktree(f"{args.label}-{side}", revision)
        output = RESULTS_DIR / f"{args.label}-{side}.jsonl"
        outputs[side] = output
        command = [sys.executable, "-X", "utf8", str(tree / "evals" / "run_evals.py"), *selection]
        if args.dry_run:
            command.append("--list")
        else:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            mode = "--resume" if output.exists() else "--output"
            command += ["--repeat", str(args.repeat), mode, str(output)]
        print(f"\n=== {side}: {revision} ({_short(revision)}) ===", flush=True)
        env = {**os.environ, "PYTHONPATH": str(tree / "src")}  # el código de ese commit
        code = subprocess.run(command, cwd=tree, env=env, check=False).returncode
        if code == 2:
            print("\nCorrida cortada (por ejemplo, por cupo). Vuelve a ejecutar el mismo comando")
            print("más tarde: retomará sin repetir los casos ya terminados.")
            return 2
        if code != 0:
            print(f"\nLa corrida de '{side}' terminó con código {code}.")
            return code

    if not args.dry_run:
        print("\n=== Comparación ===", flush=True)
        compare = [sys.executable, "-X", "utf8", str(ROOT / "evals" / "run_evals.py"), "--compare"]
        subprocess.run([*compare, str(outputs["antes"]), str(outputs["despues"])], check=False)
    if not args.keep:
        for side in ("antes", "despues"):
            _remove_worktree(WORKTREES / f"{args.label}-{side}")
    return 0


def _worktree(name: str, revision: str) -> Path:
    """Crea (o reutiliza, si ya está en ese commit) un worktree con los datos no versionados."""
    tree = WORKTREES / name
    wanted = _git("rev-parse", revision)
    if tree.exists() and _git("rev-parse", "HEAD", cwd=tree) != wanted:
        _remove_worktree(tree)
    if not tree.exists():
        WORKTREES.mkdir(parents=True, exist_ok=True)
        _git("worktree", "add", "--detach", str(tree), wanted)
    for relative in UNTRACKED_DATA:
        source = ROOT / relative
        if source.exists():
            shutil.copytree(source, tree / relative, dirs_exist_ok=True)
    return tree


def _remove_worktree(tree: Path) -> None:
    if tree.exists():
        _git("worktree", "remove", "--force", str(tree))


def _short(revision: str) -> str:
    return _git("log", "-1", "--format=%h %s", revision)


def _git(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
