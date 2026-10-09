"""Valida el formato de los casos de evaluación (el script de evaluación llega en la Fase 4)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
CASE_FILES = [ROOT / "evals" / "questions.yaml", ROOT / "evals" / "questions_test_sets.yaml"]
REQUIRED_FIELDS = {
    "numeric": {"value", "tolerance"},
    "contains": {"terms"},
    "excludes": {"terms"},
    "not_computable": {"refusal_any", "mentions_all", "must_not_contain"},
}


def _cases() -> list[dict[str, Any]]:
    return [
        case for path in CASE_FILES for case in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]


def test_case_ids_are_unique_across_files() -> None:
    ids = [case["id"] for case in _cases()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["id"])
def test_case_is_well_formed(case: dict[str, Any]) -> None:
    assert (ROOT / case["dataset"]).exists()
    assert case["question"].strip()
    assert case["checks"]
    for check in case["checks"]:
        assert check["type"] in REQUIRED_FIELDS
        assert REQUIRED_FIELDS[check["type"]] <= check.keys()
