"""Tests de la capa 0 (prechequeos deterministas)."""

from __future__ import annotations

import pytest

from editor.modelos import Pieza
from editor.prechequeos import correr_prechequeos

BASE = (
    "Tu pipeline no está vacío: está lleno de deals que nadie se atreve a cerrar.\n\n"
    "Un pipeline sano se limpia cada semana. Saca todo deal sin próximo paso, llama a los cinco más "
    "grandes y mueve a perdido lo que no responda en dos días. Cuando lo hicimos con un equipo chico, "
    "el forecast por fin se pareció a la realidad.\n\nMira Sales Machine en https://30x.com/programas"
)


def pieza(texto: str, canal: str = "linkedin") -> Pieza:
    return Pieza(id="T-1", canal_destino=canal, formato="post", texto=texto)


def fallas(config, texto: str, canal: str = "linkedin") -> set[str]:
    return {c.codigo for c in correr_prechequeos(pieza(texto, canal), config).fallas()}


def test_pieza_limpia_pasa_todo(config):
    assert fallas(config, BASE) == set()


def test_detecta_programa_exacto(config):
    pre = correr_prechequeos(pieza(BASE), config)
    assert pre.contexto["programas_detectados"] == ["Sales Machine"]


def test_longitud(config):
    assert "P0_LONGITUD" in fallas(config, "Aprende ventas. Link en bio.")


def test_hashtags(config):
    assert "P0_HASHTAGS" in fallas(config, BASE + "\n" + " ".join(f"#tag{i}" for i in range(6)))


@pytest.mark.parametrize(
    "url",
    ["https://bit.ly/oferta", "https://30x-programas.com/x", "htps://30x.com", "http:/30x.com"],
)
def test_links_invalidos(config, url):
    assert "P0_LINK" in fallas(config, BASE + f" {url}")


@pytest.mark.parametrize(
    "url", ["https://30x.com/programas", "https://www.30x.com", "https://lu.ma/30x"]
)
def test_links_validos(config, url):
    assert "P0_LINK" not in fallas(config, BASE + f" {url}")


@pytest.mark.parametrize(
    "txt", ["por solo US$497", "cuesta 2.500 USD", "a $1,299", "solo 300 dólares"]
)
def test_precio_no_publicado(config, txt):
    assert "P0_PRECIO" in fallas(config, BASE + f" {txt}.")


def test_porcentaje_no_es_precio(config):
    assert "P0_PRECIO" not in fallas(config, BASE + " El 40% de los equipos.")


def test_fecha_correcta_de_edicion(config):
    assert "P0_FECHA" not in fallas(
        config, BASE + " Inmersión Ejecutiva Bogotá, del 26 al 28 de octubre."
    )


def test_fecha_incorrecta(config):
    assert "P0_FECHA" in fallas(
        config, BASE + " Inmersión Ejecutiva Bogotá, del 10 al 12 de diciembre."
    )


def test_ciudad_sin_edicion(config):
    assert "P0_FECHA" in fallas(config, BASE + " Nos vemos en la Inmersión Ejecutiva de Lima.")


def test_medellin_no_tiene_edicion_vigente(config):
    assert "P0_FECHA" in fallas(config, BASE + " Inmersión Ejecutiva en Medellín.")


def test_fechas_sin_inmersion_se_ignoran(config):
    assert "P0_FECHA" not in fallas(config, BASE + " La clase es el 3 de diciembre.")


def test_programa_parecido(config):
    pre = correr_prechequeos(pieza(BASE.replace("Sales Machine", "Sales Machina")), config)
    assert "P0_PROGRAMA" in {c.codigo for c in pre.fallas()}
    assert pre.contexto["nombres_sospechosos"] == ["sales machina"]


def test_frase_vetada_sin_tildes(config):
    assert "P0_VETADA" in fallas(config, BASE + " Gana DINERO FACIL.")


@pytest.mark.parametrize(
    "txt", ["Ideal para tus hijos.", "Conoce IA para Jóvenes.", "Para chicos de 15 años."]
)
def test_menores(config, txt):
    assert "P0_MENOR" in fallas(config, BASE + " " + txt)


def test_efectos_vienen_de_config(config):
    pre = correr_prechequeos(pieza("corto"), config)
    largo = next(c for c in pre.chequeos if c.codigo == "P0_LONGITUD")
    assert largo.efecto == config.reglas["prechequeos"]["efectos"]["P0_LONGITUD"]
