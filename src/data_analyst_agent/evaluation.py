"""Evaluaciones: casos con respuesta esperada, comprobaciones y ejecución de cada caso.

La interfaz de línea de comandos está en evals/run_evals.py.

Estados de un caso:
- acierto:       pasaron todas las comprobaciones
- fallo:         el agente respondió, pero alguna comprobación no pasó
- error_carga:   el archivo no se pudo cargar (en la app, el usuario ni siquiera podría preguntar)
- error_llamada: falló la llamada al modelo (cupo, red, proveedor); no mide al agente
- omitido:       no se pudo ejecutar (dataset no descargado, función aún no disponible)
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from data_analyst_agent.agent import Agent
from data_analyst_agent.config import Settings
from data_analyst_agent.llm import LLMClient, LLMError
from data_analyst_agent.sandbox import new_session_dir, remove_session_dir
from data_analyst_agent.tools import DataTools, load_dataframe
from data_analyst_agent.verifier import extract_mentions

CHECK_FIELDS = {
    "numeric": {"value", "tolerance"},
    "contains": {"terms"},
    "contains_any": {"terms"},
    "excludes": {"terms"},
    "not_computable": {"refusal_any", "mentions_all", "must_not_contain"},
}
# Estados que cuentan para el porcentaje de acierto (los demás no miden al agente).
SCORED = ("acierto", "fallo", "error_carga")
# Estados que no se repiten al retomar una corrida.
FINISHED = (*SCORED, "omitido")


@dataclass
class Case:
    id: str
    dataset: str
    question: str
    checks: list[dict[str, Any]]
    sheet: str | None = None
    qa: str | None = None
    context: list[str] = field(default_factory=list)  # preguntas previas, sin evaluar
    source: str = ""  # archivo YAML de origen


@dataclass
class CheckResult:
    type: str
    passed: bool
    detail: str


# --- Casos ----------------------------------------------------------------------------------


def load_cases(files: Iterable[Path]) -> list[Case]:
    """Lee y valida los casos de los YAML indicados."""
    cases: list[Case] = []
    for path in files:
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            for check in raw["checks"]:
                missing = CHECK_FIELDS.get(check["type"], {"type"}) - check.keys()
                if check["type"] not in CHECK_FIELDS or missing:
                    raise ValueError(f"{path}: caso {raw['id']} con un check inválido: {check}")
            cases.append(
                Case(
                    id=str(raw["id"]),
                    dataset=raw["dataset"],
                    question=raw["question"],
                    checks=raw["checks"],
                    sheet=raw.get("sheet"),
                    qa=raw.get("qa"),
                    context=list(raw.get("context") or []),
                    source=path.name,
                )
            )
    ids = [case.id for case in cases]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"Ids de caso repetidos: {duplicated}")
    return cases


def select_cases(
    cases: list[Case],
    ids: list[str] | None = None,
    qa: list[str] | None = None,
    dataset: str | None = None,
) -> list[Case]:
    """Filtra los casos. `qa=["all"]` elige todos los que vienen del informe de QA."""
    selected = cases
    if ids:
        unknown = set(ids) - {case.id for case in cases}
        if unknown:
            raise ValueError(f"Ids desconocidos: {sorted(unknown)}")
        selected = [case for case in selected if case.id in ids]
    if qa:
        wanted = {tag.upper() for tag in qa}
        selected = [
            case for case in selected if case.qa and ("ALL" in wanted or case.qa.upper() in wanted)
        ]
    if dataset:
        selected = [case for case in selected if dataset.lower() in case.dataset.lower()]
    return selected


# --- Comprobaciones ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con espacios simples (incluidos los espacios duros)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _has_term(normalized_answer: str, term: str) -> bool:
    # Al inicio de palabra: "cost" acepta "costos", pero "93" no acepta "193".
    pattern = r"(?<![a-z0-9])" + re.escape(normalize(str(term)))
    return re.search(pattern, normalized_answer) is not None


def evaluate_answer(answer: str, checks: list[dict[str, Any]]) -> list[CheckResult]:
    text = normalize(answer)
    results = []
    for check in checks:
        kind = check["type"]
        if kind == "numeric":
            value, tolerance = float(check["value"]), float(check["tolerance"])
            found = [
                reading * mention.scale
                for mention in extract_mentions(answer)
                for reading, _ in mention.readings
            ]
            passed = any(abs(number - value) <= tolerance + 1e-9 for number in found)
            detail = f"esperado {value:g} ± {tolerance:g}"
        elif kind in ("contains", "contains_any", "excludes"):
            hits = [term for term in check["terms"] if _has_term(text, term)]
            if kind == "contains":
                passed = len(hits) == len(check["terms"])
                detail = f"faltan: {[t for t in check['terms'] if t not in hits]}"
            elif kind == "contains_any":
                passed = bool(hits)
                detail = f"ninguno de: {check['terms']}"
            else:
                passed = not hits
                detail = f"aparece: {hits}"
        else:  # not_computable
            refused = any(_has_term(text, term) for term in check["refusal_any"])
            missing = [t for t in check["mentions_all"] if not _has_term(text, t)]
            forbidden = [t for t in check["must_not_contain"] if _has_term(text, t)]
            passed = refused and not missing and not forbidden
            detail = f"se negó: {refused}; faltan: {missing}; prohibidos: {forbidden}"
        results.append(CheckResult(kind, passed, "" if passed else detail))
    return results


# --- Ejecución ---------------------------------------------------------------------------------


def run_case(
    case: Case,
    settings: Settings,
    llm: LLMClient,
    root: Path,
    repetition: int = 1,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Ejecuta un caso con un agente nuevo y devuelve su registro (apto para JSON)."""
    record: dict[str, Any] = {
        "key": f"{case.id}#{repetition}",
        "id": case.id,
        "repetition": repetition,
        "qa": case.qa,
        "source": case.source,
        "dataset": case.dataset,
        "question": case.question,
        "provider": settings.provider,
        "model": settings.model,
        "started_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "status": "",
        "answer": "",
        "checks": [],
        "iterations": 0,
        "total_tokens": 0,
        "seconds": 0.0,
        "error": "",
    }
    path = root / case.dataset
    if not path.exists():
        return record | {"status": "omitido", "error": f"no existe {case.dataset}"}
    if case.sheet:
        return record | {
            "status": "omitido",
            "error": "elegir hoja de Excel: llega en la Entrega B",
        }
    try:
        load_dataframe(path)  # la app también lo carga antes de dejar preguntar
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de carga es un resultado del caso
        return record | {"status": "error_carga", "error": f"{type(exc).__name__}: {exc}"}

    workdir = new_session_dir(workspace) if workspace else new_session_dir()
    start = time.monotonic()
    try:
        tools = DataTools(path, timeout=settings.sandbox_timeout, workdir=workdir)
        agent = Agent.from_settings(llm, tools, settings)
        context_tokens = 0
        try:
            for previous in case.context:  # misma conversación; no se evalúan
                context_tokens += agent.run(previous).total_tokens
            result = agent.run(case.question)
        except LLMError as exc:
            return record | {
                "status": "error_llamada",
                "error": str(exc),
                "detail": exc.detail,
                "total_tokens": context_tokens + exc.total_tokens,
                "tool_format_errors": exc.tool_format_errors,
                "seconds": round(time.monotonic() - start, 1),
            }
    finally:
        if workspace:
            remove_session_dir(workdir, workspace)
        else:
            remove_session_dir(workdir)

    checks = evaluate_answer(result.answer, case.checks)
    return record | {
        "status": "acierto" if all(c.passed for c in checks) else "fallo",
        "answer": result.answer,
        "checks": [vars(c) for c in checks],
        "iterations": result.iterations,
        "hit_limit": result.hit_limit,
        "total_tokens": context_tokens + result.total_tokens,
        "context_tokens": context_tokens,
        "tool_format_errors": result.tool_format_errors,
        "verification": {
            "triggers": result.verification.triggers,
            "flagged": result.verification.flagged,
            "checked": result.verification.checked,
            "unverified": result.verification.unverified,
            "last_execution_failed": result.verification.last_execution_failed,
        },
        "steps": [step.tool for step in result.steps],
        "seconds": round(time.monotonic() - start, 1),
    }


