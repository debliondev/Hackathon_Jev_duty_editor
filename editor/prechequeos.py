"""CAPA 0 · Prechequeos deterministas (antes de llamar a JEV).

Principio: todo lo calculable va en código. JEV es débil contando, comparando fechas y números,
así que longitud, hashtags, links, precios, fechas y palabras vetadas se resuelven aquí.

Cada chequeo devuelve un ResultadoChequeo {codigo, ok, detalle, efecto}. Además se arma un
`contexto` (programas detectados, precio detectado, ...) que viaja a JEV en `state.prechequeos`.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from editor.config import Configuracion
from editor.modelos import Pieza, ResultadoChequeo, ResultadoPrechequeos

# --------------------------------------------------------------------------- utilidades de texto


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar frases sin depender de acentos."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.lower()


RE_HASHTAG = re.compile(r"(?<![\w&])#\w+")
RE_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
# Esquemas rotos tipo "htps://", "http:/algo" o "hxxp://".
RE_URL_ROTA = re.compile(
    r"\b(?!https?://)[a-z]{3,6}:/{1,2}[^\s]+|\bhttps?:/(?!/)[^\s]+", re.IGNORECASE
)
RE_HOST_VALIDO = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
RE_PRECIO = re.compile(
    r"(?:US\$|USD|MXN|COP|€|\$)\s?\d[\d.,]*"
    r"|\d[\d.,]*\s?(?:USD|US\$|d[oó]lares|pesos|MXN|COP|euros)\b",
    re.IGNORECASE,
)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9,
    "set": 9, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip
_MES = "(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b\.?"
# "26-28 de octubre", "26 al 28 de oct", "26 y 28 oct"
RE_RANGO_FECHA = re.compile(r"\b(\d{1,2})\s*(?:-|–|al|a|y)\s*(\d{1,2})\s+(?:de\s+)?" + _MES)
# "26 de octubre"
RE_FECHA_SIMPLE = re.compile(r"\b(\d{1,2})\s+de\s+" + _MES)


def _numero(texto: str) -> float | None:
    """Convierte '2.500' o '1,299.00' o '497' en número (aproximado; suficiente para comparar)."""
    digitos = re.sub(r"[^\d.,]", "", texto)
    if not digitos:
        return None
    # Si el último separador está a 3 dígitos del final, es separador de miles.
    limpio = re.sub(r"[.,](?=\d{3}\b)", "", digitos).replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


# --------------------------------------------------------------------------- chequeos


def chequear_longitud(pieza: Pieza, limites: dict[str, Any]) -> tuple[bool, str]:
    n = len(pieza.texto)
    ok = limites["largo_min"] <= n <= limites["largo_max"]
    return ok, f"{n} caracteres (rango {limites['largo_min']}-{limites['largo_max']})"


def chequear_hashtags(pieza: Pieza, limites: dict[str, Any]) -> tuple[bool, str]:
    n_hash = len(RE_HASHTAG.findall(pieza.texto))
    n_emoji = len(RE_EMOJI.findall(pieza.texto))
    ok = n_hash <= limites["hashtags_max"] and n_emoji <= limites["emojis_max"]
    return ok, (
        f"{n_hash} hashtags (máx {limites['hashtags_max']}), "
        f"{n_emoji} emojis (máx {limites['emojis_max']})"
    )


def _dominio_permitido(host: str, permitidos: list[str]) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in permitidos)


def chequear_links(pieza: Pieza, permitidos: list[str]) -> tuple[bool, str, list[str]]:
    problemas: list[str] = []
    urls = [u.rstrip(".,;:!?)") for u in RE_URL.findall(pieza.texto)]
    for rota in RE_URL_ROTA.findall(pieza.texto):
        problemas.append(f"URL malformada: {rota}")
    for url in urls:
        parseada = urlparse(url if "://" in url else "https://" + url)
        host = (parseada.hostname or "").lower()
        if not RE_HOST_VALIDO.match(host):
            problemas.append(f"URL malformada: {url}")
        elif not _dominio_permitido(host, permitidos):
            problemas.append(f"dominio no permitido: {host}")
    return not problemas, "; ".join(problemas) or f"{len(urls)} links OK", urls


def chequear_precio(pieza: Pieza, catalogo: dict[str, Any]) -> tuple[bool, str, list[str]]:
    encontrados = [m.group(0).strip() for m in RE_PRECIO.finditer(pieza.texto)]
    precios_validos = {p["precio"] for p in catalogo["programas"] if p.get("precio") is not None}
    invalidos = [e for e in encontrados if _numero(e) not in precios_validos]
    if invalidos:
        return False, f"precio(s) no publicados en el catálogo: {', '.join(invalidos)}", encontrados
    return (
        True,
        "sin precios" if not encontrados else "precios coinciden con el catálogo",
        encontrados,
    )


def _ediciones(catalogo: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for p in catalogo["programas"] for e in p.get("ediciones", [])]


def _dias_de_edicion(edicion: dict[str, Any]) -> set[tuple[int, int, int]]:
    """{(dia_inicio, dia_fin, mes)} de una edición, a partir de fechas ISO."""
    salida = set()
    for f in edicion["fechas"]:
        _, mes, d_ini = (int(x) for x in f["inicio"].split("-"))
        d_fin = int(f["fin"].split("-")[2])
        salida.add((d_ini, d_fin, mes))
    return salida


def chequear_fecha(
    pieza: Pieza, catalogo: dict[str, Any], ciudades_conocidas: list[str]
) -> tuple[bool, str, list[str]]:
    """Fechas y ciudades de la Inmersión deben coincidir con el catálogo. Se compara en código."""
    texto_n = normalizar(pieza.texto)
    if "inmersion" not in texto_n:
        return True, "no menciona la Inmersión", []

    ediciones = _ediciones(catalogo)
    nombres_edicion = {
        normalizar(n): e for e in ediciones for n in [e["ciudad"], *e.get("alias_ciudad", [])]
    }
    mencionadas = [
        e for n, e in nombres_edicion.items() if re.search(rf"\b{re.escape(n)}\b", texto_n)
    ]
    sin_edicion = [
        c for c in ciudades_conocidas
        if re.search(rf"\b{re.escape(normalizar(c))}\b", texto_n) and normalizar(c) not in nombres_edicion
    ]  # fmt: skip

    fechas: list[tuple[int, int, int]] = [
        (int(a), int(b), MESES[m]) for a, b, m in RE_RANGO_FECHA.findall(texto_n)
    ]
    texto_sin_rangos = RE_RANGO_FECHA.sub(" ", texto_n)
    fechas += [(int(a), int(a), MESES[m]) for a, m in RE_FECHA_SIMPLE.findall(texto_sin_rangos)]

    validas = set().union(*(_dias_de_edicion(e) for e in (mencionadas or ediciones)))
    problemas = [f"ciudad sin edición: {c}" for c in sin_edicion]
    for d_ini, d_fin, mes in fechas:
        # Un rango debe coincidir exacto; una fecha suelta debe caer dentro de alguna edición.
        coincide = any(
            v_mes == mes
            and ((d_ini, d_fin) == (v_ini, v_fin) or (d_ini == d_fin and v_ini <= d_ini <= v_fin))
            for v_ini, v_fin, v_mes in validas
        )
        if not coincide:
            problemas.append(f"fecha {d_ini}-{d_fin}/{mes} no coincide con ninguna edición")
    detectadas = [f"{a}-{b}/{m}" for a, b, m in fechas]
    return not problemas, "; ".join(problemas) or "fechas/ciudades OK", detectadas


def _nombres_catalogo(catalogo: dict[str, Any]) -> dict[str, str]:
    """{nombre_normalizado: nombre_oficial} incluyendo alias de programas y activos gratuitos."""
    nombres: dict[str, str] = {}
    for p in catalogo["programas"]:
        for n in [p["programa"], *p.get("alias", [])]:
            nombres[normalizar(n)] = p["programa"]
    for a in catalogo.get("activos_gratuitos", []):
        for n in [a["nombre"], *a.get("alias", [])]:
            nombres[normalizar(n)] = a["nombre"]
    return nombres


def detectar_programas(
    pieza: Pieza, catalogo: dict[str, Any], umbral: float
) -> tuple[list[str], list[str]]:
    """Devuelve (programas exactos detectados, nombres sospechosos parecidos a un programa).

    Sospechoso = ventana de palabras que se parece mucho (difflib ≥ umbral) a un programa del
    catálogo sin ser igual: p. ej. "Sales Machina" o "Growth Rockstars".
    """
    texto_n = normalizar(pieza.texto)
    nombres = _nombres_catalogo(catalogo)
    detectados = sorted(
        {
            oficial
            for n, oficial in nombres.items()
            if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", texto_n)
        }
    )

    palabras = re.findall(r"[\w&]+", texto_n)
    # El fuzzy solo se compara contra programas pagos (los activos gratuitos tienen nombres genéricos
    # como "clases gratis en vivo" que generan falsos positivos).
    nombres_programa = {
        normalizar(n) for p in catalogo["programas"] for n in [p["programa"], *p.get("alias", [])]
    }
    sospechosos: set[str] = set()
    for n in nombres_programa:
        partes = n.split()
        if len(partes) < 2:  # nombres de una palabra dan demasiados falsos positivos
            continue
        k = len(partes)
        for i in range(len(palabras) - k + 1):
            ventana = " ".join(palabras[i : i + k])
            if ventana in nombres:
                continue
            if SequenceMatcher(None, ventana, n).ratio() >= umbral:
                sospechosos.add(ventana)
    return detectados, sorted(sospechosos)


def chequear_vetadas(pieza: Pieza, vetadas: list[str]) -> tuple[bool, str]:
    texto_n = normalizar(pieza.texto)
    halladas = [v for v in vetadas if normalizar(v) in texto_n]
    return not halladas, (
        ("frases vetadas: " + ", ".join(halladas)) if halladas else "sin frases vetadas"
    )


def chequear_menores(pieza: Pieza, patrones: list[str]) -> tuple[bool, str]:
    texto_n = normalizar(pieza.texto)
    halladas = [m.group(0) for p in patrones if (m := re.search(p, texto_n))]
    return not halladas, (
        ("referencias a menores: " + ", ".join(halladas))
        if halladas
        else "sin referencias a menores"
    )


# --------------------------------------------------------------------------- orquestador


def correr_prechequeos(pieza: Pieza, config: Configuracion) -> ResultadoPrechequeos:
    """Corre todos los chequeos de la capa 0 sobre una pieza."""
    cfg = config.reglas["prechequeos"]
    efectos = cfg["efectos"]
    limites = config.policy["canales"][pieza.canal_destino]
    catalogo = config.catalogo

    ok_largo, det_largo = chequear_longitud(pieza, limites)
    ok_hash, det_hash = chequear_hashtags(pieza, limites)
    ok_link, det_link, urls = chequear_links(pieza, cfg["dominios_permitidos"])
    ok_precio, det_precio, precios = chequear_precio(pieza, catalogo)
    ok_fecha, det_fecha, fechas = chequear_fecha(pieza, catalogo, cfg["ciudades_conocidas"])
    detectados, sospechosos = detectar_programas(pieza, catalogo, cfg["umbral_fuzzy_programa"])
    ok_vet, det_vet = chequear_vetadas(pieza, cfg["frases_vetadas"])
    ok_men, det_men = chequear_menores(pieza, cfg["patrones_menores"])

    resultados = [
        ("P0_LONGITUD", ok_largo, det_largo),
        ("P0_HASHTAGS", ok_hash, det_hash),
        ("P0_LINK", ok_link, det_link),
        ("P0_PRECIO", ok_precio, det_precio),
        ("P0_FECHA", ok_fecha, det_fecha),
        ("P0_PROGRAMA", not sospechosos, ("parecidos a un programa: " + ", ".join(sospechosos)) if sospechosos else "OK"),
        ("P0_VETADA", ok_vet, det_vet),
        ("P0_MENOR", ok_men, det_men),
    ]  # fmt: skip
    chequeos = [ResultadoChequeo(c, ok, det, efectos[c]) for c, ok, det in resultados]
    contexto = {
        "programas_detectados": detectados,
        "nombres_sospechosos": sospechosos,
        "precio_detectado": precios[0] if precios else None,
        "fechas_detectadas": fechas,
        "links": urls,
    }
    return ResultadoPrechequeos(chequeos=chequeos, contexto=contexto)
