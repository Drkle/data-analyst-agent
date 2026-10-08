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

## Privacidad

- **Qué se envía al proveedor del modelo (Groq o Gemini):** tu pregunta, los nombres y tipos
  de las columnas, 5 filas de ejemplo, estadísticas descriptivas y la salida de cada código
  ejecutado. El archivo completo nunca se envía, pero esas muestras sí salen de tu equipo:
  no uses datos sensibles con un proveedor externo.
- **Archivo subido:** se guarda solo en la carpeta de trabajo de la sesión
  (`sandbox_workspace/<id>/`) y se borra al cambiar o quitar el archivo en la app.
- **Telemetría:** el envío de estadísticas de uso de Streamlit está desactivado en
  `.streamlit/config.toml` (`gatherUsageStats = false`).
- **Claves:** el `.env` con las API keys está en `.gitignore` y nunca se sube al repositorio.

## Evaluaciones

<!-- TODO (Fase 4): publicar resultados -->
| Modelo | Acierto | Iteraciones promedio |
|---|---|---|
| — | — | — |

## Hoja de ruta

- [x] Fase 0 — Preparación
- [x] Fase 1 — Núcleo del agente
- [x] Fase 2 — Gráficas e interfaz web
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

**Fase 2 — Gráficas e interfaz web (completada, 2026-10-07)**

- `create_chart`: el modelo escribe código Plotly que asigna `fig`. El sandbox valida que sea
  una figura de Plotly con datos y como máximo 5000 puntos; si no, devuelve un error claro.
  Al modelo solo le llega un resumen (tipo, ejes, puntos, título), nunca la figura completa.
- Reglas de gráficas: agregar los datos antes de graficar; graficar solo si se pide, o como
  máximo una si no se pidió (prompt), con un tope de 3 por respuesta en el código. Las cifras
  de la respuesta salen siempre de `run_python`.
- Carpeta de trabajo por sesión (`sandbox_workspace/<id>/`). En la app se borra al cambiar o
  quitar el archivo; el archivo subido se guarda ahí con un nombre fijo.
- Límite de 50 MB en tres capas: `maxUploadSize` de Streamlit, comprobación en la app y en
  `DataTools`.
- App de Streamlit (`streamlit run app/streamlit_app.py`): subida de CSV/XLSX, vista previa,
  chat con historial, gráficas interactivas y el código ejecutado en un desplegable.
- La CLI guarda cada gráfica como `.html` en la carpeta de la sesión.
- 38 tests (incluye validación de gráficas, carpetas de sesión y un test de humo de la app).

Criterio de cierre: se subió `ventas.csv` a la app y, preguntando en español, se obtuvo la
gráfica de ingresos diarios.

**Ajustes tras probar la Fase 2**

- Métricas no calculables: el prompt obliga a decir que no se puede calcular (y qué falta)
  en vez de sustituir una métrica por otra. Probado con Groq: ganancia neta y clientes
  distintos responden correctamente que faltan datos.
- Fechas en las gráficas con formato numérico (`chart_format.py`, fuera del sandbox): eje
  `%m/%Y` que pasa a días o años con el zoom, y `%d/%m/%Y` al pasar el ratón.
- Barras ordenadas de mayor a menor salvo orden natural (regla del prompt).
- Telemetría de Streamlit desactivada y sección de privacidad en este README.
- `evals/questions.yaml`: casos q01–q07, incluidos dos de métricas no calculables.

**Verificador de cifras**

Al probar una gráfica mensual, el modelo dio 12 cifras habiendo impreso solo 5 (`head()`):
7 eran inventadas. Ahora `verifier.py` comprueba cada número de la respuesta final contra
las salidas de todas las herramientas de la conversación (redondeando a la precisión de la
respuesta, con abreviaturas como "mil" o "M" y probando ambas lecturas de separadores
ambiguos). Ignora años, fechas, enteros de un dígito y números de la pregunta. Si falta
alguna cifra, la respuesta vuelve al modelo (máximo 2 veces); si persiste, se entrega con un
aviso de "cifras sin verificar". Cada resultado registra cuántas veces se activó y cuántas
cifras se corrigieron. Además, las salidas recortadas lo indican ("se omitieron N de M
líneas") y pandas ya no oculta filas con "...". Caso de evaluación q08 con los 12 valores.

**Arreglos tras probar el verificador**

- Error `tool_use_failed` de Groq (el modelo escribe mal la llamada a una herramienta): se
  reintenta hasta 2 veces y, si persiste, se muestra un mensaje claro en español. Lo mismo
  para el 429 persistente y otros errores del proveedor; el detalle técnico queda en
  `LLMError.detail`. Cada respuesta registra cuántos de estos errores se recuperaron.
- Formato colombiano de números (51.697,33) en el prompt, en las gráficas y en la vista
  previa de la app (los enteros se dejan sin separador para no deformar años ni ids). El
  verificador reconoce este formato.
- El verificador muestra "✓ Cifras verificadas contra el código ejecutado" cuando todo
  cuadra; su detalle pasa al desplegable "Código ejecutado". Las cifras sin verificar siguen
  con aviso visible.
- Se borró `PLAN.md` de la raíz (versión vieja); el plan vigente es `docs/PLAN.md`.
- `.gitattributes` normaliza los fines de línea a LF.

## Licencia

MIT
