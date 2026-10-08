"""Interfaz web con Streamlit.

Uso: streamlit run app/streamlit_app.py

Cada sesión del navegador tiene su propia carpeta de trabajo (sandbox_workspace/<id>/),
donde se guarda el archivo subido y las gráficas. La carpeta se borra al cambiar o quitar
el archivo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.io as pio
import streamlit as st

from data_analyst_agent.agent import Agent, AgentResult
from data_analyst_agent.config import ConfigError, Settings, load_settings
from data_analyst_agent.formatting import format_preview
from data_analyst_agent.llm import LLMError, create_client
from data_analyst_agent.sandbox import new_session_dir, remove_session_dir
from data_analyst_agent.tools import MAX_FILE_BYTES, DataTools, load_dataframe

CODE_TOOLS = {"run_python", "create_chart"}
MAX_FILE_MB = MAX_FILE_BYTES // 1024 // 1024


def reset_session() -> None:
    """Borra la carpeta de trabajo y la conversación de la sesión actual."""
    workdir = st.session_state.pop("workdir", None)
    if workdir is not None:
        remove_session_dir(workdir)
    for key in ("file_id", "file_name", "agent", "history", "preview"):
        st.session_state.pop(key, None)


def start_session(uploaded: Any, settings: Settings) -> None:
    """Prepara una sesión nueva para el archivo subido."""
    reset_session()
    workdir = new_session_dir()
    # Nombre fijo dentro de la carpeta de sesión: el nombre original nunca forma la ruta.
    data_path = workdir / f"datos{Path(uploaded.name).suffix.lower()}"
    data_path.write_bytes(uploaded.getvalue())
    st.session_state.workdir = workdir
    tools = DataTools(data_path, timeout=settings.sandbox_timeout, workdir=workdir)
    st.session_state.update(
        file_id=uploaded.file_id,
        file_name=uploaded.name,
        preview=load_dataframe(data_path).head(10),
        agent=Agent.from_settings(create_client(settings), tools, settings),
        history=[],
    )


def render_result(result: AgentResult) -> None:
    # "$" activa fórmulas LaTeX en st.markdown; se escapa para mostrar importes tal cual.
    st.markdown(result.answer.replace("$", "\\$"))
    verification = result.verification
    if verification.unverified:
        st.warning(
            "Cifras sin verificar con código: "
            + ", ".join(verification.unverified).replace("$", "\\$")
        )
    elif verification.checked:
        st.caption("✓ Cifras verificadas contra el código ejecutado")
    for chart in result.charts:
        st.plotly_chart(pio.from_json(chart.figure_json))

    code_steps = [step for step in result.steps if step.tool in CODE_TOOLS]
    if code_steps or verification.triggers or result.tool_format_errors:
        with st.expander("Código ejecutado"):
            for step in code_steps:
                st.caption(step.tool)
                st.code(step.arguments.get("code", ""), language="python")
            if verification.triggers:
                times = "vez" if verification.triggers == 1 else "veces"
                st.caption(
                    f"Verificador de cifras: se activó {verification.triggers} {times}; "
                    f"cifras corregidas: {verification.corrected}."
                )
            if result.tool_format_errors:
                st.caption(
                    "Llamadas a herramientas repetidas por formato inválido: "
                    f"{result.tool_format_errors}."
                )


def main() -> None:
    st.set_page_config(page_title="Data Analyst Agent", page_icon="📊", layout="wide")
    st.title("📊 Data Analyst Agent")
    st.caption("Pregúntale a tus datos en lenguaje natural. Cada cifra sale de código ejecutado.")

    try:
        settings = load_settings()
    except ConfigError as exc:
        st.error(f"Error de configuración: {exc}")
        st.stop()

    with st.sidebar:
        uploaded = st.file_uploader(
            f"Sube un archivo CSV o Excel (máx. {MAX_FILE_MB} MB)", type=["csv", "xlsx"]
        )
        st.caption(f"Modelo: {settings.provider} · {settings.model}")

    if uploaded is None:
        if "workdir" in st.session_state:
            reset_session()
        st.info("Sube un archivo en la barra lateral para empezar.")
        st.stop()

    if uploaded.size > MAX_FILE_BYTES:
        st.error(
            f"El archivo pesa {uploaded.size / 1024 / 1024:.1f} MB; el máximo es {MAX_FILE_MB} MB."
        )
        st.stop()

    if uploaded.file_id != st.session_state.get("file_id"):
        try:
            start_session(uploaded, settings)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo al leer se muestra al usuario
            reset_session()
            st.error(f"No se pudo leer el archivo: {exc}")
            st.stop()

    with st.sidebar:
        st.subheader(st.session_state.file_name)
        preview: pd.DataFrame = st.session_state.preview
        st.dataframe(format_preview(preview), hide_index=True)

    history: list[dict[str, Any]] = st.session_state.history
    for entry in history:
        with st.chat_message(entry["role"]):
            if entry.get("result") is not None:
                render_result(entry["result"])
            else:
                st.markdown(entry["content"])

    question = st.chat_input("Pregunta sobre tus datos, por ejemplo: ¿qué región vende más?")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analizando..."):
                result = st.session_state.agent.run(question)
        except LLMError as exc:
            message = f"No pude responder: {exc}"
            st.error(message)
            history.append({"role": "assistant", "content": message})
            return
        render_result(result)
    history.append({"role": "assistant", "result": result})


main()
