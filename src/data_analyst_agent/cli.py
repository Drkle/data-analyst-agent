"""Interfaz de línea de comandos.

Uso: python -m data_analyst_agent.cli data/sample/ventas.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data_analyst_agent.agent import Agent, AgentResult
from data_analyst_agent.config import ConfigError, load_settings
from data_analyst_agent.llm import LLMError, create_client
from data_analyst_agent.tools import DataTools

EXIT_WORDS = {"salir", "exit", "quit"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pregúntale a tus datos en lenguaje natural.")
    parser.add_argument("archivo", type=Path, help="archivo CSV o XLSX a analizar")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="muestra también la salida de cada herramienta"
    )
    args = parser.parse_args(argv)
    if not args.archivo.exists():
        parser.error(f"no existe el archivo {args.archivo}")

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Error de configuración: {exc}")
        return 1

    tools = DataTools(args.archivo, timeout=settings.sandbox_timeout)
    agent = Agent(create_client(settings), tools, max_iterations=settings.max_iterations)
    print(f"Analizando {args.archivo.name} con {settings.provider} ({settings.model}).")
    print("Escribe 'salir' para terminar.")

    while True:
        try:
            question = input("\nPregunta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            return 0
        try:
            result = agent.run(question)
        except LLMError as exc:
            print(f"Error al consultar el modelo: {exc}")
            continue
        _print_result(result, verbose=args.verbose)


def _print_result(result: AgentResult, verbose: bool) -> None:
    for step in result.steps:
        print(f"\n[{step.tool}]")
        if step.tool == "run_python":
            print(step.arguments.get("code", ""))
        if verbose:
            print(f"--- salida ---\n{step.output}")
    print(f"\n{result.answer}")
    print(f"\n({result.iterations} iteraciones)")


if __name__ == "__main__":
    raise SystemExit(main())
