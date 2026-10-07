# Plan del proyecto: Data Analyst Agent

> Agente de IA que responde preguntas sobre datos tabulares en lenguaje natural, escribiendo y ejecutando su propio código de análisis de forma segura.

---

## 1. Problema

Muchas personas y equipos tienen datos valiosos en archivos CSV y Excel (ventas, inventarios, encuestas, finanzas), pero obtener respuestas de ellos exige saber programar o dominar herramientas como Excel avanzado, SQL o Power BI.

Esto genera tres problemas concretos:

1. **Dependencia de perfiles técnicos.** Una pregunta simple ("¿qué producto vendió más en marzo?") termina en una solicitud al analista de datos y horas o días de espera.
2. **Análisis superficial.** Quien no programa se queda en filtros y tablas dinámicas básicas; no explora correlaciones, tendencias ni anomalías.
3. **Riesgo al usar IA "a ciegas".** Pegar datos en un chatbot genérico produce respuestas que suenan bien pero no están calculadas: el modelo puede inventar cifras porque no ejecuta ningún cálculo real.

**El hueco:** falta una herramienta que combine la facilidad del lenguaje natural con la precisión de ejecutar código real sobre los datos, mostrando cómo llegó a cada respuesta.

## 2. Solución propuesta

Un agente que:

- Recibe un archivo de datos y una pregunta en lenguaje natural.
- Inspecciona la estructura del archivo (columnas, tipos, valores de ejemplo).
- Escribe código Python (pandas) para responder, **lo ejecuta en un entorno aislado** y lee el resultado.
- Si el código falla, lee el error y se corrige solo.
- Devuelve la respuesta con el código usado y, cuando aplica, una gráfica.

La diferencia clave frente a un chatbot genérico: **cada cifra sale de un cálculo ejecutado, no de la memoria del modelo**, y el usuario puede verificar el código.

## 3. Objetivos

### Objetivo general

Construir un agente de análisis de datos basado en LLM, implementado sin frameworks de agentes, que responda preguntas en lenguaje natural sobre archivos tabulares ejecutando código de forma segura y verificable.

### Objetivos específicos

1. Implementar desde cero el ciclo de un agente (razonar → usar herramienta → observar → repetir) y *tool use*, independiente del proveedor del modelo.
7. Comparar el desempeño de varios modelos (benchmark) con las mismas evaluaciones.
2. Diseñar herramientas para inspeccionar datos, ejecutar código y generar gráficas.
3. Ejecutar el código generado en un entorno aislado con límites de tiempo, memoria y acceso al sistema.
4. Ofrecer una interfaz web de chat donde se suba un archivo y se vean respuestas y gráficas.
5. Medir la calidad del agente con un conjunto de evaluaciones automáticas (porcentaje de respuestas correctas).
6. Documentar y desplegar el proyecto con una demo pública.

## 4. Alcance

### Dentro del alcance (v1)

| Área | Incluye |
|---|---|
| Datos | Archivos CSV y Excel (.xlsx) de hasta ~50 MB, una tabla a la vez |
| Preguntas | Agregaciones, filtros, rankings, tendencias temporales, estadística descriptiva, comparaciones |
| Herramientas del agente | `inspect_data`, `run_python`, `create_chart` |
| Seguridad | Ejecución aislada, tiempo máximo por ejecución, bloqueo de red y de archivos fuera del área de trabajo |
| Autocorrección | Reintento automático cuando el código falla (máximo configurable) |
| Interfaz | CLI para desarrollo + app web en Streamlit |
| Calidad | Tests unitarios (pytest) + evaluaciones con preguntas de respuesta conocida |
| Despliegue | Demo pública en Streamlit Community Cloud |

### Fuera del alcance (v1)

- Conexión a bases de datos (SQL, BigQuery, etc.).
- Varias tablas relacionadas a la vez (joins entre archivos).
- Modelos de machine learning o predicciones.
- Usuarios, autenticación o historial persistente.
- Datos sensibles o de producción: la demo es para datos de ejemplo.

Estos puntos quedan como **trabajo futuro** (sección 10) y muestran hacia dónde puede crecer el proyecto.

## 5. Usuarios objetivo

- **Perfil no técnico** (emprendedor, administrativo, estudiante): quiere respuestas rápidas sin programar.
- **Analista o desarrollador**: quiere acelerar la exploración inicial de un dataset y ver el código para reutilizarlo.

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
- 15–20 preguntas con respuesta esperada en `evals/questions.yaml`.
- Script que ejecuta todas y reporta porcentaje de acierto, iteraciones y tiempo promedio.
- **Benchmark entre modelos:** correr las mismas evaluaciones con distintos proveedores y publicar la tabla comparativa.
- **Criterio de cierre:** reporte de evaluación reproducible con ≥ 80 % de acierto, publicado en el README.

### Fase 5 — Presentación y despliegue (1 día)
- README final con GIF de demo, diagrama y resultados de evaluación.
- Despliegue en Streamlit Community Cloud.
- **Criterio de cierre:** enlace público funcionando y README que se entiende en 30 segundos.

**Duración estimada total:** 6–9 días de trabajo.

## 9. Métricas de éxito

| Métrica | Meta |
|---|---|
| Acierto en evaluaciones | ≥ 80 % |
| Tests de seguridad del sandbox | 100 % pasan |
| Iteraciones promedio por pregunta | ≤ 4 |
| Modelos comparados en el benchmark | ≥ 2 |
| Costo de desarrollo y demo | $0 |
| Tiempo de respuesta típico | < 20 s |
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

## 11. Trabajo futuro (v2+)

- Conexión a bases de datos SQL.
- Varios archivos y joins.
- Exportar el análisis como notebook o informe PDF.
- Exponer las herramientas como **servidor MCP** para usarlas desde Claude u otros clientes.
- Modo multiagente: un agente planifica, otro ejecuta, otro verifica.

## 12. Qué demuestra este proyecto (para el CV)

- Diseño e implementación de agentes LLM desde cero (*tool use*, ciclo de razonamiento).
- Arquitectura agnóstica al proveedor y benchmark comparativo entre modelos.
- Ejecución segura de código generado por IA.
- Evaluación sistemática de sistemas de IA.
- Ingeniería de software: arquitectura modular, tests, configuración, despliegue.
- Producto completo: desde el problema hasta la demo pública.
