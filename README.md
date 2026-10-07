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
- [x] Fase 1 — Núcleo del agente
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

**Fase 1 — Núcleo del agente (completada, 2026-10-07)**

- `llm.py`: tipos internos propios (`Message`, `ToolCall`, `LLMResponse`) y adaptador
  `OpenAICompatibleClient` para Groq y Gemini. Reintenta ante HTTP 429 respetando
  `retry-after` (o con espera exponencial) y hace una pausa mínima entre llamadas.
- `agent.py`: ciclo razonar → herramienta → observar escrito a mano, con historial entre
  preguntas y límite de iteraciones.
- `tools.py`: `inspect_data` (esquema y muestra, nunca el archivo completo) y `run_python`
  (código pandas con el dataset ya cargado en `df`; salida recortada a 4000 caracteres).
- `sandbox.py` (versión simple): proceso separado, timeout y carpeta `sandbox_workspace/`.
  El bloqueo de red e imports llega en la Fase 3.
- `config.py`: todo se ajusta por `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `MAX_ITERATIONS`,
  `MAX_RETRIES`, `CALL_DELAY_SECONDS`, `MAX_TOKENS`, `SANDBOX_TIMEOUT`).
- Dataset sintético reproducible: `data/sample/ventas.csv` (500 filas, semilla 42).
- 26 tests sin llamadas a la API (modelo falso y 429 simulados); ruff sin avisos.

Criterio de cierre — 5 preguntas con Groq (`openai/gpt-oss-120b`), 5/5 correctas:

| Pregunta | Respuesta del agente | Esperada | Iteraciones |
|---|---|---|---|
| ¿Cuántas ventas hay registradas? | 500 | 500 | 2 |
| ¿Qué producto vendió más unidades? | Escritorio, 629 | Escritorio, 629 | 2 |
| ¿Qué región generó más ingresos? | Centro, 275 858,67 | Centro, 275 858,67 | 2 |
| ¿En qué mes hubo más ingresos? | Febrero 2025, 132 836,23 | Febrero, 132 836,23 | 2 |
| ¿Precio promedio de la categoría Muebles? | 164,76 | 164,76 | 2 |

## Licencia

MIT
