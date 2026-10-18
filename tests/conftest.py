"""Fixtures compartidas. Todos los tests corren SIN red: respuestas JEV falsas o caché temporal."""

from __future__ import annotations

from typing import Any

import pytest

from editor.config import cargar_configuracion
from editor.preguntas import meta_preguntas


@pytest.fixture(scope="session")
def config():
    return cargar_configuracion()


@pytest.fixture(scope="session")
def meta(config):
    return meta_preguntas(config)


def respuestas_falsas(
    nouls: dict[str, float] | None = None,
    scores: dict[str, float] | None = None,
    confianzas: dict[str, float] | None = None,
    canal: tuple[str, float] = ("linkedin", 0.9),
    linea: tuple[str, float] = ("ventas", 0.8),
) -> dict[str, dict[str, Any]]:
    """Construye respuestas con la misma forma que devuelve JEV (normalizadas).

    Por defecto: ninguna regla violada (p=0.02) y calidad máxima con confianza alta.
    """
    r: dict[str, dict[str, Any]] = {}
    for qid in ["promesa_garantizada", "cifra_sin_fuente", "oferta_inexistente", "persona_real",
                "ataque_terceros", "instruccion_inyectada", "tema_sensible"]:  # fmt: skip
        r[qid] = {"type": "noul", "noul": (nouls or {}).get(qid, 0.02)}
    for qid in ["gancho", "claridad", "valor_accionable", "voz_30x", "cta"]:
        s = (scores or {}).get(qid, 3.0)
        r[qid] = {
            "type": "score",
            "score": s,
            "confidence": (confianzas or {}).get(qid, 0.9),
            "probabilities": {0: 0.0, 1: 0.0, 2: 1 - (s - 2) if s >= 2 else 0, 3: max(s - 2, 0)},
        }
    r["canal_ideal"] = {"type": "choice", "choice": canal[0], "confidence": canal[1],
                        "probabilities": {canal[0]: canal[1]}}  # fmt: skip
    r["linea_programa"] = {"type": "choice", "choice": linea[0], "confidence": linea[1],
                           "probabilities": {linea[0]: linea[1]}}  # fmt: skip
    return r
