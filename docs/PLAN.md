# Plan del proyecto: Data Analyst Agent

> El analista conversacional para quien usa Excel y Power BI: responde en español sobre
> archivos de datos, y cada cifra sale de código ejecutado y verificado.

---

## 1–5. Problema, solución, objetivos, alcance y usuarios

Estas secciones se reemplazaron el 9 de octubre de 2026, después de las pruebas con datos
reales, por **[docs/ALCANCE.md](ALCANCE.md)**: problema, usuario objetivo, propuesta de
valor, objetivos, alcance por versión (v1 una tabla, v2 modelo de datos, v3 conclusiones),
restricciones, **metas de calidad** y definición de terminado.

## 6. Requisitos

### Funcionales

- RF1. El usuario puede cargar un archivo CSV o XLSX.
- RF2. El usuario puede hacer preguntas en lenguaje natural y mantener una conversación con contexto.
- RF3. El agente inspecciona los datos antes de escribir código.
- RF4. El agente ejecuta código y basa su respuesta en el resultado real.
- RF5. El agente genera gráficas cuando la pregunta lo amerita.
- RF6. La respuesta muestra el código ejecutado.
- RF7. Si el código falla, el agente lo corrige y reintenta.

### No funcionales

- RNF1. **Seguridad:** el código generado no puede acceder a la red ni a archivos fuera de su área de trabajo, y se interrumpe si supera el tiempo máximo.
- RNF2. **Transparencia:** toda cifra se puede rastrear a un código ejecutado.
- RNF3. **Configurabilidad:** modelo, límites y reintentos se ajustan por variables de entorno.
- RNF4. **Calidad del código:** tipado, tests, linter (ruff) y estructura modular.
- RNF5. **Costo cero en desarrollo:** uso de capas gratuitas (Groq, Gemini), límite de iteraciones y manejo de límites de tasa (HTTP 429).
- RNF6. **Independencia del proveedor:** cambiar de modelo requiere solo modificar `LLM_PROVIDER` en el `.env`.

## 7. Arquitectura

```
┌──────────────┐     pregunta      ┌─────────────────────────────┐
│  Interfaz     │ ───────────────▶ │          Agente             │
│ (Streamlit /  │                  │  ciclo: razonar → herramienta│
│    CLI)       │ ◀─────────────── │        → observar → ...      │
└──────────────┘  respuesta +      └──────────────┬──────────────┘
                  código + gráfica                │ tool use
                                                  ▼
                         ┌────────────────────────────────────────┐
                         │               Herramientas              │
                         │  inspect_data │ run_python │ create_chart│
                         └───────────────────────┬────────────────┘
                                                 ▼
                                   ┌──────────────────────────┐
                                   │   Sandbox de ejecución    │
                                   │ proceso aislado, timeout, │
                                   │   sin red, área acotada   │
                                   └──────────────────────────┘
```

**Módulos:**

| Módulo | Responsabilidad |
|---|---|
| `llm.py` | Interfaz común para proveedores de modelos (Groq, Gemini, Anthropic opcional) |
| `agent.py` | Ciclo del agente, historial de mensajes, límite de iteraciones |
| `tools.py` | Definición (esquemas) e implementación de las herramientas |
| `sandbox.py` | Ejecución aislada de código con límites |
| `prompts.py` | Prompt de sistema y plantillas |
| `config.py` | Configuración desde variables de entorno |
| `cli.py` | Interfaz de línea de comandos |
| `app/streamlit_app.py` | Interfaz web |
| `evals/` | Preguntas de referencia y script de evaluación |

**Decisiones de diseño:**

- No se usan frameworks de agentes (LangChain, CrewAI, etc.). El objetivo es demostrar comprensión del mecanismo completo: manejo de mensajes, llamadas a herramientas, resultados y condiciones de parada.
- El agente es **agnóstico al proveedor**. Groq y Gemini exponen endpoints compatibles con la API de OpenAI, así que un solo adaptador cubre ambos cambiando la URL base y la clave. Desarrollo y demo cuestan $0 usando sus capas gratuitas.

## 8. Plan de desarrollo por fases

Cada fase termina con un *commit* etiquetado y algo funcionando.

### Fase 0 — Preparación (½ día)
- Crear repo, entorno virtual, dependencias, `.env`.
- Crear API keys gratuitas en Groq (principal) y Google AI Studio (alternativa).
- Conseguir datasets de ejemplo (ventas, ver `data/sample/README.md`).
- **Criterio de cierre:** `pytest` corre (aunque no haya tests reales) y la API key de Groq responde a una llamada de prueba.

### Fase 1 — Núcleo del agente (1–2 días)
- Capa `llm.py` con adaptador compatible OpenAI (Groq y Gemini) y reintentos ante límites de tasa.
- Ciclo del agente con *tool use*.
- Herramientas `inspect_data` y `run_python` (ejecución simple todavía).
- CLI: `python -m data_analyst_agent.cli data/sample/ventas.csv`.
- **Criterio de cierre:** responde correctamente 5 preguntas básicas sobre el dataset de ejemplo desde la terminal.

### Fase 2 — Gráficas e interfaz web (1–2 días)
- Herramienta `create_chart` (plotly o matplotlib).
- App de Streamlit: carga de archivo, chat, gráficas y código en línea.
- **Criterio de cierre:** una persona sin contexto puede subir un CSV y obtener una gráfica preguntando en español.

