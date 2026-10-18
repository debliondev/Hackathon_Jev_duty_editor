"""Guardrails sobre la configuración y el golden set sintético."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from data.synthetic.generar_piezas import generar
from editor.preguntas import a_objetos_sdk, construir_preguntas

RAIZ = Path(__file__).resolve().parent.parent


def test_preguntas_validas_para_el_sdk_en_ambos_idiomas(config):
    for idioma in ("en", "es"):
        espec = construir_preguntas(config, idioma)
        objetos = a_objetos_sdk(espec)  # valida contra los modelos pydantic del SDK
        assert set(objetos) == set(espec)


def test_noul_criteria_tiene_claves_string(config):
    """YAML convierte `true:` sin comillas en booleano: esto lo detecta."""
    for r in config.reglas["nouls"].values():
        for idioma in ("en", "es"):
            assert set(r[idioma]["criteria"]) == {"true", "false"}


def test_scores_tienen_mismo_numero_de_niveles_en_ambos_idiomas(config):
    for r in config.reglas["scores"].values():
        assert len(r["en"]["criteria"]) == len(r["es"]["criteria"])


def test_choices_incluyen_opcion_de_escape(config):
    assert "ninguno" in config.reglas["choices"]["canal_ideal"]["en"]["criteria"]
    assert "marca" in config.reglas["choices"]["linea_programa"]["en"]["criteria"]


def test_pesos_suman_uno(config):
    assert abs(sum(config.policy["pesos_calidad"].values()) - 1) < 1e-9


def test_modelo_fijado(config):
    assert config.modelo != "jev-latest" and config.modelo.startswith("jev-")


def test_catalogo_sin_precios_inventados(config):
    assert all(p["precio"] is None for p in config.catalogo["programas"])


def test_generador_determinista_y_archivos_al_dia():
    piezas, etiquetas = generar()
    en_disco = [
        json.loads(linea) for linea in (RAIZ / "data/synthetic/piezas.jsonl").open(encoding="utf-8")
    ]
    assert (
        piezas == en_disco
    ), "piezas.jsonl desactualizado: corre `python -m data.synthetic.generar_piezas`"
    with (RAIZ / "data/synthetic/etiquetas.csv").open(encoding="utf-8") as f:
        assert [r["pieza_id"] for r in csv.DictReader(f)] == [e["pieza_id"] for e in etiquetas]


def test_golden_set_composicion():
    _, etiquetas = generar()
    n = len(etiquetas)
    assert 200 <= n <= 300
    assert sum(e["defecto_plantado"] == "instruccion_inyectada" for e in etiquetas) >= 15
    assert {e["split"] for e in etiquetas} == {"dev", "test"}
