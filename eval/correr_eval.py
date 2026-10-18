"""Corre el golden set por el pipeline completo y calcula las métricas de §6.1.

    python -m eval.correr_eval --split dev               # ajustar (umbrales, redacción)
    python -m eval.correr_eval --split test              # SOLO para reportar; nunca ajustar con test
    python -m eval.correr_eval --split dev --idioma es   # ablación de idioma

Modo de JEV: variable JEV_MODE (replay por defecto). Con JEV_MODE=record graba lo que falte.
Salida: eval/resultados/decisiones_<corrida>.jsonl y metricas_<corrida>.json
"""

from __future__ import annotations

import argparse
import json
import time

from editor.metricas import calcular_metricas, cargar_etiquetas
from editor.pipeline import Editor
from eval.comun import (
    DIR_RESULTADOS,
    RUTA_ETIQUETAS,
    cargar_piezas,
    guardar_decisiones,
    nombre_corrida,
)


def fmt(v: object, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    if pct:
        return f"{v:.1%}"  # type: ignore[str-format]
    return (
        f"{v:.6f}"
        if isinstance(v, float) and v < 0.01
        else (f"{v:.2f}" if isinstance(v, float) else str(v))
    )


def imprimir(m: dict, metas: dict) -> None:
    def ok(valor, meta, mayor=True):  # noqa: ANN001
        if valor is None:
            return ""
        return "✅" if (valor >= meta if mayor else valor <= meta) else "❌"

    print(
        f"\nPiezas: {m['n']}  (llamadas a JEV: {m['n_llamadas_jev']}; el resto se resolvió en la capa 0)"
    )
    print(f"Distribución: {m['distribucion']}")
    print(
        f"Precisión de APROBAR : {fmt(m['precision_aprobar'], True)} de {m['n_aprobadas']} "
        f"{ok(m['precision_aprobar'], metas['precision_aprobar'])} (meta ≥ {metas['precision_aprobar']:.0%})"
    )
    print(
        f"Recall reglas duras  : {fmt(m['recall_reglas_duras'], True)} de {m['n_con_violacion']} "
        f"{ok(m['recall_reglas_duras'], metas['recall_reglas_duras'])} (meta ≥ {metas['recall_reglas_duras']:.0%})"
    )
    print(
        f"Adversarial aprobadas: {fmt(m['adversarial_aprobadas'], True)} de {m['n_adversariales']} "
        f"{ok(m['adversarial_aprobadas'], metas['adversarial_aprobadas'], mayor=False)} (meta 0%)"
    )
    print(
        f"Automatización       : {fmt(m['automatizacion'], True)}  → carga de revisión ≈ {m['carga_revision_diaria']} piezas/día"
    )
    print(f"Exactitud (3 clases) : {fmt(m['exactitud_veredicto'], True)}")
    print(f"Latencia p50 / p95   : {fmt(m['latencia_p50_ms'])} / {fmt(m['latencia_p95_ms'])} ms")
    print(
        f"Costo                : US${m['costo_total_usd']:.6f} total · US${m['costo_por_1000_piezas_usd']:.5f} por 1.000 piezas"
    )
    print(f"Modelo(s)            : {m['modelos']}")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument(
        "--idioma", choices=["en", "es"], default=None, help="por defecto, el de policy.yaml"
    )
    ap.add_argument(
        "--rotacion", type=int, default=0, help="rotar opciones de Choices (test de permutación)"
    )
    args = ap.parse_args()

    editor = Editor(idioma=args.idioma, rotacion_choices=args.rotacion)
    idioma = args.idioma or editor.config.policy["idioma_preguntas"]
    piezas = cargar_piezas(args.split)
    print(f"Modo JEV: {editor.cliente.modo} · modelo {editor.config.modelo} · idioma {idioma} · "
          f"split {args.split} ({len(piezas)} piezas)")  # fmt: skip

    if editor.cliente.modo == "replay":
        faltan = editor.piezas_sin_cache(piezas)
        if faltan:
            raise SystemExit(
                f"\n{len(faltan)} de {len(piezas)} piezas no están en la caché para esta configuración.\n"
                "Graba primero (necesita TYPESAFE_API_KEY):\n"
                f"  JEV_MODE=record python -m eval.correr_eval --split {args.split} --idioma {idioma}"
                + (f" --rotacion {args.rotacion}" if args.rotacion else "")
            )

    t0 = time.perf_counter()
    decisiones = editor.evaluar_lote(piezas)
    print(f"Procesado en {time.perf_counter() - t0:.1f} s")

    nombre = nombre_corrida(args.split, idioma, args.rotacion)
    guardar_decisiones(decisiones, nombre)
    metricas = calcular_metricas(
        decisiones,
        cargar_etiquetas(RUTA_ETIQUETAS),
        editor.config.policy["volumen_diario_supuesto"],
    )
    metricas["corrida"] = {"split": args.split, "idioma": idioma, "rotacion": args.rotacion,
                           "modelo": editor.config.modelo, "version_reglas": editor.config.version_reglas,
                           "version_policy": editor.config.version_policy}  # fmt: skip
    (DIR_RESULTADOS / f"metricas_{nombre}.json").write_text(
        json.dumps(metricas, indent=2, ensure_ascii=False)
    )
    imprimir(metricas, editor.config.policy["metas"])
    print(f"\nGuardado en eval/resultados/*_{nombre}.*")


if __name__ == "__main__":
    main()