### Fase 3 — Robustez y seguridad (1–2 días)
- Sandbox: proceso separado, timeout, bloqueo de red y de imports peligrosos.
- Autocorrección ante errores, límite de iteraciones.
- Streaming de respuestas en la interfaz.
- Tests con pytest para herramientas y sandbox.
- **Criterio de cierre:** los tests de seguridad pasan (código malicioso de prueba es bloqueado) y el agente se recupera de errores provocados.

### Fase 4 — Evaluaciones (1 día)
- Casos con respuesta esperada en `evals/` (ventas, datasets con trampas, datos reales y los
  casos del informe de QA), agrupados en las categorías de [ALCANCE §8](ALCANCE.md).
- `evals/run_evals.py` ejecuta subconjuntos con repeticiones y reporta acierto, iteraciones y
  tokens; `scripts/measure_commits.py` compara antes y después de cada cambio.
- **Benchmark entre modelos:** correr las mismas evaluaciones con distintos proveedores y publicar la tabla comparativa.
- **Criterio de cierre:** se cumplen las seis metas de calidad de [ALCANCE §8](ALCANCE.md)
  (cálculo directo ≥ 95 %, datos con trampas ≥ 80 %, negativas correctas ≥ 90 %,
  interpretación y alcance ≥ 70 %, carga de archivos 100 %, seguridad 100 %), medidas con
  3 repeticiones por caso, y los resultados están publicados en el README.

### Fase 5 — Presentación y despliegue (1 día)
- README final con GIF de demo, diagrama y resultados de evaluación.
- Despliegue en Streamlit Community Cloud.
- **Criterio de cierre:** enlace público funcionando y README que se entiende en 30 segundos.

**Duración estimada total:** 6–9 días de trabajo.

## 9. Métricas de éxito

| Métrica | Meta |
|---|---|
| Metas de calidad por categoría | Ver [ALCANCE §8](ALCANCE.md) (3 repeticiones por caso) |
| Tests de ataque del sandbox | 100 % pasan |
| Iteraciones promedio por pregunta | Se reporta, sin meta estricta en v1 |
| Modelos comparados en el benchmark | ≥ 2 |
| Costo de desarrollo y demo | $0 |
| Tiempo de respuesta típico | Se reporta, sin meta estricta en v1 |
| Cobertura de tests en `tools` y `sandbox` | ≥ 70 % |

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El código generado hace algo dañino | Sandbox con proceso aislado, timeout, sin red, área de trabajo acotada |
| El agente entra en bucle y gasta tokens | Límite de iteraciones y de reintentos por pregunta |
| Respuestas inventadas | Prompt que obliga a responder solo con resultados ejecutados; evaluaciones que lo detectan |
| Archivos grandes saturan el contexto | `inspect_data` envía solo esquema y muestra, nunca el archivo completo |
| Límites de la capa gratuita (peticiones por minuto/día) | Reintentos con espera ante HTTP 429, pausa configurable entre llamadas, cambio de proveedor por `.env` |
| Cambios en las condiciones gratuitas de un proveedor | Arquitectura agnóstica: se migra a otro proveedor sin tocar el agente |
| Modelos gratuitos menos precisos | Prompt de sistema claro, autocorrección y evaluaciones para medir y ajustar |
| Exponer la API key | `.env` en `.gitignore`, secrets del proveedor en el despliegue |
| **(v2)** DuckDB choca con el aislamiento de la v1: en Linux, el código del modelo corre con seccomp que niega abrir archivos tras la precarga, pero DuckDB abre los Parquet en cada consulta | A evaluar en la v2: un **proceso intermediario DuckDB** que reciba SQL por un canal ya abierto y solo pueda leer `data/` (`enable_external_access=false`, `allowed_directories`, `lock_configuration=true`, sin instalar ni cargar extensiones), mientras el código del modelo sigue sin poder abrir archivos |

## 11. Trabajo futuro (v2+)

El alcance de cada versión está en [ALCANCE §5](ALCANCE.md), y lo que queda fuera en
cualquier versión (conectores a sistemas, pronósticos, reportes gobernados) en
[ALCANCE §6](ALCANCE.md). Notas técnicas para preparar esas versiones:

- **v2, modelo de datos:** varios archivos relacionados y archivos grandes (millones de filas),
  probablemente con DuckDB sobre Parquet. La v1 ya guarda cada tabla en
  `data/<tabla>.parquet` con un catálogo (`data/catalog.json`) para no cerrar esa puerta. Ver
  el riesgo de DuckDB en la sección 10.
- **v3, conclusiones e informes:** tablero exportable en HTML con varias gráficas.
- Ideas sin versión asignada: exponer las herramientas como **servidor MCP** y un modo
  multiagente (uno planifica, otro ejecuta, otro verifica).

## 12. Qué demuestra este proyecto (para el CV)

- Diseño e implementación de agentes LLM desde cero (*tool use*, ciclo de razonamiento).
- Arquitectura agnóstica al proveedor y benchmark comparativo entre modelos.
- Ejecución segura de código generado por IA.
- Evaluación sistemática de sistemas de IA.
- Ingeniería de software: arquitectura modular, tests, configuración, despliegue.
- Producto completo: desde el problema hasta la demo pública.
