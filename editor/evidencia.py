"""Convierte una Decision en evidencia legible para el editor humano.

Ejemplo de salida:
    "cifra_sin_fuente = 0.58 (revisar)"
    "voz_30x dudó entre los niveles 1 y 2 (confianza 0.41)"
"""

from __future__ import annotations

from editor.modelos import Decision


def _duda_score(qid: str, r: dict) -> str | None:
    probs = r.get("probabilities") or {}
    if len(probs) < 2:
        return None
    top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:2]
    (n1, p1), (n2, p2) = top
    if p1 - p2 < 0.25:  # dos niveles con masa parecida: vale la pena mostrarlo
        a, b = sorted((n1, n2))
        return f"{qid} dudó entre los niveles {a} y {b} (p={p1:.2f}/{p2:.2f}, confianza {r['confidence']:.2f})"
    return None


def describir_evidencia(decision: Decision) -> list[str]:
    """Lista de frases cortas: primero los motivos, luego las dudas de los Scores."""
    lineas = []
    for m in decision.motivos:
        valor = f"{m.valor:.2f}" if isinstance(m.valor, float) else str(m.valor)
        lineas.append(f"{m.codigo} = {valor} → {m.efecto} [{m.fuente}]")
    for qid, r in decision.respuestas_crudas.items():
        if r.get("type") == "score" and (duda := _duda_score(qid, r)):
            lineas.append(duda)
    if decision.calidad is not None:
        lineas.append(f"calidad ponderada = {decision.calidad:.2f}")
    return lineas
