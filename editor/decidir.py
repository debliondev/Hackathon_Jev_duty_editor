"""Motor de decisión (§4.2 del plan). Lógica PURA: sin I/O, sin red, sin leer archivos.

Recibe los prechequeos, las respuestas de JEV (ya normalizadas) y los umbrales; devuelve el veredicto
y sus motivos. Como es pura, se puede:
  - testear con respuestas falsas (tests/test_decidir.py);
  - re-ejecutar miles de veces con otros umbrales sin volver a llamar a JEV (barrido y slider de la UI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from editor.modelos import Motivo, ResultadoPrechequeos, Veredicto
from editor.preguntas import MetaPreguntas


@dataclass
class ResultadoDecision:
    veredicto: Veredicto
    motivos: list[Motivo]
    calidad: float | None
    alertas: list[str] = field(default_factory=list)


def calidad_normalizada(
    respuestas: dict[str, dict[str, Any]], meta: MetaPreguntas
) -> dict[str, float]:
    """Lleva cada Score a 0..1: score / (n_niveles − 1)."""
    return {
        qid: respuestas[qid]["score"] / (n - 1)
        for qid, n in meta.niveles_score.items()
        if qid in respuestas
    }


def decidir(
    prechequeos: ResultadoPrechequeos,
    respuestas: dict[str, dict[str, Any]] | None,
    umbrales: dict[str, float],
    pesos_calidad: dict[str, float],
    meta: MetaPreguntas,
    canal_destino: str,
    canal_conf_min: float,
) -> ResultadoDecision:
    """Aplica el algoritmo del plan, paso a paso (los números de paso coinciden con §4.2)."""
    motivos: list[Motivo] = []
    alertas: list[str] = []

    # Paso 1 · Capa 0 con efecto "descartar" ⇒ DESCARTAR sin llamar a JEV.
    duras = prechequeos.fallas("descartar")
    if duras:
        motivos = [Motivo(c.codigo, "p0", c.detalle, "descartar") for c in duras]
        return ResultadoDecision("descartar", motivos, None)

    # Las fallas de capa 0 que no descartan se acumulan como motivos de revisión.
    for c in prechequeos.fallas("revisar") + prechequeos.fallas("marcar"):
        motivos.append(Motivo(c.codigo, "p0", c.detalle, "revisar"))

    if respuestas is None:
        raise ValueError("Faltan las respuestas de JEV y la capa 0 no descartó la pieza.")

    # Paso 2 · Reglas duras (Nouls). Valor alto = hay problema.
    for qid, accion in meta.accion_noul.items():
        p = respuestas[qid]["noul"]
        if p >= umbrales["noul_accion"]:
            motivos.append(Motivo(qid, "regla", round(p, 3), accion))  # type: ignore[arg-type]
            if qid in meta.alerta_noul:
                alertas.append(f"{qid}={p:.2f}")
        elif p >= umbrales["noul_revision"]:
            motivos.append(Motivo(qid, "regla", round(p, 3), "revisar"))

    # Ruteo (Choices): canal sugerido distinto del destino con confianza suficiente ⇒ revisar.
    canal = respuestas.get("canal_ideal")
    if canal and canal["choice"] != canal_destino and canal["confidence"] >= canal_conf_min:
        motivos.append(
            Motivo(
                f"canal_sugerido:{canal['choice']}",
                "canal",
                round(canal["confidence"], 3),
                "revisar",
            )
        )

    # Paso 5 (se calcula antes para poder reportarla siempre).
    norm = calidad_normalizada(respuestas, meta)
    calidad = round(sum(pesos_calidad[d] * v for d, v in norm.items()), 4)

    # Paso 3 · Algún motivo "descartar" ⇒ DESCARTAR.
    if any(m.efecto == "descartar" for m in motivos):
        return ResultadoDecision("descartar", motivos, calidad, alertas)

    # Paso 4 · Dimensión de calidad con baja confianza ⇒ REVISAR.
    for qid in meta.niveles_score:
        conf = respuestas[qid]["confidence"]
        if conf < umbrales["conf_min"]:
            motivos.append(Motivo(f"baja_confianza:{qid}", "calidad", round(conf, 3), "revisar"))

    # Paso 6 · Ya hay motivos de revisión (reglas, capa 0, canal o confianza) ⇒ REVISAR.
    if motivos:
        return ResultadoDecision("revisar", motivos, calidad, alertas)

    # Paso 7 · Calidad suficiente ⇒ APROBAR.
    if calidad >= umbrales["calidad_min"]:
        return ResultadoDecision("aprobar", motivos, calidad, alertas)

    # Paso 8 · Calidad muy baja ⇒ DESCARTAR, citando la dimensión más débil.
    if calidad < umbrales["calidad_descarte"]:
        peor = min(norm, key=norm.__getitem__)
        motivos.append(Motivo(f"calidad_baja:{peor}", "calidad", round(norm[peor], 3), "descartar"))
        return ResultadoDecision("descartar", motivos, calidad, alertas)

    # Paso 9 · Zona gris de calidad ⇒ REVISAR.
    motivos.append(Motivo("calidad_zona_gris", "calidad", calidad, "revisar"))
    return ResultadoDecision("revisar", motivos, calidad, alertas)
