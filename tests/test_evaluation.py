"""Tests de las evaluaciones: comprobaciones, selección de casos y ejecución con un modelo falso."""

from pathlib import Path
from typing import Any

import pytest

from data_analyst_agent.config import Settings
from data_analyst_agent.evaluation import (
    Case,
    evaluate_answer,
    is_quota_error,
    load_cases,
    run_case,
    run_cases,
    select_cases,
    summarize,
)
from data_analyst_agent.llm import LLMError, LLMResponse, Message, ToolCall, ToolDefinition

SETTINGS = Settings(provider="groq", model="modelo", api_key="k", base_url="https://x")


def _passed(answer: str, check: dict[str, Any]) -> bool:
    return evaluate_answer(answer, [check])[0].passed


# --- Comprobaciones ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Fue 275.858,67.",
        "Fue 275 858,67.",
        "Fue 275858.67.",
        "Fue 275,858.67.",
        "Fue 275.858,67 %.",
    ],
)
def test_numeric_accepts_number_formats(answer: str) -> None:
    assert _passed(answer, {"type": "numeric", "value": 275858.67, "tolerance": 0.01})


def test_numeric_respects_tolerance() -> None:
    check = {"type": "numeric", "value": 957, "tolerance": 0}
    assert _passed("Hubo 957 hurtos.", check)
    assert not _passed("Hubo 958 hurtos.", check)
    assert _passed("Fueron 35.093.000 de gastos.", {**check, "value": 35093000})
    assert _passed("Unos 35 mil.", {"type": "numeric", "value": 35000, "tolerance": 0})


def test_terms_ignore_case_and_accents_and_match_word_starts() -> None:
    assert _passed("En BOGOTA hubo...", {"type": "contains", "terms": ["Bogotá"]})
    assert _passed("No hay datos de costos.", {"type": "contains", "terms": ["cost"]})
    assert not _passed("Fueron 193 ventas.", {"type": "contains", "terms": ["93"]})
    assert _passed("Códigos: 05034007 y 05034000.", {"type": "contains", "terms": ["05034007"]})


def test_contains_any_and_excludes() -> None:
    assert _passed(
        "Hubo 957 en este registro.",
        {"type": "contains_any", "terms": ["en este registro", "modalidades"]},
    )
    assert not _passed("Hubo 957.", {"type": "contains_any", "terms": ["en este registro"]})
    assert not _passed("Son 275.858,67 COP.", {"type": "excludes", "terms": ["COP"]})
    assert _passed("Son 275.858,67.", {"type": "excludes", "terms": ["COP"]})


def test_not_computable() -> None:
    check = {
        "type": "not_computable",
        "refusal_any": ["no se puede"],
        "mentions_all": ["cliente"],
        "must_not_contain": ["350 clientes"],
    }
    assert _passed("No se puede: no hay columna de clientes.", check)
    assert not _passed("Respondieron 350 clientes.", check)
    assert not _passed("No se puede: hay 350 clientes.", check)


def test_failed_check_explains_why() -> None:
    result = evaluate_answer("Fue 10.", [{"type": "numeric", "value": 12, "tolerance": 0}])[0]
    assert not result.passed and "esperado 12" in result.detail


# --- Casos ----------------------------------------------------------------------------------


def _yaml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "casos.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_cases_rejects_invalid_checks_and_duplicated_ids(tmp_path: Path) -> None:
    bad_check = _yaml(tmp_path, "- {id: a, dataset: x.csv, question: q, checks: [{type: numeric}]}")
    with pytest.raises(ValueError, match="check inválido"):
        load_cases([bad_check])
    duplicated = _yaml(
        tmp_path,
        "- {id: a, dataset: x.csv, question: q, checks: [{type: contains, terms: [x]}]}\n"
        "- {id: a, dataset: x.csv, question: q, checks: [{type: contains, terms: [x]}]}",
    )
    with pytest.raises(ValueError, match="repetidos"):
        load_cases([duplicated])


def test_select_cases() -> None:
    cases = [
        Case("q01", "data/sample/ventas.csv", "?", []),
        Case("t-enc-04", "data/test_sets/encuesta.csv", "?", [], qa="S10"),
        Case("qa-hur-01", "data/real/hurtos.csv", "?", [], qa="R6"),
    ]
    assert [c.id for c in select_cases(cases, qa=["all"])] == ["t-enc-04", "qa-hur-01"]
    assert [c.id for c in select_cases(cases, qa=["s10"])] == ["t-enc-04"]
    assert [c.id for c in select_cases(cases, dataset="real")] == ["qa-hur-01"]
    assert [c.id for c in select_cases(cases, ids=["q01"])] == ["q01"]
    with pytest.raises(ValueError, match="desconocidos"):
        select_cases(cases, ids=["zz"])


# --- Ejecución con un modelo falso ------------------------------------------------------------


