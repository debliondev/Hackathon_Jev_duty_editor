"""UI del editor de guardia (Streamlit).   streamlit run ui/app.py

Vistas (§7.3 del plan):
  1. Lote: procesar piezas.jsonl con contadores en vivo, costo y latencia.
  2. Cola del editor: piezas en REVISAR con evidencia legible y botones Aprobar/Descartar.
  3. Política en vivo: slider estricto ↔ permisivo que recalcula SIN volver a llamar a JEV.
  4. Demo adversarial: instrucción inyectada bloqueada, con alerta.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from editor.almacen import Almacen  # noqa: E402
from editor.evidencia import describir_evidencia  # noqa: E402
from editor.jev_client import FaltaEnCacheError  # noqa: E402
from editor.metricas import calcular_metricas, cargar_etiquetas  # noqa: E402
from editor.modelos import Decision, Pieza  # noqa: E402
from editor.pipeline import Editor  # noqa: E402
from eval.comun import RUTA_ETIQUETAS, cargar_piezas  # noqa: E402

st.set_page_config(page_title="Editor de guardia · 30X × JEV", page_icon="🛡️", layout="wide")
COLOR = {"aprobar": "🟢", "descartar": "🔴", "revisar": "🟡"}


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1%}"


@st.cache_resource
def recursos() -> tuple[Editor, Almacen]:
    return Editor(), Almacen()


editor, almacen = recursos()
etiquetas = cargar_etiquetas(RUTA_ETIQUETAS)

# ------------------------------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("🛡️ Editor de guardia")
    st.caption("30X × JEV (TypeSafe System One)")
    st.markdown(
        f"**Modo JEV:** `{editor.cliente.modo}`  \n**Modelo:** `{editor.config.modelo}`  \n"
        f"**Idioma de preguntas:** `{editor.config.policy['idioma_preguntas']}`  \n"
        f"**API key:** {'configurada' if os.getenv('TYPESAFE_API_KEY') else 'no configurada'}  \n"
        f"**reglas.yaml:** `{editor.config.version_reglas}`  \n**policy.yaml:** `{editor.config.version_policy}`"
    )
    st.caption(f"Respuestas en caché: {len(editor.cliente._cache)}")
    if editor.cliente.modo == "replay" and not editor.cliente._cache:
        st.warning("La caché está vacía. Graba primero con `make record` (necesita API key).")

tab_lote, tab_cola, tab_politica, tab_adv = st.tabs(
    ["📦 Lote", "🧑‍⚖️ Cola del editor", "🎚️ Política en vivo", "🧨 Demo adversarial"]
)

# ------------------------------------------------------------------------------------- 1. Lote
with tab_lote:
    st.subheader("Procesar un lote del golden set")
    c1, c2 = st.columns(2)
    split = c1.selectbox("Split", ["dev", "test", "all"], index=2)
    todas = cargar_piezas(split)
    random.Random(0).shuffle(
        todas
    )  # mezcla fija: el lote de demo trae buenas, defectuosas y ambiguas
    n = c2.slider("Número de piezas", 5, len(todas), min(50, len(todas)))
    if st.button("▶️ Procesar lote", type="primary"):
        piezas = todas[:n]
        # st.empty() = un hueco que se reescribe en cada iteración (si no, se apilan métricas nuevas).
        m_apr, m_des, m_rev, m_cost, m_lat = (col.empty() for col in st.columns(5))
        barra = st.progress(0.0)
        decisiones: list[Decision] = []
        try:
            for i in range(0, len(piezas), 10):  # de a 10 para ver los contadores moverse
                bloque = piezas[i : i + 10]
                decisiones += asyncio.run(editor.evaluar_lote_async(bloque))
                for p, d in zip(bloque, decisiones[-len(bloque) :], strict=True):
                    almacen.guardar(p, d)
                cuenta = pd.Series([d.veredicto for d in decisiones]).value_counts()
                lat = sorted(d.latencia_ms for d in decisiones if d.input_tokens)
                m_apr.metric("🟢 Aprobadas", int(cuenta.get("aprobar", 0)))
                m_des.metric("🔴 Descartadas", int(cuenta.get("descartar", 0)))
                m_rev.metric("🟡 En revisión", int(cuenta.get("revisar", 0)))
                m_cost.metric("Costo total", f"US${sum(d.costo_usd for d in decisiones):.6f}")
                if lat:
                    p50, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]
                    m_lat.metric("Latencia p50 / p95", f"{p50:.0f} / {p95:.0f} ms")
                barra.progress(len(decisiones) / len(piezas))
        except FaltaEnCacheError as e:
            st.error(str(e))
        st.session_state["decisiones"] = decisiones
        st.session_state["piezas"] = {p.id: p for p in piezas}

    if decisiones := st.session_state.get("decisiones"):
        filas = [{"pieza": d.pieza_id, "canal": d.canal_destino, "veredicto": f"{COLOR[d.veredicto]} {d.veredicto}",
                  "esperado": etiquetas.get(d.pieza_id, {}).get("veredicto_esperado", "?"),
                  "calidad": d.calidad, "motivos": ", ".join(m.codigo for m in d.motivos),
                  "ms": d.latencia_ms, "tokens": d.input_tokens} for d in decisiones]  # fmt: skip
        st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
        m = calcular_metricas(decisiones, etiquetas)
        st.caption(f"Precisión de APROBAR: {pct(m['precision_aprobar'])} · "
                   f"automatización {pct(m['automatizacion'])} · "
                   f"costo por 1.000 piezas US${m['costo_por_1000_piezas_usd']:.5f}")  # fmt: skip

# ------------------------------------------------------------------------------------- 2. Cola
with tab_cola:
    st.subheader("Cola de revisión")
    cola = almacen.cola()
    st.caption(
        f"{len(cola)} piezas esperando criterio humano. Cada resolución se guarda como etiqueta nueva."
    )
    for item in cola[:30]:
        d: Decision = item["decision"]
        with st.expander(
            f"{item['pieza_id']} · {item['canal']} · {', '.join(m.codigo for m in d.motivos)[:90]}"
        ):
            izq, der = st.columns([3, 2])
            izq.text(item["texto"])
            der.markdown("**Evidencia**")
            for linea in describir_evidencia(d):
                der.markdown(f"- `{linea}`")
            nota = der.text_input("Nota", key=f"nota_{item['pieza_id']}")
            b1, b2 = der.columns(2)
            if b1.button("✅ Aprobar", key=f"a_{item['pieza_id']}"):
                almacen.resolver(item["pieza_id"], "aprobar", nota)
                st.rerun()
            if b2.button("❌ Descartar", key=f"d_{item['pieza_id']}"):
                almacen.resolver(item["pieza_id"], "descartar", nota)
                st.rerun()

# ------------------------------------------------------------------------------------- 3. Política
with tab_politica:
    st.subheader("Política en vivo: estricto ↔ permisivo")
    st.caption(
        "Recalcula las decisiones del último lote con otros umbrales reusando las respuestas crudas: 0 llamadas a JEV."
    )
    decisiones = st.session_state.get("decisiones")
    if not decisiones:
        st.info("Procesa un lote primero (pestaña 📦 Lote).")
    else:
        extremos = editor.config.policy["slider"]

        def interpolar(t: float) -> dict[str, float]:
            return {k: round(extremos["estricto"][k] + t * (extremos["permisivo"][k] - extremos["estricto"][k]), 3)
                    for k in extremos["estricto"]}  # fmt: skip

        t = st.slider("Estricto ⟵ ⟶ Permisivo", 0.0, 1.0, 0.5, 0.05)
        umbrales = interpolar(t)
        st.json(umbrales, expanded=False)
        nuevas = [editor.redecidir(d, umbrales) for d in decisiones]
        m = calcular_metricas(nuevas, etiquetas)
        c1, c2, c3 = st.columns(3)
        c1.metric("Precisión de APROBAR", pct(m["precision_aprobar"]))
        c2.metric("Automatización", f"{m['automatizacion']:.1%}")
        c3.metric("Recall reglas duras", pct(m["recall_reglas_duras"]))

        curva = []
        for tt in [i / 20 for i in range(21)]:
            mm = calcular_metricas(
                [editor.redecidir(d, interpolar(tt)) for d in decisiones], etiquetas
            )
            curva.append({"permisividad": tt, "automatizacion": mm["automatizacion"],
                          "precision_aprobar": mm["precision_aprobar"] or 0})  # fmt: skip
        df = pd.DataFrame(curva).set_index("permisividad")
        st.line_chart(df)
        st.caption(
            f"Posición actual: permisividad = {t}. Meta de precisión: {editor.config.policy['metas']['precision_aprobar']:.0%}."
        )

# ------------------------------------------------------------------------------------- 4. Adversarial
with tab_adv:
    st.subheader("Instrucción inyectada → bloqueada")
    adversariales = [
        p
        for p in cargar_piezas("all")
        if etiquetas[p.id]["defecto_plantado"] == "instruccion_inyectada"
    ]
    opciones = {
        f"{p.id} · {p.canal_destino} · {etiquetas[p.id]['notas']}": p for p in adversariales
    }
    eleccion = st.selectbox("Pieza adversarial del golden set (grabada en caché)", list(opciones))
    texto_libre = st.text_area(
        "…o pega tu propio texto (requiere JEV_MODE=live o record)", height=150
    )
    canal = st.selectbox(
        "Canal destino", ["linkedin", "instagram_tiktok", "newsletter", "anuncio_evento"]
    )
    if st.button("🛡️ Evaluar", type="primary"):
        pieza = (Pieza(id="DEMO-ADV", canal_destino=canal, formato=editor.config.policy["canales"][canal]["formato"],
                       texto=texto_libre) if texto_libre.strip() else opciones[eleccion])  # fmt: skip
        try:
            d = editor.evaluar_pieza(pieza)
        except FaltaEnCacheError as e:
            st.error(str(e))
        else:
            st.text(pieza.texto)
            st.markdown(f"## {COLOR[d.veredicto]} {d.veredicto.upper()}")
            if d.alertas:
                st.error(f"🚨 ALERTA: {', '.join(d.alertas)}")
            for linea in describir_evidencia(d):
                st.markdown(f"- `{linea}`")
