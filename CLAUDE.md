# Contexto para Claude Code

Proyecto: agente analista de datos. Ver docs/PLAN.md para problema, alcance y fases.

Reglas:
- NO usar frameworks de agentes (LangChain, CrewAI, etc.). El ciclo del agente se escribe a mano.
- El agente es agnóstico al proveedor: toda llamada al modelo pasa por src/data_analyst_agent/llm.py.
  Proveedores: Groq y Gemini (capa gratuita) y Anthropic (opcional).
- Tener en cuenta los límites de la capa gratuita: reintentos ante HTTP 429 y pausas entre llamadas.
- Antes de escribir código de una fase, proponer el diseño y esperar aprobación.
- Explicar cada cambio en lenguaje claro antes de pedir aprobación.
- Nunca hacer commit sin que el usuario lo pida.
- Código con type hints, tests en tests/, estilo ruff (line-length 100).
- Nunca leer ni imprimir el contenido de .env.
- Trabajar fase por fase según docs/PLAN.md y marcar avances en el README.
