# Datasets reales de datos.gov.co

`scripts/real_datasets.py` descarga 4 datasets públicos y calcula las respuestas de referencia
con pandas, **sin el agente**. Escribe los datos en `data/real/` y los casos en
`evals/questions_real.yaml`.

| Clave | Dataset | Publica | Filas aprox. | Trampa que prueba |
|---|---|---|---|---|
| `trm` | Tasa de Cambio Representativa del Mercado (`32sa-8pi3`) | Superfinanciera | 8.400 | Una fila vale para varios días (fines de semana y festivos): la TRM del 1/1/2025 no está en una fila con esa fecha |
| `hurtos` | Reporte Hurto por Modalidades (`d4fr-sbn2`) | Policía Nacional | 44.000 | Hay que sumar `CANTIDAD`, no contar filas; fechas dd/mm/aaaa como texto |
| `aire` | Calidad del aire ECCDM Piedecuesta (`kh7q-whyx`) | CDMB | 17.500 | Valores `-999` que significan "sin dato"; columnas como `PM2.5 (µg/m³)` |
| `educacion` | Estadísticas en educación por departamento (`ji8i-4anb`) | MinEducación | 460 | 40 columnas; posible fila de total nacional; "Bogotá, D.C." escrito de varias formas |

Cada dataset tiene además una pregunta que **no se puede** responder con sus datos.

## Uso

Desde la raíz del proyecto, con el entorno virtual activo:

```
python scripts/real_datasets.py
```

Antes de calcular, el script valida que las fechas y los números se leyeron bien. Si algo
no cuadra, se detiene y explica qué pasó, en lugar de escribir respuestas falsas.

## Licencia

Los cuatro datasets tienen licencia **CC BY-SA 4.0**: se pueden usar citando la fuente.
**Los CSV no se suben al repositorio** (`data/real/*.csv` está en `.gitignore`): solo el
script, este README y el YAML. Cualquiera puede regenerar los datos con el script. Sin los
CSV, los casos de `evals/questions_real.yaml` y los `qa-*` que los usan se omiten.

## Ojo

- TRM y hurtos se actualizan. Las preguntas usan 2025 completo para que las respuestas no
  cambien, pero si vuelves a descargar, vuelve a generar el YAML.
- `evals/questions_real.yaml` lo genera el script: no lo edites a mano, porque se
  sobrescribe. Los casos escritos a mano van en `evals/questions_qa.yaml`.
