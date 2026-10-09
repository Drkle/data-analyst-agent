# Objetivo y alcance

> Versión 2 — 9 de octubre de 2026. Reemplaza las secciones 1 a 5 del plan original
> (`docs/PLAN.md`), escritas antes de las pruebas con datos reales.

## 1. Problema

Quien trabaja a diario con Excel y Power BI pasa buena parte del tiempo en **preguntas ad hoc**:
"¿por qué cayeron las ventas en marzo?", "compárame las regiones", "¿qué destaca de este
archivo?". Responderlas exige limpiar el archivo, armar un modelo, escribir medidas DAX y
diseñar visuales: horas de trabajo para una pregunta que se hace una sola vez.

Los asistentes de IA genéricos prometen atajar ese camino, pero tienen tres problemas que
medimos en este proyecto:

1. **Inventan cifras.** Un modelo con una regla explícita que se lo prohibía inventó 7 de 12
   valores mensuales.
2. **Responden con seguridad lo que los datos no permiten.** Dieron "350 clientes" contando
   respuestas, o "957 hurtos en Colombia" con un registro que solo cubre 3 modalidades.
3. **Tropiezan con los archivos reales.** CSV exportados desde Excel en Colombia (`;`, coma
   decimal, cp1252), códigos con cero inicial, `-999` como "sin dato", Excel con varias hojas.

**El hueco:** falta un analista conversacional en el que se pueda confiar: que acierte o diga
honestamente que no puede, que muestre de dónde sale cada cifra y que entienda los archivos
tal como llegan.

## 2. Usuario objetivo

**Principal:** profesionales que usan Excel y Power BI a diario (analistas de negocio,
controllers, coordinadores, funcionarios públicos) y trabajan con exportes de sistemas y
datos abiertos, en español.

**Escenarios:**

| Escenario | Hoy | Con el agente |
|---|---|---|
| Pregunta puntual sobre un exporte | Abrir Excel, filtrar, tabla dinámica, gráfica | Una pregunta en español; respuesta, gráfica y código |
| Explorar un archivo nuevo | Revisar columnas a mano, descubrir los problemas tarde | El agente describe la estructura y advierte los problemas de los datos |
| Cruzar varios archivos (v2) | Modelo de datos en Power BI, relaciones, DAX | El agente propone las relaciones y responde sobre el conjunto |
| Preparar conclusiones (v3) | Armar un tablero y redactar hallazgos | El agente genera un informe con cifras verificadas |

**Secundario:** analistas que programan y quieren acelerar la exploración inicial y reutilizar
el código generado.

## 3. Propuesta de valor y posicionamiento

**El analista conversacional para quien usa Excel y Power BI**: un complemento para las
preguntas ad hoc, no un reemplazo de los tableros oficiales.

| Frente a | Diferencia |
|---|---|
| Chatbots genéricos | Cada cifra sale de código ejecutado y verificado; el código es visible |
| Copilot en Power BI | Abierto, funciona con archivos sueltos sin montar un modelo, verifica cifras, entiende formatos colombianos |
| Tableros de Power BI | No compite: los reportes gobernados necesitan cifras idénticas en cada consulta, y un modelo de lenguaje varía |

**Principio central: confiable antes que completo.** Ante la duda, el agente dice qué no
puede responder y por qué, en vez de dar una cifra plausible.

## 4. Objetivos

### Objetivo general

Construir un agente analista que permita a usuarios de Excel y Power BI analizar uno o varios
archivos de datos en lenguaje natural, obteniendo respuestas, gráficas y conclusiones
**confiables**: cada cifra sale de un cálculo verificable y, cuando los datos no permiten
responder, el agente lo dice.

### Objetivos específicos

1. **Agente:** ciclo de razonamiento con *tool use* implementado desde cero, independiente del
   proveedor del modelo.
2. **Confiabilidad:** controles en código (verificador de cifras, evidencia solo de código
   exitoso, preguntas transaccionales) y reglas de interpretación (alcance, conceptos,
   pronósticos).
3. **Datos reales:** carga robusta de CSV y Excel en formatos colombianos, con el principio
   "normalizar el formato, nunca el contenido".
4. **Seguridad:** el código generado se ejecuta aislado, sin acceso a credenciales, red ni
   archivos ajenos, también en la nube.
5. **Medición:** evaluaciones automáticas con metas por categoría, repeticiones y comparación
   antes/después de cada cambio.
6. **Escala (v2):** varios archivos relacionados y archivos de millones de filas.
7. **Síntesis (v3):** conclusiones e informes con varias gráficas.
8. **Demo pública** sostenible con la capa gratuita.

## 5. Alcance por versión

### v1 — Analista confiable de una tabla *(en curso)*

