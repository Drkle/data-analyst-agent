# 🤖 Data Analyst Agent

> Pregúntale a tus datos en lenguaje natural. Un agente de IA que escribe, ejecuta y corrige su propio código de análisis, y te muestra cómo llegó a cada respuesta.

![status](https://img.shields.io/badge/status-en%20desarrollo-yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

<!-- TODO (Fase 5): reemplazar por un GIF de la demo -->
<!-- ![demo](docs/demo.gif) -->

## ¿Qué problema resuelve?

Los chatbots genéricos *suenan* seguros al hablar de tus datos, pero no calculan nada: pueden inventar cifras. Este agente **ejecuta código real** sobre tu archivo, así que cada número de la respuesta sale de un cálculo verificable.

Más detalle en el [plan del proyecto](docs/PLAN.md).

## Características

- 💬 Preguntas en lenguaje natural sobre archivos CSV y Excel
- 🧠 Agente implementado desde cero con *tool use* (sin frameworks)
- 🔀 Agnóstico al proveedor: Groq, Gemini o Anthropic con una sola variable
- 💸 Desarrollo y demo con costo $0 usando capas gratuitas
- 🔒 Ejecución de código aislada, con timeout y sin acceso a red
- 🔁 Autocorrección: si el código falla, lee el error y reintenta
- 📊 Gráficas generadas automáticamente
- ✅ Evaluaciones automáticas de calidad

## Arquitectura

```
Interfaz (Streamlit / CLI) ──▶ Agente (ciclo de razonamiento)
                                   │ tool use
                                   ▼
                 inspect_data · run_python · create_chart
                                   │
                                   ▼
                       Sandbox de ejecución aislado
```

## Instalación

```bash
git clone https://github.com/<tu-usuario>/data-analyst-agent.git
cd data-analyst-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Crea un archivo `.env` en la raíz con al menos `LLM_PROVIDER` y `GROQ_API_KEY`
(gratis en console.groq.com). El `.env` está en `.gitignore` y nunca se sube al repositorio.

## Uso

```bash
# Terminal
python -m data_analyst_agent.cli data/sample/ventas.csv

# Interfaz web
streamlit run app/streamlit_app.py
```

## Evaluaciones

<!-- TODO (Fase 4): publicar resultados -->
| Modelo | Acierto | Iteraciones promedio |
|---|---|---|
| — | — | — |

## Hoja de ruta

- [x] Fase 0 — Preparación
- [ ] Fase 1 — Núcleo del agente
- [ ] Fase 2 — Gráficas e interfaz web
- [ ] Fase 3 — Robustez y seguridad
- [ ] Fase 4 — Evaluaciones
- [ ] Fase 5 — Demo pública

### Registro de avances

**Fase 0 — Preparación (completada, 2026-10-07)**

- Estructura del proyecto: paquete `src/data_analyst_agent/` con módulos vacíos por fase,
  `app/`, `evals/`, `tests/`, `data/sample/` y plan en `docs/PLAN.md`.
- Entorno virtual con Python 3.14 y dependencias instaladas con `pip install -e ".[dev]"`.
- Conexión con Groq verificada a través de su endpoint compatible con OpenAI
  (modelo `openai/gpt-oss-120b`), con una llamada de prueba que respondió correctamente.
- `pytest` corre: 1 test de humo (`tests/test_smoke.py`) pasa.
- Repositorio git inicializado en la rama `main`; `.env` y `.venv/` excluidos por `.gitignore`.

Notas para la Fase 1:

- `gpt-oss-120b` es un modelo de razonamiento: consume tokens pensando antes de responder.
  Con un `max_tokens` muy bajo (p. ej. 5) devuelve texto vacío, así que `llm.py` debe usar
  límites holgados.

## Licencia

MIT
