"""Experimentos de robustez (§6.2 del plan).

    python -m eval.experimentos permutacion   # sesgo por orden de opciones en Choices
    python -m eval.experimentos adversarial   # % de inyectadas que terminan aprobadas (meta 0)
    python -m eval.experimentos idioma        # instrucciones EN vs ES (piezas en ES)

`permutacion` e `idioma` necesitan respuestas grabadas adicionales (otras preguntas ⇒ otras claves de
caché). La primera vez, córrelos con JEV_MODE=record. Resultados en eval/resultados/exp_*.json.
"""

from __future__ import annotations

import argparse
import json

from editor.metricas import calcular_metricas, cargar_etiquetas
from editor.pipeline import Editor
from eval.comun import DIR_RESULTADOS, RUTA_ETIQUETAS, cargar_decisiones, cargar_piezas


def _evaluar(editor: Editor, piezas):  # noqa: ANN001, ANN202
    if editor.cliente.modo == "replay" and (faltan := editor.piezas_sin_cache(piezas)):
        raise SystemExit(
            f"{len(faltan)} piezas sin grabar para este experimento. Corre con JEV_MODE=record."
        )
    return editor.evaluar_lote(piezas)


def permutacion(n_max: int = 60) -> dict:
    """Rota las opciones de los Choices 1 y 2 posiciones y mide cuántas respuestas cambian."""
    piezas = [p for p in cargar_piezas("dev")][:n_max]
    base = {d.pieza_id: d for d in _evaluar(Editor(), piezas) if d.respuestas_crudas}
    salida: dict = {"n_piezas": len(base)}
    for rot in (1, 2):
        rotadas = {
            d.pieza_id: d
            for d in _evaluar(Editor(rotacion_choices=rot), piezas)
            if d.respuestas_crudas
        }
        for qid in ("canal_ideal", "linea_programa"):
            cambios = sum(
                base[pid].respuestas_crudas[qid]["choice"]
                != rotadas[pid].respuestas_crudas[qid]["choice"]
                for pid in base
            )
            salida[f"{qid}_rot{rot}_cambios_pct"] = cambios / len(base) if base else None
    return salida


def adversarial() -> dict:
    """Usa la corrida de dev y de test si existen (no hace llamadas nuevas)."""
    etiquetas = cargar_etiquetas(RUTA_ETIQUETAS)
    salida = {}
    for nombre in ("dev_en", "test_en", "dev_es"):
        try:
            decisiones = cargar_decisiones(nombre)
        except SystemExit:
            continue
        inyectadas = [
            d
            for d in decisiones
            if etiquetas[d.pieza_id]["defecto_plantado"] == "instruccion_inyectada"
        ]
        salida[nombre] = {
            "n": len(inyectadas),
            "aprobadas": sum(d.veredicto == "aprobar" for d in inyectadas),
            "descartadas": sum(d.veredicto == "descartar" for d in inyectadas),
            "con_alerta": sum(bool(d.alertas) for d in inyectadas),
            "p_instruccion_inyectada": {
                d.pieza_id: d.respuestas_crudas.get("instruccion_inyectada", {}).get("noul")
                for d in inyectadas
            },
        }
    return salida


def idioma() -> dict:
    etiquetas = cargar_etiquetas(RUTA_ETIQUETAS)
    piezas = cargar_piezas("dev")
    salida = {}
    for lang in ("en", "es"):
        m = calcular_metricas(_evaluar(Editor(idioma=lang), piezas), etiquetas)
        salida[lang] = {k: m[k] for k in ("precision_aprobar", "recall_reglas_duras", "automatizacion",
                                          "exactitud_veredicto", "adversarial_aprobadas", "tokens_promedio_por_llamada")}  # fmt: skip
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("experimento", choices=["permutacion", "adversarial", "idioma"])
    args = ap.parse_args()
    resultado = {"permutacion": permutacion, "adversarial": adversarial, "idioma": idioma}[
        args.experimento
    ]()
    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (DIR_RESULTADOS / f"exp_{args.experimento}.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False)
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
