"""Estructuras de datos del editor: Pieza, ResultadoChequeo, Motivo, RespuestaJEV y Decision."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Veredicto = Literal["aprobar", "descartar", "revisar"]
Efecto = Literal["descartar", "revisar", "marcar"]
FuenteMotivo = Literal["p0", "regla", "calidad", "canal"]


@dataclass
class Pieza:
    """Una pieza de contenido ya generada que hay que calificar."""

    id: str
    canal_destino: str  # linkedin | instagram_tiktok | newsletter | anuncio_evento
    formato: str  # post | guion_reel | newsletter | copy_evento
    texto: str
    metadatos: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def desde_dict(cls, d: dict[str, Any]) -> Pieza:
        return cls(
            id=d["id"],
            canal_destino=d["canal_destino"],
            formato=d.get("formato", ""),
            texto=d["texto"],
            metadatos=d.get("metadatos", {}),
        )


@dataclass
class ResultadoChequeo:
    """Resultado de un prechequeo de la capa 0."""

    codigo: str  # P0_LONGITUD, P0_LINK, ...
    ok: bool
    detalle: str
    efecto: Efecto  # qué pasa si ok=False


@dataclass
class ResultadoPrechequeos:
    """Todos los chequeos de la capa 0 más el contexto extraído (se envía a JEV)."""

    chequeos: list[ResultadoChequeo]
    contexto: dict[str, Any]

    def fallas(self, efecto: Efecto | None = None) -> list[ResultadoChequeo]:
        return [c for c in self.chequeos if not c.ok and (efecto is None or c.efecto == efecto)]

    @classmethod
    def desde_dict(cls, d: dict[str, Any]) -> ResultadoPrechequeos:
        return cls(chequeos=[ResultadoChequeo(**c) for c in d["chequeos"]], contexto=d["contexto"])


@dataclass
class Motivo:
    """Una razón que explica el veredicto."""

    codigo: str  # p. ej. "promesa_garantizada", "P0_PRECIO", "calidad_baja:gancho"
    fuente: FuenteMotivo
    valor: float | str | None  # p de un Noul, confianza, detalle de la capa 0...
    efecto: Efecto


@dataclass
class RespuestaJEV:
    """Respuesta de JEV normalizada (lo que se guarda en caché y en la decisión)."""

    respuestas: dict[
        str, dict[str, Any]
    ]  # id_pregunta → {type, noul|score|choice, probabilities, confidence}
    modelo: str
    input_tokens: int
    latencia_ms: float
    desde_cache: bool = False


@dataclass
class Decision:
    """Veredicto final y toda la evidencia para auditarlo."""

    pieza_id: str
    canal_destino: str
    veredicto: Veredicto
    motivos: list[Motivo]
    calidad: float | None
    respuestas_crudas: dict[str, dict[str, Any]]
    prechequeos: dict[str, Any]
    alertas: list[str]
    modelo: str | None
    version_reglas: str
    version_policy: str
    input_tokens: int
    costo_usd: float
    latencia_ms: float

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, d: dict[str, Any]) -> Decision:
        d = dict(d)
        d["motivos"] = [Motivo(**m) for m in d["motivos"]]
        return cls(**d)
