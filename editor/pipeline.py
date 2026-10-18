"""Orquestación: Pieza → capa 0 → (una llamada a JEV) → decidir → Decision.

Funciones principales:
    editor = Editor()                                   # lee config/ y JEV_MODE
    decision = editor.evaluar_pieza(pieza)              # una pieza (síncrono)
    decisiones = editor.evaluar_lote(piezas)            # lote con concurrencia limitada
    nueva = editor.redecidir(decision, overrides)       # otros umbrales SIN volver a llamar a JEV
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from editor.config import Configuracion, cargar_configuracion
from editor.decidir import decidir
from editor.jev_client import ClienteJEV
from editor.modelos import Decision, Pieza, RespuestaJEV, ResultadoPrechequeos
from editor.prechequeos import correr_prechequeos
from editor.preguntas import EspecPreguntas, construir_preguntas, meta_preguntas


def construir_state(
    pieza: Pieza, pre: ResultadoPrechequeos, config: Configuracion
) -> dict[str, Any]:
    """Arma el `state` que ve JEV. Regla: solo lo necesario (el ruido baja la precisión).

    - `catalogo`: lista compacta {programa, linea} de TODOS los programas (JEV necesita saber qué existe
      para responder `oferta_inexistente`), y el detalle (ediciones, precio) solo de los detectados.
    - `prechequeos`: lo que la capa 0 ya extrajo (programas detectados, nombres sospechosos, precio).
    - `guia_relevante`: 3-4 líneas de la guía de voz, según el canal.
    """
    detectados = set(pre.contexto["programas_detectados"])
    catalogo: list[dict[str, Any]] = []
    for p in config.catalogo["programas"]:
        entrada: dict[str, Any] = {"programa": p["programa"], "linea": p["linea"]}
        if p["programa"] in detectados:
            entrada["precio"] = p.get("precio")
            if p.get("ediciones"):
                entrada["ediciones"] = [
                    {"ciudad": e["ciudad"], "fechas": e["fechas"]} for e in p["ediciones"]
                ]
        catalogo.append(entrada)
    catalogo += [
        {"recurso_gratuito": a["nombre"], "plataforma": a["plataforma"]}
        for a in config.catalogo["activos_gratuitos"]
    ]
    guia = config.reglas["guia_relevante"]
    return {
        "pieza": {
            "canal_destino": pieza.canal_destino,
            "formato": pieza.formato,
            "texto": pieza.texto,
        },
        "catalogo": catalogo,
        "prechequeos": {
            "programas_detectados": pre.contexto["programas_detectados"],
            "nombres_sospechosos": pre.contexto["nombres_sospechosos"],
            "precio_detectado": pre.contexto["precio_detectado"],
        },
        "guia_relevante": guia["general"] + guia.get(pieza.canal_destino, []),
    }


class Editor:
    """Punto de entrada del editor de guardia."""

    def __init__(
        self,
        config: Configuracion | None = None,
        cliente: ClienteJEV | None = None,
        idioma: str | None = None,
        rotacion_choices: int = 0,
    ) -> None:
        self.config = config or cargar_configuracion()
        self.cliente = cliente or ClienteJEV(
            modelo=self.config.modelo, concurrencia=self.config.policy.get("concurrencia", 8)
        )
        self.meta = meta_preguntas(self.config)
        self.preguntas: EspecPreguntas = construir_preguntas(self.config, idioma, rotacion_choices)

    # ----------------------------------------------------------------- piezas

    def preparar(self, pieza: Pieza) -> tuple[ResultadoPrechequeos, dict[str, Any] | None]:
        """Corre la capa 0. Devuelve el state para JEV, o None si la capa 0 ya descarta."""
        pre = correr_prechequeos(pieza, self.config)
        if pre.fallas("descartar"):
            return pre, None
        return pre, construir_state(pieza, pre, self.config)

    def _armar_decision(
        self, pieza: Pieza, pre: ResultadoPrechequeos, resp: RespuestaJEV | None
    ) -> Decision:
        res = decidir(
            prechequeos=pre,
            respuestas=resp.respuestas if resp else None,
            umbrales=self.config.politica_de_canal(pieza.canal_destino),
            pesos_calidad=self.config.policy["pesos_calidad"],
            meta=self.meta,
            canal_destino=pieza.canal_destino,
            canal_conf_min=self.config.policy["canal_conf_min"],
        )
        tokens = resp.input_tokens if resp else 0
        return Decision(
            pieza_id=pieza.id,
            canal_destino=pieza.canal_destino,
            veredicto=res.veredicto,
            motivos=res.motivos,
            calidad=res.calidad,
            respuestas_crudas=resp.respuestas if resp else {},
            prechequeos={
                "chequeos": [c.__dict__ for c in pre.chequeos],
                "contexto": pre.contexto,
            },
            alertas=res.alertas,
            modelo=resp.modelo if resp else None,
            version_reglas=self.config.version_reglas,
            version_policy=self.config.version_policy,
            input_tokens=tokens,
            costo_usd=tokens * self.config.policy["precio_usd_por_millon"] / 1_000_000,
            latencia_ms=round(resp.latencia_ms, 1) if resp else 0.0,
        )

    async def evaluar_lote_async(
        self,
        piezas: Sequence[Pieza],
        al_progresar: Callable[[int, int], None] | None = None,
    ) -> list[Decision]:
        """Evalúa un lote. Solo las piezas que pasan la capa 0 consumen una llamada a JEV."""
        preparadas = [(p, *self.preparar(p)) for p in piezas]
        a_consultar = [(p, pre, st) for p, pre, st in preparadas if st is not None]
        respuestas = await self.cliente.consultar_lote(
            [(st, self.preguntas) for _, _, st in a_consultar]
        )
        por_id = {p.id: r for (p, _, _), r in zip(a_consultar, respuestas, strict=True)}
        decisiones = []
        for i, (p, pre, _) in enumerate(preparadas, start=1):
            decisiones.append(self._armar_decision(p, pre, por_id.get(p.id)))
            if al_progresar:
                al_progresar(i, len(preparadas))
        return decisiones

    async def evaluar_pieza_async(self, pieza: Pieza) -> Decision:
        return (await self.evaluar_lote_async([pieza]))[0]

    def evaluar_lote(self, piezas: Sequence[Pieza]) -> list[Decision]:
        return asyncio.run(self.evaluar_lote_async(piezas))

    def evaluar_pieza(self, pieza: Pieza) -> Decision:
        return self.evaluar_lote([pieza])[0]

    def piezas_sin_cache(self, piezas: Sequence[Pieza]) -> list[str]:
        """IDs de piezas que necesitarían llamar a JEV y no están grabadas (útil antes de un replay)."""
        faltan = []
        for p in piezas:
            _, st = self.preparar(p)
            if st is not None and not self.cliente.esta_en_cache(st, self.preguntas):
                faltan.append(p.id)
        return faltan

    # ----------------------------------------------------------------- re-decidir

    def redecidir(self, decision: Decision, overrides: dict[str, float] | None = None) -> Decision:
        """Recalcula el veredicto con otros umbrales usando las respuestas crudas guardadas.

        No llama a JEV: es lo que permite el barrido de umbrales y el slider de la UI.
        """
        config = self.config.con_overrides(overrides) if overrides else self.config
        pre = ResultadoPrechequeos.desde_dict(decision.prechequeos)
        res = decidir(
            prechequeos=pre,
            respuestas=decision.respuestas_crudas or None,
            umbrales=config.politica_de_canal(decision.canal_destino),
            pesos_calidad=config.policy["pesos_calidad"],
            meta=self.meta,
            canal_destino=decision.canal_destino,
            canal_conf_min=config.policy["canal_conf_min"],
        )
        nueva = Decision.desde_dict(decision.a_dict())
        nueva.veredicto, nueva.motivos, nueva.calidad, nueva.alertas = (
            res.veredicto, res.motivos, res.calidad, res.alertas,
        )  # fmt: skip
        nueva.version_policy = config.version_policy
        return nueva
