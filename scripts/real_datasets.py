"""Descarga 4 datasets públicos de datos.gov.co y calcula las respuestas de referencia.

Las respuestas se calculan aquí, con pandas y sin el agente, para que sirvan de verdad
de referencia en las evaluaciones. El script valida que las fechas y los números se
hayan leído bien antes de calcular nada; si algo no cuadra, se detiene y lo dice.

Datasets (todos con licencia CC BY-SA 4.0: se pueden usar citando la fuente):
- trm:       Tasa de Cambio Representativa del Mercado (Superfinanciera)        32sa-8pi3
- hurtos:    Reporte Hurto por Modalidades (Policía Nacional)                   d4fr-sbn2
- aire:      Calidad del aire ECCDM Piedecuesta (CDMB)                          kh7q-whyx
- educacion: Estadísticas en educación por departamento (MinEducación)          ji8i-4anb

Uso (desde la raíz del proyecto):
    python scripts/real_datasets.py                 # descarga (si no existen) y calcula
    python scripts/real_datasets.py --refresh       # vuelve a descargar
    python scripts/real_datasets.py --no-download   # usa los archivos de data/real/

Salida: data/real/*.csv y evals/questions_real.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]  # raíz del proyecto (el script está en scripts/)
DATA_DIR = ROOT / "data" / "real"
OUTPUT = ROOT / "evals" / "questions_real.yaml"
URL = "https://www.datos.gov.co/api/views/{id}/rows.csv?accessType=DOWNLOAD"

DATASETS = {
    "trm": ("32sa-8pi3", "trm.csv", "Superintendencia Financiera de Colombia"),
    "hurtos": ("d4fr-sbn2", "hurtos_policia.csv", "Policía Nacional de Colombia (DIJIN)"),
    "aire": ("kh7q-whyx", "aire_piedecuesta.csv", "CDMB, Santander"),
    "educacion": ("ji8i-4anb", "educacion_departamentos.csv", "Ministerio de Educación Nacional"),
}

MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
REFUSAL = [
    "no se puede",
    "no es posible",
    "no puedo",
    "no permite",
    "no hay datos",
    "no contiene",
    "no incluye",
    "no dispon",
]
SENTINELS = (-999, -9999, 9999)
TODAY = datetime.now(tz=UTC).date()


class DataProblem(Exception):
    """Los datos no tienen la forma esperada: mejor detenerse que calcular algo falso."""


# --- Utilidades ----------------------------------------------------------------------------


def norm(name: str) -> str:
    """'Temperatura Ambiente (Celsius)' -> 'temperatura_ambiente_celsius'."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def col(df: pd.DataFrame, exact: tuple[str, ...] = (), contains: tuple[str, ...] = ()) -> str:
    """Busca una columna por nombre normalizado: primero coincidencia exacta, luego parcial."""
    names = {norm(c): c for c in df.columns}
    for e in exact:
        if e in names:
            return names[e]
    for n, original in names.items():
        if contains and all(k in n for k in contains):
            return original
    raise DataProblem(f"No encontré la columna {exact or contains}. Columnas: {list(df.columns)}")


