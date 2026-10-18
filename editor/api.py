"""API HTTP (FastAPI). Arranque:  uvicorn editor.api:app --reload

Endpoints (§7.2 del plan):
    POST /evaluar                    → Decision
    POST /evaluar/lote               → {decisiones, resumen}
    GET  /cola                       → piezas en REVISAR con evidencia legible
    POST /cola/{pieza_id}/resolver   → guarda el veredicto humano (etiqueta nueva)
    GET  /metricas                   → automatización, motivos, costo acumulado
"""

from __future__ import annotations

import statistics
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from editor.almacen import Almacen
from editor.evidencia import describir_evidencia
from editor.jev_client import FaltaEnCacheError
from editor.modelos import Pieza
from editor.pipeline import Editor

estado: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    estado.setdefault("editor", Editor())
    estado.setdefault("almacen", Almacen())
    yield


app = FastAPI(title="Editor de guardia (30X × JEV)", version="0.1.0", lifespan=lifespan)


class PiezaIn(BaseModel):
    id: str
    canal_destino: Literal["linkedin", "instagram_tiktok", "newsletter", "anuncio_evento"]
    formato: str = ""
    texto: str
    metadatos: dict[str, Any] = {}


class ResolucionIn(BaseModel):
    veredicto: Literal["aprobar", "descartar"]
    nota: str = ""


async def _evaluar(piezas: list[PiezaIn]) -> list[dict[str, Any]]:
    editor: Editor = estado["editor"]
    almacen: Almacen = estado["almacen"]
    objs = [Pieza.desde_dict(p.model_dump()) for p in piezas]
    try:
        decisiones = await editor.evaluar_lote_async(objs)
    except FaltaEnCacheError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    for p, d in zip(objs, decisiones, strict=True):
        almacen.guardar(p, d)
    return [d.a_dict() for d in decisiones]


@app.post("/evaluar")
async def evaluar(pieza: PiezaIn) -> dict[str, Any]:
    return (await _evaluar([pieza]))[0]


@app.post("/evaluar/lote")
async def evaluar_lote(piezas: list[PiezaIn]) -> dict[str, Any]:
    decisiones = await _evaluar(piezas)
    latencias = sorted(d["latencia_ms"] for d in decisiones if d["input_tokens"] > 0)
    resumen = {
        "n": len(decisiones),
        "conteos": {
            v: sum(d["veredicto"] == v for d in decisiones)
            for v in ("aprobar", "descartar", "revisar")
        },
        "costo_total_usd": sum(d["costo_usd"] for d in decisiones),
        "latencia_p50_ms": statistics.median(latencias) if latencias else None,
        "latencia_max_ms": latencias[-1] if latencias else None,
    }
    return {"decisiones": decisiones, "resumen": resumen}


@app.get("/cola")
def cola() -> list[dict[str, Any]]:
    return [
        {"pieza_id": c["pieza_id"], "canal": c["canal"], "texto": c["texto"],
         "evidencia": describir_evidencia(c["decision"]), "motivos": [m.__dict__ for m in c["decision"].motivos]}
        for c in estado["almacen"].cola()
    ]  # fmt: skip


@app.post("/cola/{pieza_id}/resolver")
def resolver(pieza_id: str, body: ResolucionIn) -> dict[str, str]:
    try:
        estado["almacen"].resolver(pieza_id, body.veredicto, body.nota)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"pieza {pieza_id} no evaluada") from e
    return {"ok": "guardado", "pieza_id": pieza_id}


@app.get("/metricas")
def metricas() -> dict[str, Any]:
    return estado["almacen"].metricas()
