"""Genera datasets de prueba variados para el agente (semilla fija, reproducibles).

Cada archivo reproduce un problema típico de datos reales:

- empleados.csv            fechas dd/mm/aaaa, Sí/No, nulos, salarios en pesos
- ventas_excel_colombia.csv exportado desde Excel en Colombia: separador ';',
                            decimales con coma, miles con punto, codificación Windows (cp1252)
- clima.xlsx               Excel, columnas con espacios, tildes y unidades, nulos
- encuesta.csv             escala 1-5 con vacíos, rangos de edad (orden natural),
                            texto libre con comas y comillas
- inventario_sucio.csv     nombres de columna con espacios, filas duplicadas,
                            precios como texto "$1.250", stock con "N/A" y "-"

Uso: python generate_test_sets.py [carpeta_destino]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent


def empleados(rng: np.random.Generator) -> None:
    n = 240
    deptos = {
        "Tecnología": 6_500_000,
        "Ventas": 3_800_000,
        "Finanzas": 5_200_000,
        "Talento Humano": 4_100_000,
        "Operaciones": 3_200_000,
    }
    depto = rng.choice(list(deptos), n, p=[0.3, 0.25, 0.15, 0.1, 0.2])
    base = np.array([deptos[d] for d in depto])
    salario = (base * rng.uniform(0.7, 1.6, n) / 10_000).round() * 10_000
    ingreso = pd.Timestamp("2016-01-01") + pd.to_timedelta(rng.integers(0, 3500, n), "D")
    edad = rng.integers(21, 62, n).astype(float)
    edad[rng.choice(n, 12, replace=False)] = np.nan
    df = pd.DataFrame(
        {
            "id_empleado": [f"EMP-{i:04d}" for i in range(1, n + 1)],
            "departamento": depto,
            "fecha_ingreso": ingreso.strftime("%d/%m/%Y"),
            "salario_mensual": salario.astype(int),
            "edad": edad,
            "modalidad": rng.choice(["Presencial", "Remoto", "Híbrido"], n, p=[0.4, 0.2, 0.4]),
            "activo": rng.choice(["Sí", "No"], n, p=[0.85, 0.15]),
        }
    )
    df["edad"] = df["edad"].astype("Int64")
    df.to_csv(OUT / "empleados.csv", index=False, encoding="utf-8")


def ventas_excel_colombia(rng: np.random.Generator) -> None:
    n = 300
    ciudades = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga"]
    lineas = {"Café especial": 38_500.0, "Panela orgánica": 7_250.0, "Cacao en grano": 52_900.0}
    linea = rng.choice(list(lineas), n)
    cantidad = rng.integers(1, 60, n)
    unit = np.array([lineas[x] for x in linea]) * rng.uniform(0.9, 1.15, n)
    unit = unit.round(2)
    df = pd.DataFrame(
        {
            "Fecha": (
                pd.Timestamp("2025-07-01") + pd.to_timedelta(rng.integers(0, 184, n), "D")
            ).strftime("%d/%m/%Y"),
            "Ciudad": rng.choice(ciudades, n, p=[0.32, 0.24, 0.18, 0.14, 0.12]),
            "Línea de producto": linea,
            "Cantidad": cantidad,
            "Valor unitario": unit,
            "Valor total": (cantidad * unit).round(2),
        }
    ).sort_values("Fecha", key=lambda s: pd.to_datetime(s, dayfirst=True), kind="stable")
    # Formato de Excel en configuración regional de Colombia.
    df.to_csv(
        OUT / "ventas_excel_colombia.csv",
        index=False,
        sep=";",
        decimal=",",
        encoding="cp1252",
        float_format="%.2f",
    )


def clima(rng: np.random.Generator) -> None:
    dias = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    perfiles = {  # ciudad: (máx media, mín media, prob. lluvia, mm medio)
        "Bogotá": (19.5, 8.0, 0.55, 6.0),
        "Medellín": (27.5, 17.0, 0.50, 7.5),
        "Cali": (30.5, 19.0, 0.40, 6.5),
    }
    filas = []
    for ciudad, (tmax, tmin, p_lluvia, mm) in perfiles.items():
        estacional = 1.2 * np.sin(2 * np.pi * (dias.dayofyear - 60) / 365)
        maxima = (tmax + estacional + rng.normal(0, 1.3, len(dias))).round(1)
        minima = (tmin + estacional / 2 + rng.normal(0, 1.0, len(dias))).round(1)
        lluvia = np.where(rng.random(len(dias)) < p_lluvia, rng.exponential(mm, len(dias)), 0)
        lluvia = lluvia.round(1)
        lluvia[rng.choice(len(dias), 6, replace=False)] = np.nan  # sensor sin dato
        filas.append(
            pd.DataFrame(
                {
                    "Fecha": dias,
                    "Ciudad": ciudad,
                    "Temp. máxima (°C)": maxima,
                    "Temp. mínima (°C)": minima,
                    "Precipitación (mm)": lluvia,
                }
            )
        )
    pd.concat(filas, ignore_index=True).to_excel(OUT / "clima.xlsx", index=False)


def encuesta(rng: np.random.Generator) -> None:
    n = 350
    canal = rng.choice(["Web", "App", "Tienda física"], n, p=[0.4, 0.35, 0.25])
    sesgo = {"Web": 0.0, "App": 0.4, "Tienda física": -0.3}
    punt = np.clip(np.round(3.6 + np.array([sesgo[c] for c in canal]) + rng.normal(0, 1, n)), 1, 5)
    punt[rng.choice(n, 28, replace=False)] = np.nan
    recom = np.where(punt >= 4, "Sí", "No").astype(object)
    recom[rng.choice(n, 20, replace=False)] = None
    comentarios = [
        "Muy buena atención, volvería",
        'El envío tardó, pero el producto "llegó bien"',
        "Precios altos, calidad regular",
        "Todo perfecto",
        "La app se cierra, a veces, al pagar",
        "",
    ]
    df = pd.DataFrame(
        {
            "respuesta_id": range(1, n + 1),
            "fecha": (
                pd.Timestamp("2025-09-01") + pd.to_timedelta(rng.integers(0, 61, n), "D")
            ).strftime("%Y-%m-%d"),
            "canal": canal,
            "rango_edad": rng.choice(["18-24", "25-34", "35-44", "45-54", "55+"], n),
            "puntuacion": pd.array(punt, dtype="Int64"),
            "recomendaria": recom,
            "comentario": rng.choice(comentarios, n),
        }
    )
    df.to_csv(OUT / "encuesta.csv", index=False, encoding="utf-8")


def inventario_sucio(rng: np.random.Generator) -> None:
    n = 80
    categorias = ["Herramientas", "Pinturas", "Eléctricos", "Plomería"]
    precio = (rng.uniform(3_000, 180_000, n) / 50).round() * 50
    stock = rng.integers(0, 120, n).astype(object)
    sin_dato = rng.choice(n, 9, replace=False)
    for i, idx in enumerate(sin_dato):
        stock[idx] = "N/A" if i % 2 == 0 else "-"
    df = pd.DataFrame(
        {
            " Código Producto ": [f"P{i:03d}" for i in range(1, n + 1)],
            "Categoría": rng.choice(categorias, n),
            "Precio Unitario": [f"${int(p):,}".replace(",", ".") for p in precio],
            "STOCK": stock,
            "Bodega": rng.choice(["Norte", "Sur"], n),
        }
    )
    duplicadas = df.iloc[rng.choice(n, 6, replace=False)]
    df = pd.concat([df, duplicadas], ignore_index=True).sample(frac=1, random_state=SEED)
    df.to_csv(OUT / "inventario_sucio.csv", index=False, encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    for gen in (empleados, ventas_excel_colombia, clima, encuesta, inventario_sucio):
        gen(rng)
        print(f"ok: {gen.__name__}")
