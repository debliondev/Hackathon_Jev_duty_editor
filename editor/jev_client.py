"""Wrapper de JEV con tres modos: live, record y replay.

    JEV_MODE=live    → siempre llama a la API (no escribe la caché).
    JEV_MODE=record  → usa la caché si ya existe la respuesta; si no, llama a la API y la guarda.
    JEV_MODE=replay  → solo lee cache/jev_respuestas.json. Sin red y sin API key.

Clave de caché = sha256(json(state) + json(preguntas) + modelo). Cualquier cambio en la pieza, en el
texto de una regla o en la versión del modelo produce una clave nueva (y obliga a re-grabar).

Nunca se loggea la API key: el SDK la lee sola de TYPESAFE_API_KEY.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import threading
import time
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from editor.config import RAIZ
from editor.modelos import RespuestaJEV
from editor.preguntas import EspecPreguntas, a_objetos_sdk

# JEV_CACHE permite apuntar a otra caché (p. ej. una por modelo) sin tocar el código.
RUTA_CACHE_DEFECTO = Path(os.getenv("JEV_CACHE", RAIZ / "cache" / "jev_respuestas.json"))
MODOS = ("live", "record", "replay")


class FaltaEnCacheError(RuntimeError):
    """En modo replay, la combinación pieza+preguntas+modelo no está grabada."""


def clave_cache(state: Any, preguntas: EspecPreguntas, modelo: str) -> str:
    """sha256 estable: json con claves ordenadas y sin espacios."""
    payload = (
        json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + json.dumps(preguntas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + modelo
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalizar_respuestas(respuestas: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Asegura que las probabilidades de los Scores tengan claves int (JSON las guarda como str)."""
    salida = {}
    for qid, r in respuestas.items():
        r = dict(r)
        if r.get("type") == "score" and "probabilities" in r:
            r["probabilities"] = {int(k): float(v) for k, v in r["probabilities"].items()}
        salida[qid] = r
    return salida


def _respuesta_sdk_a_dict(answer: Any) -> dict[str, Any]:
    """Convierte un NoulAnswer/ScoreAnswer/ChoiceAnswer (pydantic) en dict serializable."""
    datos = answer.model_dump(mode="json")
    datos.pop("legend", None)  # el legend repite los criterios: no hace falta guardarlo
    return datos


class ClienteJEV:
    """Cliente de JEV con caché y concurrencia limitada.

    Uso típico:
        cliente = ClienteJEV(modelo="jev-1.13.0")            # modo desde JEV_MODE
        [resp] = await cliente.consultar_lote([(state, preguntas)])
    """

    def __init__(
        self,
        modelo: str,
        modo: str | None = None,
        ruta_cache: Path = RUTA_CACHE_DEFECTO,
        concurrencia: int = 8,
    ) -> None:
        self.modelo = modelo
        self.modo = (modo or os.getenv("JEV_MODE") or "replay").lower()
        if self.modo not in MODOS:
            raise ValueError(f"JEV_MODE inválido: {self.modo!r}. Usa uno de {MODOS}.")
        self.ruta_cache = ruta_cache
        self.concurrencia = concurrencia
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = self._leer_cache()

    # ----------------------------------------------------------------- caché

    def _leer_cache(self) -> dict[str, Any]:
        if self.ruta_cache.exists():
            return json.loads(self.ruta_cache.read_text(encoding="utf-8"))
        return {}

    def _guardar_cache(self) -> None:
        """Escritura atómica: primero a un archivo temporal y luego se renombra."""
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta_cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.ruta_cache)

    def esta_en_cache(self, state: Any, preguntas: EspecPreguntas) -> bool:
        return clave_cache(state, preguntas, self.modelo) in self._cache

    # ----------------------------------------------------------------- API

    @contextlib.asynccontextmanager
    async def _sesion(self) -> AsyncIterator[Any]:
        """Abre un AsyncTypeSafeClient solo si hace falta red (en replay no se crea: no hay key)."""
        if self.modo == "replay":
            yield None
            return
        from typesafe_sdk import AsyncTypeSafeClient

        async with AsyncTypeSafeClient(model=self.modelo) as cliente:
            yield cliente

    async def _llamar_api(
        self, cliente: Any, state: Any, preguntas: EspecPreguntas
    ) -> RespuestaJEV:
        inicio = time.perf_counter()
        resp = await cliente.system_one(state=state, questions=a_objetos_sdk(preguntas))
        latencia_ms = (time.perf_counter() - inicio) * 1000
        return RespuestaJEV(
            respuestas=normalizar_respuestas(
                {qid: _respuesta_sdk_a_dict(a) for qid, a in resp.answers.items()}
            ),
            modelo=resp.model,
            input_tokens=resp.usage.input_tokens or 0,
            latencia_ms=latencia_ms,
        )

    async def _consultar_uno(
        self, cliente: Any, sem: asyncio.Semaphore, state: Any, preguntas: EspecPreguntas
    ) -> RespuestaJEV:
        clave = clave_cache(state, preguntas, self.modelo)

        if self.modo in ("replay", "record") and clave in self._cache:
            g = self._cache[clave]
            return RespuestaJEV(
                respuestas=normalizar_respuestas(g["respuestas"]),
                modelo=g["modelo"],
                input_tokens=g["input_tokens"],
                latencia_ms=g["latencia_ms"],
                desde_cache=True,
            )
        if self.modo == "replay":
            raise FaltaEnCacheError(
                f"No hay respuesta grabada para esta pieza/preguntas/modelo (clave {clave[:12]}…).\n"
                "Causas típicas: es una pieza nueva, editaste reglas.yaml o cambiaste de modelo/idioma.\n"
                "Solución: exporta TYPESAFE_API_KEY y corre con JEV_MODE=record (p. ej. `make record`)."
            )

        async with sem:
            r = await self._llamar_api(cliente, state, preguntas)

        if self.modo == "record":
            with self._lock:
                self._cache[clave] = {
                    "modelo": r.modelo,
                    "input_tokens": r.input_tokens,
                    "latencia_ms": round(r.latencia_ms, 1),
                    "respuestas": r.respuestas,
                    "grabado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                self._guardar_cache()
        return r

    async def consultar_lote(
        self, items: Sequence[tuple[Any, EspecPreguntas]]
    ) -> list[RespuestaJEV]:
        """Evalúa varios (state, preguntas) en paralelo, con a lo sumo `concurrencia` en vuelo.

        El SDK ya reintenta los 429 (rate limit) con backoff.
        """
        sem = asyncio.Semaphore(self.concurrencia)
        async with self._sesion() as cliente:
            return list(
                await asyncio.gather(*(self._consultar_uno(cliente, sem, s, p) for s, p in items))
            )