def is_quota_error(record: dict[str, Any]) -> bool:
    """Un 429 por cupo diario: seguir llamando no sirve hasta que se renueve."""
    text = f"{record.get('error', '')} {record.get('detail', '')}".lower()
    return record["status"] == "error_llamada" and (
        "per day" in text or "tpd" in text or "rpd" in text
    )


@dataclass
class Summary:
    counts: dict[str, int] = field(default_factory=dict)
    accuracy: float | None = None
    tokens: int = 0
    avg_iterations: float | None = None


def summarize(records: list[dict[str, Any]]) -> Summary:
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    scored = [r for r in records if r["status"] in SCORED]
    answered = [r for r in records if r["status"] in ("acierto", "fallo")]
    return Summary(
        counts=counts,
        accuracy=counts.get("acierto", 0) / len(scored) if scored else None,
        tokens=sum(r.get("total_tokens", 0) for r in records),
        avg_iterations=(
            sum(r["iterations"] for r in answered) / len(answered) if answered else None
        ),
    )


def run_cases(
    cases: list[Case],
    settings: Settings,
    llm: LLMClient,
    root: Path,
    done: set[str],
    on_record: Callable[[dict[str, Any]], None],
    repeat: int = 1,
    max_call_errors: int = 2,
    workspace: Path | None = None,
) -> str | None:
    """Ejecuta los casos pendientes. Devuelve el motivo si la corrida se cortó, o None."""
    consecutive_call_errors = 0
    for repetition in range(1, repeat + 1):
        for case in cases:
            if f"{case.id}#{repetition}" in done:
                continue
            record = run_case(case, settings, llm, root, repetition, workspace)
            on_record(record)
            if record["status"] != "error_llamada":
                consecutive_call_errors = 0
                continue
            consecutive_call_errors += 1
            if is_quota_error(record):
                return "cupo diario del proveedor agotado"
            if consecutive_call_errors >= max_call_errors:
                return f"{consecutive_call_errors} errores de llamada seguidos"
    return None
