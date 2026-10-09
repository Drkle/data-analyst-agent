"""App mínima de sondeo: muestra qué aislamiento ofrece el servidor donde se despliega.

En Streamlit Community Cloud: Main file path = probe/streamlit_app.py
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

# El módulo de sondeo solo usa la librería estándar: no hace falta instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
isolation_probe = importlib.import_module("data_analyst_agent.isolation_probe")


# App pública: el sondeo lanza varios procesos, así que se repite como mucho una vez por hora
# (o al reiniciar la app). No muestra variables de entorno ni contenido de archivos.
@st.cache_data(ttl=3600, show_spinner="Sondeando el servidor...")
def probe() -> dict[str, Any]:
    return isolation_probe.run_probe()


st.set_page_config(page_title="Sondeo de aislamiento", page_icon="🔒")
st.title("🔒 Sondeo de aislamiento")
st.caption("Qué mecanismos ofrece este servidor para aislar el código que genera el agente.")

report = probe()
level = report["nivel"]
(st.success if level["suficiente"] else st.error)(level["nivel"])
st.markdown(isolation_probe.format_markdown(report))
with st.expander("Resultado en JSON (para copiar)"):
    st.code(json.dumps(report, indent=2, ensure_ascii=False), language="json")
