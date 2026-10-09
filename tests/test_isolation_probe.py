"""Tests del sondeo de aislamiento (en Linux ejecuta las pruebas reales del kernel)."""

import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from data_analyst_agent.isolation_probe import (
    format_markdown,
    github_annotation,
    main,
    run_probe,
)

IS_LINUX = sys.platform.startswith("linux")


@pytest.fixture(scope="module")
def report() -> dict:
    return run_probe()


def test_report_has_the_main_sections(report: dict) -> None:
    assert {"sistema", "herramientas", "red_saliente", "nivel"} <= report.keys()
    assert isinstance(report["nivel"]["suficiente"], bool)


@pytest.mark.skipif(IS_LINUX, reason="comprueba el caso sin Landlock ni seccomp")
def test_non_linux_is_development_only(report: dict) -> None:
    assert "linux" not in report
    assert report["nivel"]["suficiente"] is False
    assert report["nivel"]["nivel"].startswith("solo desarrollo")


@pytest.mark.skipif(not IS_LINUX, reason="pruebas del kernel de Linux")
def test_linux_checks_run_without_crashing(report: dict) -> None:
    linux = report["linux"]
    for key in (
        "landlock_archivos",
        "landlock_red",
        "seccomp_filtro",
        "user_namespaces",
        "bwrap_sandbox",
    ):
        assert isinstance(linux[key], str) and linux[key]
    assert "numpy" in linux["rlimit_as_1gb"]
    # Un informe por prueba (análisis, gráficas...) o un texto si no se pudo instalar.
    assert isinstance(linux["seccomp_sin_open"], (dict, str)) and linux["seccomp_sin_open"]


def test_markdown_shows_level(report: dict) -> None:
    text = format_markdown(report)
    assert text.startswith("## Sondeo de aislamiento")
    assert report["nivel"]["nivel"] in text


def test_cli_prints_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "**Nivel:**" in capsys.readouterr().out


def test_github_annotations_are_single_escaped_lines() -> None:
    line = github_annotation("Sondeo: x", {"a": "100% listo\nfin"})
    assert line == '::notice title=Sondeo: x::{"a": "100%25 listo\\nfin"}'
    assert "\n" not in github_annotation("t", "uno\ndos")


def test_probe_app_renders() -> None:
    app_path = Path(__file__).parents[1] / "probe" / "streamlit_app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120).run()
    assert not app.exception
    assert app.title[0].value == "🔒 Sondeo de aislamiento"


def test_report_never_includes_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "canario-sondeo-123")
    monkeypatch.setenv("CANARIO_SONDEO", "canario-sondeo-123")
    text = json.dumps(run_probe(), ensure_ascii=False)
    assert "canario-sondeo-123" not in text
    assert "GROQ_API_KEY" not in text
