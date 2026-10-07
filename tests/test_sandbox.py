"""Tests de las carpetas de trabajo por sesión."""

from pathlib import Path

import pytest

from data_analyst_agent.sandbox import new_session_dir, remove_session_dir


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
