"""Valida los archivos de casos de evaluación (formato, ids únicos y datasets)."""

from pathlib import Path

import pytest

from data_analyst_agent.evaluation import Case, load_cases

ROOT = Path(__file__).parents[1]
CASE_FILES = sorted((ROOT / "evals").glob("questions*.yaml"))
# Datasets que no se suben al repositorio (ver data/real/README.md).
DOWNLOADED = "data/real/"


def test_all_case_files_are_found() -> None:
    names = {path.name for path in CASE_FILES}
    assert {
        "questions.yaml",
        "questions_test_sets.yaml",
        "questions_real.yaml",
        "questions_qa.yaml",
    } <= names


def test_cases_load_with_unique_ids() -> None:
    assert len(load_cases(CASE_FILES)) > 40  # load_cases falla si hay ids repetidos


@pytest.mark.parametrize("case", load_cases(CASE_FILES), ids=lambda case: case.id)
def test_case_is_well_formed(case: Case) -> None:
    assert case.question.strip()
    assert case.checks
    if not (ROOT / case.dataset).exists():
        assert case.dataset.startswith(DOWNLOADED), f"falta {case.dataset}"
        pytest.skip(f"{case.dataset} no descargado")
