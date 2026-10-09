"""Ejecuta las evaluaciones del agente y reporta acierto, iteraciones y tokens.

Una corrida completa puede agotar el cupo diario gratuito de Groq: elige subconjuntos.

Ejemplos (desde la raíz del proyecto):
    python evals/run_evals.py --list                     # muestra los casos, sin llamar al modelo
    python evals/run_evals.py --qa all                   # casos que salen del informe de QA
    python evals/run_evals.py --qa S10,R6 --repeat 3     # algunos, repetidos 3 veces
    python evals/run_evals.py --ids q01,q02 --dataset ventas
    python evals/run_evals.py --resume evals/results/20261009-101500.jsonl
    python evals/run_evals.py --compare antes.jsonl despues.jsonl

Cada caso se guarda en un JSONL apenas termina. Si la corrida se corta (por ejemplo, por
cupo agotado), --resume la retoma sin repetir los casos ya terminados.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from data_analyst_agent.config import ConfigError, load_settings
from data_analyst_agent.evaluation import (
    FINISHED,
    load_cases,
    run_cases,
    select_cases,
    summarize,
)
from data_analyst_agent.llm import create_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [
    ROOT / "evals" / name
    for name in (
        "questions.yaml",
        "questions_test_sets.yaml",
        "questions_real.yaml",
        "questions_qa.yaml",
    )
]
RESULTS_DIR = ROOT / "evals" / "results"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.compare:
        return _compare(*args.compare)

    cases = select_cases(
        load_cases(args.files or DEFAULT_FILES),
        ids=_split(args.ids),
        qa=_split(args.qa),
        dataset=args.dataset,
    )
    if args.list:
        for case in cases:
            available = "" if (ROOT / case.dataset).exists() else "  [dataset no descargado]"
            print(f"{case.id:12} {case.qa or '-':5} {case.dataset}{available}")
        print(f"\n{len(cases)} casos")
        return 0
    if not cases:
        print("Ningún caso coincide con los filtros.")
        return 1

    output = (
        args.resume
        or args.output
        or RESULTS_DIR / f"{datetime.now().astimezone():%Y%m%d-%H%M%S}.jsonl"
    )
    previous = _read(output) if args.resume else []
    done = {r["key"] for r in previous if r["status"] in FINISHED}
    pending = len(cases) * args.repeat - len(done & _keys(cases, args.repeat))

    try:
        settings = load_settings(ROOT / ".env")
    except ConfigError as exc:
        print(f"Error de configuración: {exc}")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"{pending} ejecuciones pendientes con {settings.provider} ({settings.model})")
    print(f"Resultados en {output}\n")

    records = [r for r in previous if r["status"] in FINISHED]

    def save(record: dict[str, Any]) -> None:
        with output.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        records.append(record)
        print(_line(record))

    stopped = run_cases(
        cases,
        settings,
        create_client(settings),
        ROOT,
        done,
        save,
        repeat=args.repeat,
        max_call_errors=args.max_call_errors,
    )
    _print_summary([r for r in records if r["key"] in _keys(cases, args.repeat)])
    if stopped:
        print(f"\nCorrida detenida: {stopped}.")
        print(f"Retómala más tarde con: python evals/run_evals.py --resume {output}")
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluaciones del agente.")
    parser.add_argument("--files", nargs="+", type=Path, help="YAML de casos (por defecto, todos)")
    parser.add_argument("--ids", help="ids separados por coma")
    parser.add_argument("--qa", help="pruebas del informe de QA (S10,R6) o 'all'")
    parser.add_argument("--dataset", help="filtra por parte de la ruta del dataset")
    parser.add_argument("--repeat", type=int, default=1, help="repeticiones de cada caso")
    parser.add_argument("--output", type=Path, help="archivo JSONL de resultados")
    parser.add_argument("--resume", type=Path, help="retoma una corrida guardada en ese JSONL")
    parser.add_argument(
        "--max-call-errors", type=int, default=2, help="errores de llamada seguidos antes de parar"
    )
    parser.add_argument("--list", action="store_true", help="lista los casos y sale")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("ANTES", "DESPUES"))
    return parser


def _split(value: str | None) -> list[str] | None:
    return [item.strip() for item in value.split(",") if item.strip()] if value else None


def _keys(cases: list[Any], repeat: int) -> set[str]:
    return {f"{case.id}#{rep}" for case in cases for rep in range(1, repeat + 1)}


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _line(record: dict[str, Any]) -> str:
    marks = {"acierto": "✓", "fallo": "✗", "error_carga": "✗", "error_llamada": "!", "omitido": "-"}
    text = (
        f"{marks.get(record['status'], '?')} {record['key']:14} {record['status']:13} "
        f"{record.get('total_tokens', 0):6} tokens  {record.get('iterations', 0)} iter."
    )
    failed = [c for c in record.get("checks", []) if not c["passed"]]
    if failed:
        text += "  " + "; ".join(f"{c['type']}: {c['detail']}" for c in failed)
    if record.get("error"):
        text += f"  {record['error'][:120]}"
    return text


def _print_summary(records: list[dict[str, Any]]) -> None:
    summary = summarize(records)
    print("\n--- Resumen ---")
    for status, count in sorted(summary.counts.items()):
        print(f"{status:14} {count}")
    if summary.accuracy is not None:
        print(f"Acierto: {summary.accuracy:.0%} (sin contar errores de llamada ni omitidos)")
    if summary.avg_iterations is not None:
        print(f"Iteraciones promedio: {summary.avg_iterations:.1f}")
    print(f"Tokens: {summary.tokens}")


def _compare(before_path: Path, after_path: Path) -> int:
    before = {r["key"]: r for r in _read(before_path)}
    after = {r["key"]: r for r in _read(after_path)}
    print(f"{'caso':14} {'qa':5} {'antes':13} {'después':13} {'tokens':>15}")
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key, {}), after.get(key, {})
        qa = (b or a).get("qa") or "-"
        tokens = f"{a.get('total_tokens', '-')} -> {b.get('total_tokens', '-')}"
        print(f"{key:14} {qa:5} {a.get('status', '-'):13} {b.get('status', '-'):13} {tokens:>15}")
    for label, records in (("antes", before), ("después", after)):
        summary = summarize(list(records.values()))
        accuracy = "-" if summary.accuracy is None else f"{summary.accuracy:.0%}"
        print(f"\n{label}: acierto {accuracy}, {summary.tokens} tokens, {summary.counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