| Área | Incluye |
|---|---|
| Archivos | Un CSV o Excel por sesión, hasta 50 MB. CSV en UTF-8 o cp1252, separado por `,` `;` tabulador o `|`, con coma o punto decimal. Excel con selección de hoja |
| Preguntas | Agregaciones, filtros, rankings, comparaciones, tendencias temporales, estadística descriptiva, medidas tipo DAX simples (participación, variación) |
| Respuestas | Texto en español con formato colombiano, gráficas Plotly, código de cada paso |
| Honestidad | Negarse cuando falta el dato, advertir el alcance del dataset, señalar huecos y valores fuera de rango, no pronosticar |
| Calidad de datos | `inspect_data` advierte columnas con espacios, valores no numéricos en columnas numéricas, centinelas (`-999`), duplicados y porcentajes mayores que 100 |
| Seguridad | Sandbox con entorno limpio (capa 0), bloqueo de procesos y red (seccomp) y aislamiento de archivos (bubblewrap o equivalente) |
| Interfaz | App de Streamlit y CLI |
| Demo | Streamlit Community Cloud, con datasets de ejemplo precargados y cupo por visitante |

### v2 — Modelo de datos

- Varios archivos por sesión, con detección de relaciones (llaves) que el usuario confirma.
- Motor DuckDB sobre Parquet para archivos de millones de filas.
- Medidas tipo DAX: acumulado del año, variación interanual, participación sobre total.
- Preguntas que cruzan tablas ("ventas por segmento de cliente").

### v3 — Conclusiones e informes

- Modo "conclusiones": el agente se hace varias preguntas y redacta hallazgos verificados.
- Tablero exportable (HTML) con KPI y varias gráficas.

## 6. Fuera de alcance (en cualquier versión)

- Reemplazar reportes gobernados: actualización programada, permisos por usuario, publicación
  para toda la organización.
- Conectores a sistemas (SQL Server, SharePoint, ERP): el agente trabaja con archivos.
- Pronósticos y modelos de machine learning.
- *Big data* de escala de clúster (cientos de GB o más).
- Datos sensibles en la demo pública: muestras de los datos se envían al proveedor del modelo.

## 7. Restricciones

| Restricción | Consecuencia en el diseño |
|---|---|
| Costo $0 (capa gratuita de Groq: ~8.000 tokens/minuto, ~200.000/día) | Historial acotado, salidas recortadas, demo con cupo; evaluaciones por subconjuntos |
| Streamlit Cloud: sin Landlock, con seccomp, 3 GB de RAM | El aislamiento de archivos se resuelve con bubblewrap o con seccomp sin apertura de archivos |
| Privacidad | La demo advierte que no se suban datos sensibles |
| Modelos no deterministas | Toda medición usa repeticiones; ninguna conclusión con una sola corrida |

## 8. Metas de calidad (v1)

Se miden con `evals/run_evals.py`, **3 repeticiones por caso**. La tasa de acierto es aciertos
sobre ejecuciones; los errores de llamada (cupo, red) no cuentan.

| Categoría | Qué mide | Casos | Línea base | Meta v1 |
|---|---|---|---|---|
| Cálculo directo | Agregaciones y rankings sobre datos limpios | `questions.yaml` | Sin fallos en las pruebas manuales con `ventas.csv` | **≥ 95 %** |
| Datos con trampas | Fechas `dd/mm`, nulos, `-999`, duplicados, "-" | `questions_test_sets.yaml`, `questions_real.yaml` | 8/12 sintéticos; 11/11 reales (QA del 8/10) | **≥ 80 %** |
| Negativas correctas | Decir "no se puede" cuando falta el dato o se pide un pronóstico | casos `not_computable` | 2 fallos de 6 en el QA | **≥ 90 %** |
| Interpretación y alcance | Advertir alcance, huecos y valores fuera de rango | `qa-hur-01`, `qa-air-01`, `qa-edu-01` | 0/3 (medición base del 9/10) | **≥ 70 %** |
| Carga de archivos | Formatos soportados cargan bien y lo no soportado da un error claro en español | tests del cargador + `t-vco-*`, `qa-xls-*` | 1/5 en el QA | **100 %** |
| Seguridad | Ataques ejecutados directamente en el sandbox, sin pasar por el modelo; inyección en celdas | tests de ataque + `qa-iny-01`, `qa-red-01` | 5/5 frenados por el modelo; sandbox sin probar | **100 %** |

**Eficiencia y experiencia** (se reportan, sin meta estricta en v1): tokens por pregunta,
iteraciones promedio y tiempo de respuesta. Referencia actual: ~4.000–5.000 tokens y ~20–70 s
por pregunta.

## 9. Definición de terminado (v1)

La v1 está terminada cuando:

1. Se cumplen las seis metas de calidad, con 3 repeticiones, y los resultados están en el README.
2. Las capas de aislamiento funcionan en Streamlit Cloud, comprobado con el sondeo y los tests de ataque.
3. La demo pública está desplegada con datasets precargados y cupo por visitante.
4. El README explica el problema, la arquitectura, las decisiones y los resultados, con un GIF.
5. El CI pasa en Ubuntu y Windows.

## 10. Principios de diseño

1. **Confiable antes que completo.** Mejor "no se puede con estos datos" que una cifra plausible.
2. **El modelo decide qué hacer; el código decide qué es aceptable.** Autonomía para
   interpretar, programar y explicar; controles en código para evidencia, memoria, permisos y
   límites.
3. **Cada control se justifica con una medición.** Si una prueba no mostró el fallo, no se añade el control.
4. **Normalizar el formato, nunca el contenido.** El cargador no limpia datos; los problemas se
   señalan para que el agente y el usuario decidan.
5. **Medir antes y después.** Ningún cambio se da por bueno sin comparación con repeticiones.
