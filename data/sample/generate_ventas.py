"""Genera data/sample/ventas.csv: ventas sintéticas reproducibles (semilla fija).

Uso: python data/sample/generate_ventas.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_ROWS = 500
OUTPUT = Path(__file__).with_name("ventas.csv")

# producto: (categoría, precio base)
PRODUCTS: dict[str, tuple[str, float]] = {
    "Laptop": ("Electrónica", 850.0),
    "Monitor": ("Electrónica", 220.0),
    "Audífonos": ("Electrónica", 60.0),
    "Silla de oficina": ("Muebles", 150.0),
    "Escritorio": ("Muebles", 280.0),
    "Lámpara": ("Muebles", 35.0),
    "Cuaderno": ("Papelería", 4.5),
    "Bolígrafos (caja)": ("Papelería", 8.0),
    "Resma de papel": ("Papelería", 6.0),
}
REGIONS = ["Norte", "Sur", "Este", "Oeste", "Centro"]


def generate(seed: int = SEED, n_rows: int = N_ROWS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    products = rng.choice(list(PRODUCTS), size=n_rows)
    days = rng.integers(0, 365, size=n_rows)
    dates = pd.Timestamp("2025-01-01") + pd.to_timedelta(days, unit="D")
    base_prices = np.array([PRODUCTS[p][1] for p in products])
    df = pd.DataFrame(
        {
            "fecha": dates.strftime("%Y-%m-%d"),
            "producto": products,
            "categoria": [PRODUCTS[p][0] for p in products],
            "region": rng.choice(REGIONS, size=n_rows),
            "unidades": rng.integers(1, 21, size=n_rows),
            "precio": (base_prices * rng.uniform(0.9, 1.1, size=n_rows)).round(2),
        }
    )
    return df.sort_values("fecha", kind="stable").reset_index(drop=True)


if __name__ == "__main__":
    generate().to_csv(OUTPUT, index=False)
    print(f"Generado {OUTPUT} ({N_ROWS} filas)")
