"""Regenera eval/reporte.md a partir de lo que haya en eval/resultados/.

python -m eval.reporte
"""

from __future__ import annotations

import json
from datetime import date

from editor.config import RAIZ
from eval.comun import DIR_RESULTADOS


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1%}"


def _num(v: float | None, dec: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{dec}f}"


def main() -> None:
    lineas = [
        "# Reporte del eval: Editor de guardia",
        "",
        f"_Generado automáticamente por `python -m eval.reporte` el {date.today().isoformat()}. No editar a mano._",
        "",
    ]
    metricas = sorted(DIR_RESULTADOS.glob("metricas_*.json"))
    if not metricas:
        lineas += [
            "**Todavía no hay resultados.** Graba y corre el eval (ver README → *Recording real JEV answers*)."
        ]
    else:
        lineas += [
            "## Métricas por corrida",
            "",
            "| Corrida | n | Precisión APROBAR | Recall reglas duras | Adversarial aprobadas | Automatización | "
            "Cola/día | p50 ms | p95 ms | US$/1.000 piezas | Modelo |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for ruta in metricas:
            m = json.loads(ruta.read_text())
            lineas.append(
                f"| {ruta.stem.removeprefix('metricas_')} | {m['n']} | {_pct(m['precision_aprobar'])} | "
                f"{_pct(m['recall_reglas_duras'])} | {_pct(m['adversarial_aprobadas'])} | "
                f"{_pct(m['automatizacion'])} | {m['carga_revision_diaria']} | {_num(m['latencia_p50_ms'])} | "
                f"{_num(m['latencia_p95_ms'])} | {m['costo_por_1000_piezas_usd']:.5f} | {', '.join(m['modelos'])} |"
            )
        lineas += [
            "",
            "Metas: precisión de APROBAR ≥ 95%, recall de reglas duras ≥ 98%, adversariales aprobadas = 0%.",
            "",
        ]
        for ruta in metricas:
            m = json.loads(ruta.read_text())
            c = m["confusion"]
            lineas += [
                f"### Matriz de confusión: {ruta.stem.removeprefix('metricas_')}",
                "",
                "| esperado \\ predicho | aprobar | descartar | revisar |",
                "|---|---|---|---|",
                *[
                    f"| {e} | {c[e]['aprobar']} | {c[e]['descartar']} | {c[e]['revisar']} |"
                    for e in c
                ],
                "",
                f"Motivos más frecuentes: {', '.join(f'`{k}` ({v})' for k, v in list(m['motivos'].items())[:8])}",
                "",
            ]
    if (DIR_RESULTADOS / "curva_precision_automatizacion.png").exists():
        lineas += ["## Curva precisión vs. automatización (dev)", "",
                   "![curva](resultados/curva_precision_automatizacion.png)", ""]  # fmt: skip
    if (p := DIR_RESULTADOS / "umbrales_propuestos.yaml").exists():
        lineas += [
            "## Umbrales propuestos por el barrido",
            "",
            "```yaml",
            p.read_text().strip(),
            "```",
            "",
        ]
    for exp in ("permutacion", "idioma", "adversarial"):
        if (p := DIR_RESULTADOS / f"exp_{exp}.json").exists():
            datos = json.loads(p.read_text())
            if exp == "adversarial":
                datos = {
                    k: {kk: vv for kk, vv in v.items() if kk != "p_instruccion_inyectada"}
                    for k, v in datos.items()
                }
            lineas += [
                f"## Experimento: {exp}",
                "",
                "```json",
                json.dumps(datos, indent=2, ensure_ascii=False),
                "```",
                "",
            ]
    lineas += [
        "## Notas",
        "",
        "- Benchmark publicado por TypeSafe (no es medición propia): ~111 ms y ~US$0.000043 por llamada en su "
        "cookbook de autoconsistencia. Las cifras de arriba sí son mediciones propias.",
        "- La latencia en replay es la medida al grabar (JEV_MODE=record).",
        "- Golden set sintético (236 piezas): resultados indicativos; validar en modo sombra con piezas reales.",
    ]
    (RAIZ / "eval" / "reporte.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("eval/reporte.md regenerado.")


if __name__ == "__main__":
    main()