def to_num(s: pd.Series) -> pd.Series:
    """Convierte a número aceptando '3,238.88', '3.238,88' y '3238.88'."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    t = s.astype(str).str.strip().str.replace(r"[^\d,.\-]", "", regex=True)
    both = t.str.contains(",") & t.str.contains(r"\.")
    if both.any():
        last_comma = t.str.rfind(",") > t.str.rfind(".")
        t = t.where(~(both & last_comma), t.str.replace(".", "", regex=False))
        t = t.where(~(both & ~last_comma), t.str.replace(",", "", regex=False))
    t = t.str.replace(",", ".", regex=False)
    return pd.to_numeric(t.replace("", None), errors="coerce")


def to_date(s: pd.Series, formats: list[str] | None = None) -> pd.Series:
    """Lee fechas probando todos los formatos. Exige que exactamente uno lea todos los valores.

    Si dos formatos distintos (día/mes y mes/día) leen todo con resultados diferentes, la
    fecha es ambigua y el script se detiene en lugar de adivinar.
    """
    s = s.astype(str).str.strip()
    ok: dict[str, pd.Series] = {}
    for fmt in formats or DATE_FORMATS:
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.notna().all():
            ok[fmt] = parsed
    if not ok:
        raise DataProblem(
            f"Ningún formato de fecha leyó todos los valores. Ejemplos: {s.head(3).tolist()}"
        )
    distintos = {tuple(v.astype("int64")) for v in ok.values()}
    if len(distintos) > 1:
        raise DataProblem(
            f"Fechas ambiguas: sirven varios formatos {list(ok)}. Ejemplos: {s.head(3).tolist()}"
        )
    fmt, parsed = next(iter(ok.items()))
    print(f"  Formato de fecha detectado: {fmt}")
    return parsed


DATE_FORMATS = [
    "ISO8601",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %I:%M:%S %p",
    "%m/%d/%Y",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
]


def key_word(name: str) -> str:
    """Palabra más larga del nombre, para comprobarla en la respuesta: 'La Guajira' -> 'guajira'."""
    return max(norm(name).split("_"), key=len)


def fmt(x: float) -> str:
    """Número en formato colombiano para el resumen en pantalla."""
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s.removesuffix(",00")


def numeric(value: float, tolerance: float = 0.01) -> dict:
    return {"type": "numeric", "value": round(float(value), 2), "tolerance": tolerance}


def contains(*terms: str) -> dict:
    return {"type": "contains", "terms": list(terms)}


def not_computable(mentions: list[str], forbidden: list[str]) -> dict:
    return {
        "type": "not_computable",
        "refusal_any": REFUSAL,
        "mentions_all": mentions,
        "must_not_contain": forbidden,
    }


def case(cid: str, dataset: str, question: str, checks: list[dict], comment: str = "") -> dict:
    return {
        "id": cid,
        "dataset": f"data/real/{DATASETS[dataset][1]}",
        "question": question,
        "checks": checks,
        "_comment": comment,
    }


def require_year(dates: pd.Series, year: int, name: str) -> None:
    if not (dates.dt.year == year).any():
        raise DataProblem(f"{name}: no hay datos de {year}. Rango: {dates.min()} a {dates.max()}")


# --- Un bloque por dataset -----------------------------------------------------------------


def trm(df: pd.DataFrame) -> list[dict]:
    valor = to_num(df[col(df, ("valor",))])
    desde = to_date(df[col(df, ("vigenciadesde", "vigencia_desde"))])
    hasta = to_date(df[col(df, ("vigenciahasta", "vigencia_hasta"))])
    if (desde > hasta).any():
        raise DataProblem("TRM: hay filas con 'desde' posterior a 'hasta': fechas mal leídas.")
    if valor.isna().any() or not valor.between(500, 10_000).all():
        raise DataProblem("TRM: hay valores vacíos o fuera de rango: números mal leídos.")
    require_year(desde, 2025, "TRM")

    dia = pd.Timestamp("2025-01-01")
    vigente = valor[(desde <= dia) & (hasta >= dia)]
    if len(vigente) != 1:
        raise DataProblem(f"TRM: {len(vigente)} filas vigentes el 1/1/2025; esperaba 1.")
    exacta = (desde == dia).sum()

    y = desde.dt.year == 2025
    imax, imin = valor[y].idxmax(), valor[y].idxmin()
    print(
        f"  TRM vigente el 1/1/2025: {fmt(vigente.iloc[0])} "
        f"(filas que empiezan exactamente ese día: {exacta}; buscar solo por fecha exacta falla)"
    )
    print(
        f"  Máxima 2025: {fmt(valor[imax])} desde {desde[imax].date()}; "
        f"mínima 2025: {fmt(valor[imin])} desde {desde[imin].date()}"
    )
    return [
        case(
            "r-trm-01",
            "trm",
            "¿Cuál fue la TRM vigente el 1 de enero de 2025?",
            [numeric(vigente.iloc[0])],
            "El 1 de enero es festivo: la TRM de ese día viene de una fila cuya vigencia "
            f"empieza antes. Buscar solo VIGENCIADESDE == 2025-01-01 da {exacta} filas.",
        ),
        case(
            "r-trm-02",
            "trm",
            "¿Cuál fue la TRM más alta de 2025 y en qué mes?",
            [numeric(valor[imax]), contains(MESES[desde[imax].month - 1])],
            f"Rige desde {desde[imax].date()}.",
        ),
        case(
            "r-trm-03",
            "trm",
            "¿Cuál fue la TRM más baja de 2025?",
            [numeric(valor[imin])],
            f"Rige desde {desde[imin].date()}.",
        ),
        case(
            "r-trm-04",
            "trm",
            "¿Cuál será la TRM el próximo mes?",
            [not_computable([], ["la trm será de", "la trm estará en"])],
            "Pronóstico: los datos son históricos.",
        ),
    ]


def hurtos(df: pd.DataFrame) -> list[dict]:
    cantidad = to_num(df[col(df, ("cantidad",))])
    fecha = to_date(df[col(df, ("fecha_hecho",), ("fecha",))])
    tipo = df[col(df, ("tipo_de_hurto",), ("tipo", "hurto"))].astype(str).str.strip()
    depto = df[col(df, ("departamento",))].astype(str).str.strip()
    if cantidad.isna().any() or (cantidad < 1).any():
        raise DataProblem("Hurtos: CANTIDAD vacía o menor que 1.")
    if not fecha.dt.year.between(2009, TODAY.year).all():
        raise DataProblem("Hurtos: años fuera de rango: fechas mal leídas.")
    require_year(fecha, 2025, "Hurtos")

    y = fecha.dt.year == 2025
    total, filas = cantidad[y].sum(), int(y.sum())
    por_tipo = cantidad[y].groupby(tipo[y]).sum().sort_values(ascending=False)
    por_depto = cantidad[y].groupby(depto[y]).sum().sort_values(ascending=False)
    print(
        f"  Hurtos 2025: {fmt(total)} (filas: {fmt(filas)}; contar filas en vez de sumar "
        f"CANTIDAD da otro número)"
        if total != filas
        else f"  Hurtos 2025: {fmt(total)} (en 2025 cada fila es un hurto: filas = total)"
    )
    print(
        f"  Tipo con más casos: {por_tipo.index[0]} ({fmt(por_tipo.iloc[0])}); "
        f"departamento: {por_depto.index[0]} ({fmt(por_depto.iloc[0])})"
    )
    return [
        case(
            "r-hur-01",
            "hurtos",
            "¿Cuántos hurtos se registraron en total en 2025?",
            [numeric(total, 0)],
            f"Hay que sumar CANTIDAD; el número de filas de 2025 es {filas}. Ojo: el dataset no "
            "cubre todos los hurtos del país, solo las modalidades que reporta.",
        ),
        case(
            "r-hur-02",
            "hurtos",
            "¿Qué tipo de hurto tuvo más casos en 2025 y cuántos?",
            [contains(key_word(por_tipo.index[0])), numeric(por_tipo.iloc[0], 0)],
            f"Tipo: {por_tipo.index[0]}.",
        ),
        case(
            "r-hur-03",
            "hurtos",
            "¿Qué departamento registró más hurtos en 2025?",
            [contains(key_word(por_depto.index[0])), numeric(por_depto.iloc[0], 0)],
            f"Departamento: {por_depto.index[0]}.",
        ),
        case(
            "r-hur-04",
            "hurtos",
            "¿Cuál fue el valor promedio de los bienes hurtados en 2025?",
            [
                not_computable(
                    ["valor"], ["valor promedio fue", "valor promedio de los bienes hurtados es"]
                )
            ],
            "El dataset no tiene el valor de lo robado.",
        ),
    ]


def aire(df: pd.DataFrame) -> list[dict]:
    fecha = to_date(df[col(df, (), ("fecha",))])
    pm25_raw = to_num(df[col(df, (), ("pm2_5",))])
    temp_raw = to_num(df[col(df, (), ("temperatura",))])
    if fecha.duplicated().mean() > 0.01:
        raise DataProblem("Aire: muchas fechas repetidas: probablemente mal leídas.")
    require_year(fecha, 2025, "Aire")

    def clean(s: pd.Series) -> pd.Series:
        return s.mask(s.isin(SENTINELS) | (s < 0))

    pm25, temp = clean(pm25_raw), clean(temp_raw)
    y = fecha.dt.year == 2025
    centinelas = int(pm25_raw[y].isin(SENTINELS).sum())
    prom, ingenuo = pm25[y].mean(), pm25_raw[y].mean()
    mensual = pm25[y].groupby(fecha[y].dt.month).mean()
    mes = int(mensual.idxmax())
    itemp = temp[y].idxmax()
    print(
        f"  PM2.5 promedio 2025: {fmt(prom)} µg/m³ (valores centinela: {centinelas}; "
        f"incluyéndolos el promedio sería {fmt(ingenuo)})"
    )
    print(
        f"  Mes con más PM2.5: {MESES[mes - 1]} ({fmt(mensual[mes])}); "
        f"temperatura máxima: {fmt(temp[itemp])} °C el {fecha[itemp]}"
    )
    return [
        case(
            "r-air-01",
            "aire",
            "¿Cuál fue la concentración promedio de PM2.5 en 2025?",
            [numeric(prom)],
            f"Hay {centinelas} valores -999 (o similares) que significan 'sin dato'. "
            f"Promediarlos da {round(ingenuo, 2)}.",
        ),
        case(
            "r-air-02",
            "aire",
            "¿Qué mes de 2025 tuvo el PM2.5 promedio más alto?",
            [contains(MESES[mes - 1]), numeric(mensual[mes])],
        ),
        case(
            "r-air-03",
            "aire",
            "¿Cuál fue la temperatura más alta registrada en 2025?",
            [numeric(temp[itemp])],
            f"Registrada el {fecha[itemp]}.",
        ),
    ]


def educacion(df: pd.DataFrame) -> list[dict]:
    anio = to_num(df[col(df, ("ano", "a_o", "anno"))])
    depto = df[col(df, ("departamento",))].astype(str).str.strip()
    cobertura = to_num(df[col(df, ("cobertura_neta",))])
    desercion = to_num(df[col(df, ("desercion", "deserci_n"))])
    if not anio.between(2000, TODAY.year).all():
        raise DataProblem("Educación: años fuera de rango.")
    year = int(anio.max())
    agregados = depto.str.upper().str.contains("NACIONAL|TOTAL|COLOMBIA")
    if agregados.any():
        print(f"  Filas agregadas excluidas del ranking: {sorted(depto[agregados].unique())}")
    if cobertura.dropna().max() <= 1.5:
        raise DataProblem("Educación: la cobertura parece estar en proporción (0-1), no en %.")

    y = (anio == year) & ~agregados
    cob = cobertura[y].groupby(depto[y]).mean().sort_values(ascending=False)
    bogota = depto.str.upper().str.contains("BOGOT")
    des_bog = desercion[(anio == year) & bogota]
    if len(des_bog) != 1:
        raise DataProblem(f"Educación: {len(des_bog)} filas de Bogotá en {year}; esperaba 1.")
    sobre_90 = int((cob > 90).sum())
    print(
        f"  Año más reciente: {year}. Mayor cobertura neta: {cob.index[0]} ({fmt(cob.iloc[0])} %)"
    )
    print(
        f"  Deserción Bogotá {year}: {fmt(des_bog.iloc[0])} %; "
        f"departamentos con cobertura neta > 90 %: {sobre_90} de {len(cob)}"
    )
    return [
        case(
            "r-edu-01",
            "educacion",
            f"¿Qué departamento tuvo la mayor cobertura neta en {year} y cuál fue?",
            [contains(key_word(cob.index[0])), numeric(cob.iloc[0])],
            f"Departamento: {cob.index[0]}.",
        ),
        case(
            "r-edu-02",
            "educacion",
            f"¿Cuál fue la tasa de deserción de Bogotá en {year}?",
            [numeric(des_bog.iloc[0])],
            "El nombre puede venir como 'Bogotá, D.C.' o similar: hay que buscarlo con "
            "flexibilidad.",
        ),
        case(
            "r-edu-03",
            "educacion",
            f"¿Cuántos departamentos tuvieron una cobertura neta mayor al 90 % en {year}?",
            [numeric(sobre_90, 0)],
            "Si hay filas de total nacional, no deben contarse como departamento.",
        ),
        case(
            "r-edu-04",
            "educacion",
            f"¿Cuál fue el puntaje promedio en las pruebas Saber 11 por departamento en {year}?",
            [not_computable(["saber"], ["puntaje promedio fue", "puntaje promedio es de"])],
            "El dataset no tiene resultados de pruebas.",
        ),
    ]


# --- Programa principal --------------------------------------------------------------------


def download(dataset_id: str, path: Path) -> None:
    request = urllib.request.Request(
        URL.format(id=dataset_id), headers={"User-Agent": "data-analyst-agent-evals"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        path.write_bytes(response.read())


def to_yaml(cases: list[dict]) -> str:
    header = (
        "# Casos de evaluación con datasets reales de datos.gov.co (licencia CC BY-SA 4.0).\n"
        f"# Generado por real_datasets.py el {TODAY.isoformat()}. Las respuestas se\n"
        "# calcularon con pandas, sin el agente. Si vuelves a descargar los datos, regenera\n"
        "# este archivo: TRM y hurtos se actualizan y sus cifras pueden cambiar.\n"
        "# Fuentes: " + "; ".join(f"{p} ({i})" for i, _, p in DATASETS.values()) + "\n"
    )
    blocks = []
    for c in cases:
        comment = c.pop("_comment")
        text = yaml.safe_dump([c], allow_unicode=True, sort_keys=False, width=100)
        blocks.append((f"# {comment}\n" if comment else "") + text)
    return header + "\n" + "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="vuelve a descargar los datos")
    parser.add_argument("--no-download", action="store_true", help="no descarga nada")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    builders = {"trm": trm, "hurtos": hurtos, "aire": aire, "educacion": educacion}
    cases, failed = [], []
    for key, (dataset_id, filename, publisher) in DATASETS.items():
        path = args.data_dir / filename
        print(f"\n[{key}] {publisher} ({dataset_id})")
        try:
            if not args.no_download and (args.refresh or not path.exists()):
                print("  Descargando...")
                download(dataset_id, path)
            df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
            print(f"  {len(df):,} filas, {len(df.columns)} columnas".replace(",", "."))
            cases += builders[key](df)
        except (DataProblem, OSError, KeyError, ValueError) as exc:
            failed.append(key)
            print(f"  PROBLEMA: {exc}")

    if cases:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(to_yaml(cases), encoding="utf-8")
        print(f"\n{len(cases)} casos escritos en {args.output}")
    if failed:
        print(f"Sin casos para: {', '.join(failed)}. Revisa los mensajes de arriba.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
