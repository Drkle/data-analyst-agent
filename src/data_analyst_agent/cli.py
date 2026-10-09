"""Interfaz de línea de comandos.

Uso: python -m data_analyst_agent.cli data/sample/ventas.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import plotly.io as pio

from data_analyst_agent.agent import Agent, AgentResult
from data_analyst_agent.config import ConfigError, load_settings
from data_analyst_agent.llm import LLMError, create_client
from data_analyst_agent.tools import DataTools

EXIT_WORDS = {"salir", "exit", "quit"}
CODE_TOOLS = {"run_python", "create_chart"}


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
        tools = DataTools(args.archivo, timeout=settings.sandbox_timeout)
    except (ConfigError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    agent = Agent.from_settings(create_client(settings), tools, settings)
    print(f"Analizando {args.archivo.name} con {settings.provider} ({settings.model}).")
    print(f"Carpeta de trabajo de esta sesión: {tools.workdir}")
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
            print(f"No pude responder: {exc}")
            if args.verbose and exc.detail:
                print(f"--- detalle técnico ---\n{exc.detail}")
            continue
        _print_result(result, verbose=args.verbose, charts_dir=tools.workdir / "charts")


def _print_result(result: AgentResult, verbose: bool, charts_dir: Path) -> None:
    for step in result.steps:
        print(f"\n[{step.tool}]")
        if step.tool in CODE_TOOLS:
            print(step.arguments.get("code", ""))
        if verbose:
            print(f"--- salida ---\n{step.output}")
    for index, chart in enumerate(result.charts, start=1):
        path = charts_dir / f"grafica_{len(list(charts_dir.glob('*.html'))) + 1}.html"
        pio.from_json(chart.figure_json).write_html(path, include_plotlyjs="cdn")
        print(f"\nGráfica {index} ({chart.kind}, {chart.points} puntos): {path.resolve()}")
    print(f"\n{result.answer}")
    verification = result.verification
    if verification.last_execution_failed:
        print("\n⚠️ La última ejecución de código falló: las cifras pueden no venir de un cálculo.")
    if verification.unverified:
        print(f"\n⚠️ Cifras que no salen de ningún cálculo: {', '.join(verification.unverified)}")
    elif verification.checked and not verification.last_execution_failed:
        print("\n✓ Cifras calculadas con código")
    summary = f"{result.iterations} iteraciones"
    if result.tool_format_errors:
        summary += f" · llamadas repetidas por formato inválido: {result.tool_format_errors}"
    if verification.triggers:
        times = "vez" if verification.triggers == 1 else "veces"
        summary += (
            f" · verificador: se activó {verification.triggers} {times}, "
            f"cifras corregidas: {verification.corrected}"
        )
    print(f"\n({summary})")


if __name__ == "__main__":
    raise SystemExit(main())
