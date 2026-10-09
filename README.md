# 🤖 Data Analyst Agent

> **El analista conversacional para quien usa Excel y Power BI.** Pregúntale a tus archivos
> en español: el agente escribe y ejecuta el código de análisis, cada cifra sale de un cálculo
> verificado y, cuando los datos no permiten responder, te lo dice.

![status](https://img.shields.io/badge/status-en%20desarrollo-yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

<!-- TODO (Fase 5): reemplazar por un GIF de la demo -->
<!-- ![demo](docs/demo.gif) -->

## ¿Qué problema resuelve?

Quien trabaja con Excel y Power BI dedica horas a **preguntas ad hoc** ("¿por qué cayeron
las ventas en marzo?", "compárame las regiones"): limpiar el archivo, armar el modelo, escribir
medidas y diseñar visuales para una pregunta que se hace una sola vez. Los asistentes de IA
genéricos prometen atajar ese camino, pero en este proyecto medimos sus tres problemas:
**inventan cifras**, **responden con seguridad lo que los datos no permiten** y **tropiezan con
los archivos reales** (CSV de Excel en Colombia, códigos con cero inicial, `-999` como "sin
dato", Excel con varias hojas).

Este agente es un complemento para esas preguntas, no un reemplazo de los tableros oficiales.
Su principio: **confiable antes que completo**. Objetivo, usuarios, alcance por versión y metas
de calidad en [docs/ALCANCE.md](docs/ALCANCE.md); plan técnico en [docs/PLAN.md](docs/PLAN.md).

## Características

- 💬 Preguntas en español sobre archivos CSV y Excel, con respuestas en formato colombiano
- 🔢 **Cada cifra sale de código ejecutado:** un verificador rechaza cifras que no salen de un
  cálculo que terminó bien, y el código de cada paso es visible
- 🙅 **Honesto con los límites de los datos:** dice "no se puede" cuando falta el dato, advierte
  el alcance del dataset y no pronostica
- 📂 **Entiende los archivos tal como llegan:** detecta codificación, separador y decimal,
  conserva los códigos con cero inicial y avisa de problemas de calidad sin modificar los datos
- 📊 Gráficas interactivas con Plotly
- 🧠 Agente implementado desde cero con *tool use* (sin frameworks), agnóstico al proveedor
- 🔒 Código ejecutado en un proceso aislado, sin credenciales; bloqueo de archivos, red y
  procesos con seccomp en Linux (en curso)
- 💸 Costo $0 con la capa gratuita de Groq
- ✅ Evaluaciones automáticas con metas por categoría y comparación antes/después

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

> **Para uso local, limita Streamlit a localhost.** La app ejecuta código generado por el
> modelo; si escucha en todas las interfaces, cualquiera en tu red podría usarla. Crea
> `~/.streamlit/config.toml` (en Windows, `C:\Users\<usuario>\.streamlit\config.toml`) con:
>
> ```toml
> [server]
> address = "localhost"
> ```
>
> No va en el `.streamlit/config.toml` del repositorio porque ese archivo también lo usa el
> despliegue en Streamlit Cloud.

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

Metas de calidad de la v1 ([ALCANCE §8](docs/ALCANCE.md)), medidas con **3 repeticiones por
caso**; son el criterio de cierre de la Fase 4. Los errores de llamada (cupo, red) no cuentan.

<!-- TODO (Fase 4): completar la columna de resultados -->
| Categoría | Meta v1 | Resultado |
|---|---|---|
| Cálculo directo | ≥ 95 % | — |
| Datos con trampas | ≥ 80 % | — |
| Negativas correctas | ≥ 90 % | — |
| Interpretación y alcance | ≥ 70 % | — |
| Carga de archivos | 100 % | — |
| Seguridad | 100 % | — |

Casos en `evals/questions.yaml` (dataset de ventas) y `evals/questions_test_sets.yaml`
(datasets sintéticos de `data/test_sets/`, que reproducen problemas de datos reales: fechas
dd/mm/aaaa, nulos, duplicados, precios como texto, Excel con unidades en las columnas).

`data/test_sets/ventas_excel_colombia.csv` (exportado desde Excel en Colombia: separador
`;`, coma decimal, punto de miles y codificación Windows cp1252) no cargaba hasta la
Entrega B, que detecta codificación, separador y decimal.

Las evaluaciones se ejecutan con `evals/run_evals.py` (subconjuntos, repeticiones, `--resume`
tras un corte por cupo y `--compare`). Para medir una entrega antes y después en el mismo
día: `scripts/measure_commits.py`.

## Hoja de ruta

Alcance de cada versión en [ALCANCE §5](docs/ALCANCE.md); fases de la v1 en
[PLAN §8](docs/PLAN.md).

### v1 — Analista confiable de una tabla *(en curso)*

- [x] Fase 0 — Preparación
- [x] Fase 1 — Núcleo del agente
- [x] Fase 2 — Gráficas e interfaz web
- [ ] Fase 3 — Robustez y seguridad *(hechas: capa 0 del sandbox y entregas A–E del QA;
  falta la capa 2 con seccomp y los tests de ataque)*
- [ ] Fase 4 — Evaluaciones: las seis metas de calidad, con 3 repeticiones
- [ ] Fase 5 — Demo pública en Streamlit Community Cloud, con datasets precargados y cupo
  por visitante

### v2 — Modelo de datos

- [ ] Varios archivos por sesión, con relaciones que el usuario confirma
- [ ] DuckDB sobre Parquet para archivos de millones de filas
- [ ] Medidas tipo DAX (acumulado del año, variación interanual, participación)

### v3 — Conclusiones e informes

- [ ] Modo "conclusiones": hallazgos verificados a partir de varias preguntas
- [ ] Tablero exportable en HTML con KPI y varias gráficas

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

**Historial acotado y preguntas transaccionales**

- Cada llamada al modelo reenvía el contexto, y la capa gratuita de Groq admite 8.000
  tokens por minuto. Ahora `history.py` envía completo solo el último turno
  (`HISTORY_FULL_TURNS=1`); los anteriores van como pregunta + respuesta, sin código ni
  salidas, y todo el historial previo se limita a ~1.500 tokens (`HISTORY_TOKEN_BUDGET`).
  El verificador sigue usando todas las salidas, aunque ya no se envíen.
- Medido con 5 preguntas seguidas: la primera llamada de la 5.ª pregunta pasó de 2.391 a
  1.212 tokens, y el costo por llamada se estabiliza en lugar de crecer con cada pregunta.
- Si una llamada falla a mitad de una pregunta, esa pregunta se descarta y el historial
  queda como estaba (sin pasos huérfanos). Cada respuesta registra sus tokens totales.

**Hallazgos del QA del 2026-10-08** ([informe](docs/qa/INFORME_QA_2026-10-08.md))

- **A — evaluaciones:** ejecutor `evals/run_evals.py` y casos de los fallos del informe
  (`evals/questions_qa.yaml`). Base: 4 de 14 casos del QA acertados (29 %).
- **C — verificador honesto (H1, H8):** solo respalda cifras el código que terminó bien (ni
  `inspect_data` ni ejecuciones fallidas); no se acepta una respuesta con cifras si la última
  ejecución falló; sello "✓ Cifras calculadas con código"; las correcciones repiten la
  pregunta actual.
- **E — interpretación y alcance (H2, H7, H12):** identificadores no son clientes; decir el
  alcance del dataset; no pronosticar; mencionar huecos y porcentajes > 100 % de forma
  neutral; "no está permitido" en vez de "no tengo la capacidad". Medición antes/después con
  3 repeticiones en curso.
- **B — carga de archivos (H3, H4, H6, H9):** el archivo se carga en el sandbox y se guarda
  normalizado en Parquet (`loading.py`): detecta codificación, separador, decimal y miles;
  los códigos con ceros iniciales, las columnas mixtas y las de decimal ambiguo quedan como
  texto y se explica por qué. Se normaliza el formato, nunca el contenido: "-" y "N/A" se
  conservan y no se quitan duplicados. Excel: se listan las hojas y se elige una (cambiar de
  hoja empieza una conversación nueva). Errores de carga en español. La vista previa de la
  app sale del mismo Parquet que usa el agente. Cada tabla va en `data/<tabla>.parquet` con un
  catálogo (`data/catalog.json`), pensando en varios archivos relacionados en una v2. Los
  datos se protegen con un hash: si una ejecución los cambia, se restauran y se avisa.
- **D — alertas de calidad (H5):** `inspect_data` señala, sin corregir nada, nombres de
  columna con espacios, columnas casi numéricas con valores como "-" o "N/A", números
  guardados como texto, posibles centinelas (-999), filas duplicadas y porcentajes mayores que
  100 (en tono neutral: "revisar si es esperado").

## Licencia

MIT
