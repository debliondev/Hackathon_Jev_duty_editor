"""Barrido de umbrales sobre el split DEV, SIN volver a llamar a JEV.

    python -m eval.barrido_umbrales            # usa eval/resultados/decisiones_dev_<idioma>.jsonl

Reusa las respuestas crudas guardadas por correr_eval y re-ejecuta el motor de decisión (puro) con
cada combinación de umbrales. Genera:
  - eval/resultados/curva_precision_automatizacion.png  (para el playbook)
  - eval/resultados/barrido.csv
  - eval/resultados/umbrales_propuestos.yaml  (NO toca policy.yaml: un humano decide si aplicarlos)

Simplificación: aplica los mismos umbrales a todas las políticas de canal.
"""

from __future__ import annotations

import argparse
import csv
import itertools

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402

from editor.metricas import calcular_metricas, cargar_etiquetas  # noqa: E402
from editor.pipeline import Editor  # noqa: E402
from eval.comun import DIR_RESULTADOS, RUTA_ETIQUETAS, cargar_decisiones  # noqa: E402

GRILLA = {
    "noul_accion": [0.5, 0.6, 0.7, 0.8, 0.9],
    "noul_revision": [0.15, 0.25, 0.35, 0.45],
    "calidad_min": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85],
    "conf_min": [0.4, 0.5, 0.6, 0.7, 0.8],
}


def barrer(editor: Editor, decisiones, etiquetas) -> list[dict]:  # noqa: ANN001
    filas = []
    for na, nr, cm, cf in itertools.product(*GRILLA.values()):
        if nr >= na:
            continue
        ov = {"noul_accion": na, "noul_revision": nr, "calidad_min": cm, "conf_min": cf}
        nuevas = [editor.redecidir(d, ov) for d in decisiones]
        m = calcular_metricas(nuevas, etiquetas)
        filas.append({**ov, "precision_aprobar": m["precision_aprobar"], "recall_reglas_duras": m["recall_reglas_duras"],
                      "automatizacion": m["automatizacion"], "adversarial_aprobadas": m["adversarial_aprobadas"],
                      "n_aprobadas": m["n_aprobadas"]})  # fmt: skip
    return filas


def proponer(filas: list[dict], metas: dict) -> dict | None:
    """Máxima automatización sujeta a las metas de precisión, recall y adversarial."""
    validas = [
        f for f in filas
        if (f["precision_aprobar"] or 0) >= metas["precision_aprobar"]
        and (f["recall_reglas_duras"] or 0) >= metas["recall_reglas_duras"]
        and (f["adversarial_aprobadas"] or 0) <= metas["adversarial_aprobadas"]
    ]  # fmt: skip
    return (
        max(validas, key=lambda f: (f["automatizacion"], f["precision_aprobar"]))
        if validas
        else None
    )


def graficar(filas: list[dict], propuesta: dict | None, actual: dict, metas: dict) -> None:
    x = [f["automatizacion"] for f in filas]
    y = [f["precision_aprobar"] if f["precision_aprobar"] is not None else 0 for f in filas]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(x, y, s=10, alpha=0.35, color="#7a8ca5", label="combinaciones de umbrales")
    # Frontera de Pareto: mejor precisión alcanzable para cada nivel de automatización.
    frontera, mejor = [], -1.0
    for f in sorted(filas, key=lambda f: -f["automatizacion"]):
        p = f["precision_aprobar"] or 0
        if p > mejor:
            frontera.append((f["automatizacion"], p))
            mejor = p
    if frontera:
        fx, fy = zip(*sorted(frontera), strict=True)
        ax.plot(fx, fy, color="#1f4e79", lw=2, label="frontera")
    ax.axhline(
        metas["precision_aprobar"],
        color="#c0392b",
        ls="--",
        lw=1,
        label=f"meta {metas['precision_aprobar']:.0%}",
    )
    ax.scatter([actual["automatizacion"]], [actual["precision_aprobar"] or 0], marker="s", s=70,
               color="#e67e22", label="policy.yaml actual", zorder=5)  # fmt: skip
    if propuesta:
        ax.scatter([propuesta["automatizacion"]], [propuesta["precision_aprobar"]], marker="*", s=200,
                   color="#27ae60", label="propuesta", zorder=6)  # fmt: skip
    ax.set_xlabel("Tasa de automatización (aprobado + descartado sin humano)")
    ax.set_ylabel("Precisión de APROBAR")
    ax.set_title("Precisión vs. automatización (split dev)")
    ax.set_ylim(min(0.5, min(y) - 0.05), 1.01)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(DIR_RESULTADOS / "curva_precision_automatizacion.png", dpi=150)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idioma", choices=["en", "es"], default=None)
    args = ap.parse_args()
    editor = Editor()
    idioma = args.idioma or editor.config.policy["idioma_preguntas"]
    decisiones = cargar_decisiones(f"dev_{idioma}")
    etiquetas = cargar_etiquetas(RUTA_ETIQUETAS)
    metas = editor.config.policy["metas"]

    filas = barrer(editor, decisiones, etiquetas)
    with (DIR_RESULTADOS / "barrido.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    actual = calcular_metricas([editor.redecidir(d) for d in decisiones], etiquetas)
    propuesta = proponer(filas, metas)
    graficar(filas, propuesta, actual, metas)

    print(f"{len(filas)} combinaciones evaluadas sobre {len(decisiones)} piezas de dev.")
    print(
        f"Actual (policy.yaml): precisión {actual['precision_aprobar']}, automatización {actual['automatizacion']:.1%}"
    )
    if propuesta:
        print(f"Propuesta: {propuesta}")
        (DIR_RESULTADOS / "umbrales_propuestos.yaml").write_text(
            yaml.safe_dump(
                {
                    "fuente": f"barrido sobre dev_{idioma}",
                    "aplicar_a_todas_las_politicas": propuesta,
                },
                allow_unicode=True,
            )
        )
    else:
        print(
            "Ninguna combinación cumple todas las metas: revisar redacción de reglas (tarea 2) o las metas."
        )
    print("Gráfico: eval/resultados/curva_precision_automatizacion.png")


if __name__ == "__main__":
    main()
