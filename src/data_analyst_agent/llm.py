"""Capa de abstracción del proveedor de modelos. (Fase 1)

Objetivo: que el agente no dependa de un proveedor concreto.
El proveedor se elige con LLM_PROVIDER en el .env.

Diseño previsto:
- Interfaz común `LLMClient.chat(messages, tools) -> LLMResponse`
  (texto + llamadas a herramientas en un formato interno propio).
- Adaptador `OpenAICompatibleClient` para Groq y Gemini, que exponen
  endpoints compatibles con la API de OpenAI (cambia solo base_url y key).
- Adaptador `AnthropicClient` opcional.
- Reintentos con espera ante errores de límite de tasa (HTTP 429),
  habituales en las capas gratuitas.
"""
