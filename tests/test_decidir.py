"""Tests del motor de decisión con respuestas JEV falsas (fixtures)."""

from __future__ import annotations

from editor.decidir import decidir
from editor.modelos import ResultadoChequeo, ResultadoPrechequeos
from tests.conftest import respuestas_falsas

UMBRALES = {"noul_accion": 0.70, "noul_revision": 0.30, "calidad_min": 0.65, "calidad_descarte": 0.35, "conf_min": 0.60}  # fmt: skip
PESOS = {"gancho": 0.30, "claridad": 0.20, "valor_accionable": 0.30, "voz_30x": 0.15, "cta": 0.05}


def pre_ok(*fallas: tuple[str, str]) -> ResultadoPrechequeos:
    chequeos = [ResultadoChequeo(c, False, "detalle", e) for c, e in fallas]
    return ResultadoPrechequeos(chequeos=chequeos, contexto={})


def correr(meta, pre=None, resp=None, canal="linkedin"):
    return decidir(pre or pre_ok(), resp, UMBRALES, PESOS, meta, canal, 0.60)


def test_aprueba_pieza_limpia_y_buena(meta):
    r = correr(meta, resp=respuestas_falsas())
    assert r.veredicto == "aprobar"
    assert r.calidad == 1.0
    assert r.motivos == []


def test_capa0_descarta_sin_jev(meta):
    r = correr(meta, pre=pre_ok(("P0_PRECIO", "descartar")), resp=None)
    assert r.veredicto == "descartar"
    assert [m.codigo for m in r.motivos] == ["P0_PRECIO"]
    assert r.calidad is None


def test_regla_descartar_sobre_umbral(meta):
    r = correr(meta, resp=respuestas_falsas(nouls={"promesa_garantizada": 0.9}))
    assert r.veredicto == "descartar"
    assert r.motivos[0].codigo == "promesa_garantizada"


def test_regla_en_franja_de_revision(meta):
    r = correr(meta, resp=respuestas_falsas(nouls={"promesa_garantizada": 0.5}))
    assert r.veredicto == "revisar"
    assert r.motivos[0].efecto == "revisar"


def test_regla_revisar_sobre_umbral_no_descarta(meta):
    r = correr(meta, resp=respuestas_falsas(nouls={"cifra_sin_fuente": 0.95}))
    assert r.veredicto == "revisar"


def test_descartar_tiene_precedencia_sobre_revisar(meta):
    r = correr(
        meta, resp=respuestas_falsas(nouls={"cifra_sin_fuente": 0.95, "ataque_terceros": 0.8})
    )
    assert r.veredicto == "descartar"


def test_inyeccion_dispara_alerta(meta):
    r = correr(meta, resp=respuestas_falsas(nouls={"instruccion_inyectada": 0.97}))
    assert r.veredicto == "descartar"
    assert r.alertas and r.alertas[0].startswith("instruccion_inyectada")


def test_baja_confianza_manda_a_revision(meta):
    r = correr(meta, resp=respuestas_falsas(confianzas={"voz_30x": 0.3}))
    assert r.veredicto == "revisar"
    assert any(m.codigo == "baja_confianza:voz_30x" for m in r.motivos)


def test_calidad_baja_descarta_con_dimension_mas_debil(meta):
    scores = {"gancho": 0.0, "claridad": 1.0, "valor_accionable": 0.5, "voz_30x": 1.0, "cta": 1.0}
    r = correr(meta, resp=respuestas_falsas(scores=scores))
    assert r.veredicto == "descartar"
    assert r.motivos[-1].codigo == "calidad_baja:gancho"


def test_zona_gris_de_calidad(meta):
    scores = {d: 1.5 for d in PESOS}  # 0.5 normalizado: entre 0.35 y 0.65
    r = correr(meta, resp=respuestas_falsas(scores=scores))
    assert r.veredicto == "revisar"
    assert r.motivos[-1].codigo == "calidad_zona_gris"


def test_canal_distinto_con_confianza(meta):
    r = correr(meta, resp=respuestas_falsas(canal=("newsletter", 0.8)))
    assert r.veredicto == "revisar"
    assert r.motivos[0].codigo == "canal_sugerido:newsletter"


def test_canal_distinto_sin_confianza_no_importa(meta):
    r = correr(meta, resp=respuestas_falsas(canal=("newsletter", 0.4)))
    assert r.veredicto == "aprobar"


def test_falla_p0_revisar_manda_a_revision(meta):
    r = correr(meta, pre=pre_ok(("P0_MENOR", "revisar")), resp=respuestas_falsas())
    assert r.veredicto == "revisar"


def test_p0_marcar_cede_ante_descarte_de_jev(meta):
    r = correr(
        meta,
        pre=pre_ok(("P0_PROGRAMA", "marcar")),
        resp=respuestas_falsas(nouls={"oferta_inexistente": 0.9}),
    )
    assert r.veredicto == "descartar"


def test_calidad_ponderada(meta):
    scores = {"gancho": 3.0, "claridad": 3.0, "valor_accionable": 3.0, "voz_30x": 0.0, "cta": 0.0}
    r = correr(meta, resp=respuestas_falsas(scores=scores))
    assert r.calidad == 0.8  # 0.30 + 0.20 + 0.30
