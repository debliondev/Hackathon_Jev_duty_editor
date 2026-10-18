"""Pipeline completo en modo replay con una caché temporal (sin red y sin API key)."""

from __future__ import annotations

import json

import pytest

from editor.almacen import Almacen
from editor.jev_client import ClienteJEV, FaltaEnCacheError, clave_cache
from editor.modelos import Pieza
from editor.pipeline import Editor
from tests.conftest import respuestas_falsas

TEXTO = (
    "Tu pipeline no está vacío: está lleno de deals que nadie se atreve a cerrar.\n\n"
    "Un pipeline sano se limpia cada semana. Saca todo deal sin próximo paso, llama a los cinco más "
    "grandes y mueve a perdido lo que no responda en dos días. Cuando lo hicimos con un equipo chico, "
    "el forecast por fin se pareció a la realidad.\n\nMira Sales Machine en https://30x.com/programas"
)


@pytest.fixture
def pieza():
    return Pieza(id="T-1", canal_destino="linkedin", formato="post", texto=TEXTO)


def grabar(editor: Editor, pieza: Pieza, respuestas: dict, ruta) -> None:
    """Escribe en la caché temporal la respuesta 'grabada' para esta pieza."""
    _, state = editor.preparar(pieza)
    clave = clave_cache(state, editor.preguntas, editor.config.modelo)
    ruta.write_text(json.dumps({clave: {
        "modelo": "jev-1.13.0", "input_tokens": 430, "latencia_ms": 111.0,
        "respuestas": json.loads(json.dumps(respuestas)),  # simula el viaje por JSON (claves str)
    }}))  # fmt: skip


def editor_replay(config, ruta) -> Editor:
    return Editor(
        config=config, cliente=ClienteJEV(modelo=config.modelo, modo="replay", ruta_cache=ruta)
    )


def test_replay_aprueba_y_calcula_costo(config, pieza, tmp_path):
    ruta = tmp_path / "cache.json"
    grabar(editor_replay(config, ruta), pieza, respuestas_falsas(), ruta)
    d = editor_replay(config, ruta).evaluar_pieza(pieza)
    assert d.veredicto == "aprobar"
    assert d.modelo == "jev-1.13.0"
    assert d.input_tokens == 430
    assert d.costo_usd == pytest.approx(430 * 0.042 / 1e6)
    assert d.version_reglas == config.version_reglas
    # Las probabilidades de Scores vuelven a tener claves int tras pasar por JSON.
    assert all(isinstance(k, int) for k in d.respuestas_crudas["gancho"]["probabilities"])


def test_replay_sin_cache_falla_con_mensaje_claro(config, pieza, tmp_path):
    with pytest.raises(FaltaEnCacheError, match="JEV_MODE=record"):
        editor_replay(config, tmp_path / "vacia.json").evaluar_pieza(pieza)


def test_capa0_descarta_sin_tocar_la_cache(config, tmp_path):
    corta = Pieza(id="T-2", canal_destino="linkedin", formato="post", texto="Muy corto.")
    d = editor_replay(config, tmp_path / "vacia.json").evaluar_pieza(corta)
    assert d.veredicto == "descartar"
    assert d.input_tokens == 0 and d.modelo is None


def test_editar_una_regla_invalida_la_cache(config, pieza, tmp_path):
    e = editor_replay(config, tmp_path / "c.json")
    _, state = e.preparar(pieza)
    preguntas = dict(e.preguntas)
    k1 = clave_cache(state, preguntas, "jev-1.13.0")
    preguntas["gancho"] = {**preguntas["gancho"], "instructions": "otro texto"}
    assert clave_cache(state, preguntas, "jev-1.13.0") != k1
    assert clave_cache(state, e.preguntas, "jev-1.14.0") != k1


def test_redecidir_sin_llamar_a_jev(config, pieza, tmp_path):
    ruta = tmp_path / "cache.json"
    scores = {
        d: 2.0 for d in ["gancho", "claridad", "valor_accionable", "voz_30x", "cta"]
    }  # calidad 0.667
    grabar(editor_replay(config, ruta), pieza, respuestas_falsas(scores=scores), ruta)
    e = editor_replay(config, ruta)
    d = e.evaluar_pieza(pieza)
    assert d.veredicto == "aprobar"  # calidad_min 0.65 en post_organico
    estricta = e.redecidir(d, {"calidad_min": 0.80})
    assert estricta.veredicto == "revisar"
    assert d.veredicto == "aprobar"  # la original no cambia


def test_almacen_cola_y_feedback(config, pieza, tmp_path):
    ruta = tmp_path / "cache.json"
    grabar(
        editor_replay(config, ruta), pieza, respuestas_falsas(nouls={"cifra_sin_fuente": 0.5}), ruta
    )
    d = editor_replay(config, ruta).evaluar_pieza(pieza)
    alm = Almacen(":memory:")
    alm.guardar(pieza, d)
    assert [c["pieza_id"] for c in alm.cola()] == ["T-1"]
    alm.resolver("T-1", "aprobar", "la cifra es ilustrativa")
    assert alm.cola() == []
    assert alm.metricas()["resueltas_por_humano"] == 1
