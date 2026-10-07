"""Test de humo de la app de Streamlit (sin navegador ni llamadas a la API)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "app" / "streamlit_app.py"


def test_app_asks_for_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    app = AppTest.from_file(str(APP)).run()

    assert not app.exception
    assert "Sube un archivo" in app.info[0].value