class ScriptedLLM:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "ventas.csv").write_text(
        "region,valor\nNorte,3\nSur,5\n", encoding="utf-8"
    )
    (tmp_path / "datos" / "roto.csv").write_text(
        "Acta de la reunión\nAsistentes varios\nSe revisó, se aprobó y, al final, se cerró\n",
        encoding="utf-8",
    )
    return tmp_path


def _case(case_id: str = "c1", dataset: str = "datos/ventas.csv", **extra: Any) -> Case:
    checks = [{"type": "numeric", "value": 8, "tolerance": 0}]
    return Case(case_id, dataset, "¿Cuánto suma valor?", checks, **extra)


def _answer_with_code() -> list[LLMResponse]:
    call = ToolCall("c", "run_python", {"code": "print(df['valor'].sum())"})
    return [
        LLMResponse(text="", tool_calls=[call], total_tokens=100),
        LLMResponse(text="Suma 8.", total_tokens=50),
    ]


def test_run_case_correct_answer(root: Path) -> None:
    record = run_case(
        _case(), SETTINGS, ScriptedLLM(_answer_with_code()), root, workspace=root / "ws"
    )
    assert record["status"] == "acierto"
    assert record["total_tokens"] == 150
    assert record["iterations"] == 2
    assert record["steps"] == ["run_python"]
    assert list((root / "ws").iterdir()) == []  # la carpeta de la sesión se borró


def test_run_case_wrong_answer(root: Path) -> None:
    llm = ScriptedLLM([LLMResponse(text="No lo sé.")])
    record = run_case(_case(), SETTINGS, llm, root, workspace=root / "ws")
    assert record["status"] == "fallo"
    assert record["checks"][0]["passed"] is False


def test_run_case_classifies_non_agent_problems(root: Path) -> None:
    llm = ScriptedLLM([])
    assert (
        run_case(_case(dataset="datos/no_existe.csv"), SETTINGS, llm, root)["status"] == "omitido"
    )
    assert run_case(_case(sheet="Gastos"), SETTINGS, llm, root)["status"] == "omitido"
    assert run_case(_case(dataset="datos/roto.csv"), SETTINGS, llm, root)["status"] == "error_carga"


def test_run_case_call_error_keeps_tokens(root: Path) -> None:
    first = LLMResponse(
        text="", tool_calls=[ToolCall("c", "run_python", {"code": "print(1)"})], total_tokens=120
    )
    llm = ScriptedLLM(
        [first, LLMError("Demasiadas peticiones.", detail="429 tokens per day (TPD)")]
    )
    record = run_case(_case(), SETTINGS, llm, root, workspace=root / "ws")
    assert record["status"] == "error_llamada"
    assert record["total_tokens"] == 120
    assert is_quota_error(record)


def test_run_cases_stops_on_quota_and_resumes(root: Path) -> None:
    cases = [_case("c1"), _case("c2"), _case("c3")]
    saved: list[dict[str, Any]] = []
    quota = LLMError("Demasiadas peticiones.", detail="429 tokens per day (TPD)")
    llm = ScriptedLLM([*_answer_with_code(), quota])
    stopped = run_cases(cases, SETTINGS, llm, root, set(), saved.append, workspace=root / "ws")
    assert stopped == "cupo diario del proveedor agotado"
    assert [r["status"] for r in saved] == ["acierto", "error_llamada"]

    done = {r["key"] for r in saved if r["status"] == "acierto"}
    llm = ScriptedLLM([*_answer_with_code(), *_answer_with_code()])
    resumed: list[dict[str, Any]] = []
    assert (
        run_cases(cases, SETTINGS, llm, root, done, resumed.append, workspace=root / "ws") is None
    )
    assert [r["key"] for r in resumed] == ["c2#1", "c3#1"]


def test_summary_ignores_call_errors_and_skips() -> None:
    records = [
        {"status": "acierto", "iterations": 2, "total_tokens": 10},
        {"status": "fallo", "iterations": 4, "total_tokens": 20},
        {"status": "error_carga", "iterations": 0, "total_tokens": 0},
        {"status": "error_llamada", "iterations": 0, "total_tokens": 5},
        {"status": "omitido", "iterations": 0, "total_tokens": 0},
    ]
    summary = summarize(records)
    assert summary.accuracy == pytest.approx(1 / 3)
    assert summary.avg_iterations == 3
    assert summary.tokens == 35


def test_context_questions_run_first_in_the_same_conversation(root: Path) -> None:
    llm = ScriptedLLM([LLMResponse(text="Antes.", total_tokens=30), *_answer_with_code()])
    case = _case(context=["¿Pregunta previa?"])
    record = run_case(case, SETTINGS, llm, root, workspace=root / "ws")
    assert record["status"] == "acierto"
    assert record["context_tokens"] == 30
    assert record["total_tokens"] == 180
