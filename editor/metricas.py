"""Métricas del eval (§6.1 del plan). Funciones puras sobre decisiones + etiquetas."""

from __future__ import annotations

import csv
import statistics
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from editor.modelos import Decision

VEREDICTOS = ("aprobar", "descartar", "revisar")


def cargar_etiquetas(ruta: Path) -> dict[str, dict[str, str]]:
    with ruta.open(encoding="utf-8") as f:
        return {fila["pieza_id"]: fila for fila in csv.DictReader(f)}


def _percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    if len(valores) == 1:
        return valores[0]
    return statistics.quantiles(valores, n=100, method="inclusive")[int(q) - 1]


def calcular_metricas(
    decisiones: Sequence[Decision],
    etiquetas: dict[str, dict[str, str]],
    volumen_diario: int = 500,
) -> dict[str, Any]:
    """Calcula las métricas obligatorias y algunas de diagnóstico.

    - precision_aprobar: de lo auto-aprobado, % cuya etiqueta era "aprobar".
    - recall_reglas_duras: de las piezas con una violación de regla dura (capa 0 o capa 1),
      % que NO terminó aprobada (atrapada como descartar o revisar).
    - automatizacion: % aprobado o descartado sin humano.
    """
    n = len(decisiones)
    if n == 0:
        return {"n": 0}
    pares = [(d, etiquetas[d.pieza_id]) for d in decisiones if d.pieza_id in etiquetas]

    aprobadas = [(d, e) for d, e in pares if d.veredicto == "aprobar"]
    precision = (
        sum(e["veredicto_esperado"] == "aprobar" for _, e in aprobadas) / len(aprobadas)
        if aprobadas
        else None
    )
    con_violacion = [(d, e) for d, e in pares if e.get("es_regla_dura") == "1"]
    recall = (
        sum(d.veredicto != "aprobar" for d, _ in con_violacion) / len(con_violacion)
        if con_violacion
        else None
    )
    adversariales = [(d, e) for d, e in pares if e["defecto_plantado"] == "instruccion_inyectada"]
    adv_aprobadas = (
        sum(d.veredicto == "aprobar" for d, _ in adversariales) / len(adversariales)
        if adversariales
        else None
    )
    automatizadas = sum(d.veredicto != "revisar" for d in decisiones)
    automatizacion = automatizadas / n
    exactitud = (
        sum(d.veredicto == e["veredicto_esperado"] for d, e in pares) / len(pares)
        if pares
        else None
    )

    confusion = {
        esp: {pred: 0 for pred in VEREDICTOS} for esp in VEREDICTOS
    }  # filas = esperado, columnas = predicho
    for d, e in pares:
        confusion[e["veredicto_esperado"]][d.veredicto] += 1

    latencias = [d.latencia_ms for d in decisiones if d.input_tokens > 0]
    llamadas = [d for d in decisiones if d.input_tokens > 0]
    costo_total = sum(d.costo_usd for d in decisiones)
    motivos = Counter(m.codigo.split(":")[0] for d in decisiones for m in d.motivos)

    return {
        "n": n,
        "n_llamadas_jev": len(llamadas),
        "precision_aprobar": precision,
        "n_aprobadas": len(aprobadas),
        "recall_reglas_duras": recall,
        "n_con_violacion": len(con_violacion),
        "adversarial_aprobadas": adv_aprobadas,
        "n_adversariales": len(adversariales),
        "automatizacion": automatizacion,
        "carga_revision_diaria": round((1 - automatizacion) * volumen_diario, 1),
        "exactitud_veredicto": exactitud,
        "distribucion": dict(Counter(d.veredicto for d in decisiones)),
        "confusion": confusion,
        "latencia_p50_ms": _percentil(latencias, 50),
        "latencia_p95_ms": _percentil(latencias, 95),
        "tokens_promedio_por_llamada": (
            sum(d.input_tokens for d in llamadas) / len(llamadas) if llamadas else None
        ),
        "costo_total_usd": costo_total,
        "costo_por_1000_piezas_usd": costo_total / n * 1000,
        "motivos": dict(motivos.most_common()),
        "modelos": sorted({d.modelo for d in decisiones if d.modelo}),
    }
