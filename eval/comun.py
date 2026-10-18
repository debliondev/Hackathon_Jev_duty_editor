"""Utilidades compartidas por los scripts del eval."""

from __future__ import annotations

import json
from pathlib import Path

from editor.config import RAIZ
from editor.metricas import cargar_etiquetas
from editor.modelos import Decision, Pieza

DIR_DATOS = RAIZ / "data" / "synthetic"
DIR_RESULTADOS = RAIZ / "eval" / "resultados"
RUTA_PIEZAS = DIR_DATOS / "piezas.jsonl"
RUTA_ETIQUETAS = DIR_DATOS / "etiquetas.csv"


def cargar_piezas(split: str = "all") -> list[Pieza]:
    """Piezas del golden set filtradas por split (dev | test | all)."""
    etiquetas = cargar_etiquetas(RUTA_ETIQUETAS)
    piezas = [Pieza.desde_dict(json.loads(linea)) for linea in RUTA_PIEZAS.open(encoding="utf-8")]
    return [p for p in piezas if split == "all" or etiquetas[p.id]["split"] == split]


def nombre_corrida(split: str, idioma: str, rotacion: int = 0) -> str:
    return f"{split}_{idioma}" + (f"_rot{rotacion}" if rotacion else "")


def guardar_decisiones(decisiones: list[Decision], nombre: str) -> Path:
    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_RESULTADOS / f"decisiones_{nombre}.jsonl"
    with ruta.open("w", encoding="utf-8") as f:
        for d in decisiones:
            f.write(json.dumps(d.a_dict(), ensure_ascii=False) + "\n")
    return ruta


def cargar_decisiones(nombre: str) -> list[Decision]:
    ruta = DIR_RESULTADOS / f"decisiones_{nombre}.jsonl"
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}. Corre primero: python -m eval.correr_eval --split ...")
    decisiones = [Decision.desde_dict(json.loads(linea)) for linea in ruta.open(encoding="utf-8")]
    # Las probabilidades de Scores vuelven con claves str desde JSON.
    from editor.jev_client import normalizar_respuestas

    for d in decisiones:
        d.respuestas_crudas = normalizar_respuestas(d.respuestas_crudas)
    return decisiones
