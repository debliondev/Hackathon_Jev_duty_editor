"""Construye la batería de preguntas de JEV a partir de config/reglas.yaml.

Se trabaja con una ESPECIFICACIÓN PLANA (dicts con la misma forma que el SDK:
{"type": "noul"|"score"|"choice", "instructions": ..., "criteria": ...}) por dos razones:
  1. La clave de caché se calcula sobre estos dicts (editar un texto ⇒ nueva clave).
  2. El modo replay no necesita importar ni instanciar nada del SDK.
Solo en modo live/record se convierten a objetos del SDK con `a_objetos_sdk`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.config import Configuracion

EspecPreguntas = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class MetaPreguntas:
    """Lo que el motor de decisión necesita saber de las preguntas (sin los textos)."""

    accion_noul: dict[str, str]  # id → descartar | revisar
    alerta_noul: frozenset[str]  # ids de Nouls que disparan alerta
    niveles_score: dict[str, int]  # id → número de niveles
    choices: tuple[str, ...]


def _rotar(criterios: dict[str, Any], k: int) -> dict[str, Any]:
    """Rota el orden de las opciones de un Choice (para el test de permutación)."""
    items = list(criterios.items())
    if not items:
        return criterios
    k %= len(items)
    return dict(items[k:] + items[:k])


def construir_preguntas(
    config: Configuracion, idioma: str | None = None, rotacion_choices: int = 0
) -> EspecPreguntas:
    """Devuelve {id_pregunta: especificación} para todas las capas (1, 2 y 3).

    idioma: "en" | "es". Por defecto, `idioma_preguntas` de policy.yaml.
    rotacion_choices: cuántas posiciones rotar las opciones de los Choices (0 = orden original).
    """
    idioma = idioma or config.policy.get("idioma_preguntas", "en")
    reglas = config.reglas
    espec: EspecPreguntas = {}
    for qid, r in reglas["nouls"].items():
        t = r[idioma]
        espec[qid] = {"type": "noul", "instructions": t["instructions"], "criteria": t["criteria"]}
    for qid, r in reglas["scores"].items():
        t = r[idioma]
        espec[qid] = {"type": "score", "instructions": t["instructions"], "criteria": t["criteria"]}
    for qid, r in reglas["choices"].items():
        t = r[idioma]
        espec[qid] = {
            "type": "choice",
            "instructions": t["instructions"],
            "criteria": _rotar(t["criteria"], rotacion_choices),
        }
    return espec


def meta_preguntas(config: Configuracion) -> MetaPreguntas:
    reglas = config.reglas
    return MetaPreguntas(
        accion_noul={qid: r["accion"] for qid, r in reglas["nouls"].items()},
        alerta_noul=frozenset(qid for qid, r in reglas["nouls"].items() if r.get("alerta")),
        niveles_score={qid: len(r["en"]["criteria"]) for qid, r in reglas["scores"].items()},
        choices=tuple(reglas["choices"]),
    )


def a_objetos_sdk(espec: EspecPreguntas) -> dict[str, Any]:
    """Convierte la especificación plana en objetos Noul/Score/Choice del SDK de TypeSafe."""
    from typesafe_sdk import Choice, Noul, Score  # import tardío: replay no necesita el SDK

    clases = {"noul": Noul, "score": Score, "choice": Choice}
    return {
        qid: clases[q["type"]](instructions=q["instructions"], criteria=q["criteria"])
        for qid, q in espec.items()
    }
