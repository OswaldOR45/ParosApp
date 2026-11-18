"""
VISTA 5 — DASHBOARD DE MANTENIMIENTO

Responde 4 preguntas, una por pestaña:
  Resumen       ¿Cuánto tiempo estuvo parada la línea por fallas y cuánto de eso
                fue reparación vs. espera?
  Componentes   ¿Qué piezas intervenimos más y qué hicimos con ellas?
  Empresas      ¿Cómo va RSI vs STEO? (solo ADMIN)
  Revisar       ¿Qué falta cerrar y qué paros tienen tiempos raros?

Definiciones (a nivel EVENTO, sin contar dos veces un paro AMBOS):
  Paro        = duración total que reportó producción (todos sus tramos).
  Reparación  = horas en que al menos una empresa estuvo interviniendo
                (unión de los horarios INI_INT–FIN_INT de sus cierres).
  Espera      = Paro − Reparación: línea parada sin nadie reparando
                (traslado del técnico, refacción, diagnóstico, arranque…).
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.sheets import leer_paros, leer_acrs
from utils.auth import requiere_empresa
from utils.filtros import COLOR_EMPRESA, LINEAS, filtrar_fechas, filtrar_linea, selector_periodo
from utils.mtto import (COLOR_ESPERA, COLOR_REPARACION, COLOR_TIPO, eventos, fmt_h,
                        horas_intervencion, pendientes, separar_componentes)
from utils.tiempo import hhmm_a_horas

EMPRESA = requiere_empresa("Dashboard de Mantenimiento")
st.title("Dashboard de Mantenimiento")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos.")
    st.stop()
ev = eventos(df)
acrs = leer_acrs()
if acrs.empty or "id_paro" not in acrs.columns:
    st.info("Aún no hay paros cerrados por mantenimiento.")
    st.stop()

acrs = acrs.copy()
acrs["id_paro"] = acrs["id_paro"].astype(str).str.strip()
acrs["empresa"] = acrs.get("empresa", "").astype(str).str.strip().str.upper()
acrs["h_int"] = acrs.get("dur_int", "").apply(hhmm_a_horas)

# --- Filtros (una sola fila) -----------------------------------------------
fa, fb = st.columns([3, 2])
with fa:
    ini, fin, etiqueta = selector_periodo(ev["fecha"], key="mdash", default="Este mes")
with fb:
    linea = st.segmented_control("Línea", ["Todas"] + LINEAS, default="Todas",
                                 key="mdash_linea") or "Todas"
if EMPRESA == "ADMIN":
    emp_sel = st.segmented_control("Empresa", ["Todas", "RSI", "STEO"],
                                   default="Todas", key="mdash_emp") or "Todas"
else:
    emp_sel = EMPRESA
st.caption(f"{etiqueta} · {linea if linea != 'Todas' else 'ambas líneas'} · "
           f"{'RSI y STEO' if emp_sel == 'Todas' else emp_sel}")

ev_f = filtrar_linea(filtrar_fechas(ev, "fecha", ini, fin), linea)
acr_f = acrs if emp_sel == "Todas" else acrs[acrs["empresa"] == emp_sel]

# --- Eventos cerrados: un renglón por paro ---------------------------------
interv = pd.Series({pid: horas_intervencion(g) for pid, g in acr_f.groupby("id_paro")},
                   name="h_rep", dtype=float)
emp_por_paro = acr_f.groupby("id_paro")["empresa"].agg(lambda s: " y ".join(sorted(set(s))))
cer = ev_f[ev_f["id_paro"].isin(interv.index)].copy()
cer["h_rep"] = cer["id_paro"].map(interv)
cer["empresas"] = cer["id_paro"].map(emp_por_paro)
cer["h_espera"] = (cer["h_paro"] - cer["h_rep"]).clip(lower=0)

# Lo pendiente es pendiente sin importar el periodo elegido: solo se filtra por línea.
pend = pendientes(filtrar_linea(ev, linea), acrs, emp_sel if emp_sel != "Todas" else "ADMIN")

# --- KPIs ------------------------------------------------------------------
t_paro, t_rep, t_esp = cer["h_paro"].sum(), cer["h_rep"].sum(), cer["h_espera"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Paros cerrados", len(cer))
k2.metric("Pendientes (todo el histórico)", len(pend),
          f"{int((pend['dias'] > 3).sum())} con más de 3 días" if len(pend) else None,
          delta_color="inverse" if len(pend) and (pend["dias"] > 3).any() else "off")
k3.metric("Reparación promedio", f"{fmt_h(cer['h_rep'].mean())} h" if len(cer) else "—",
          help="Tiempo medio de intervención por paro (MTTR de mantenimiento).")
k4.metric("Espera sin reparar", f"{t_esp / t_paro:.0%}" if t_paro else "—",
          f"{t_esp:.0f} h de {t_paro:.0f} h de paro" if t_paro else None, delta_color="off",
          help="Parte del paro en que nadie estaba reparando.")

if cer.empty and pend.empty:
    st.info("No hay paros de mantenimiento en este periodo.")
    st.stop()

tabs = ["Resumen", "Componentes"] + (["Empresas"] if emp_sel == "Todas" else []) + ["Revisar"]
tab = dict(zip(tabs, st.tabs(tabs)))


def _barras_apiladas(cats, rep, esp, horizontal=True, titulo=None):
    fig = go.Figure()
    for nombre, vals, color in (("Reparación", rep, COLOR_REPARACION),
                                ("Espera", esp, COLOR_ESPERA)):
        kw = dict(x=vals, y=cats, orientation="h") if horizontal else dict(x=cats, y=vals)
        fig.add_bar(name=nombre, marker_color=color,
                    hovertemplate=f"<b>%{{{'y' if horizontal else 'x'}}}</b><br>{nombre}: "
                                  f"%{{{'x' if horizontal else 'y'}:.1f}} h<extra></extra>", **kw)
    fig.update_layout(barmode="stack", title=titulo, bargap=0.3,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                                  traceorder="normal"),
                      margin=dict(t=70, l=10, r=10))
    fig.update_traces(marker_line_color="white", marker_line_width=1.5)
    return fig


# --- 1. Resumen --------------------------------------------------------------
with tab["Resumen"]:
    if cer.empty:
        st.info("Sin paros cerrados en el periodo.")
    else:
        g = (cer.assign(equipo=cer["equipo"].replace("", "Sin dato"))
             .groupby("equipo")[["h_rep", "h_espera"]].sum())
        g = g.assign(tot=g.sum(axis=1)).sort_values("tot")
        fig = _barras_apiladas(g.index.tolist(), g["h_rep"], g["h_espera"],
                               titulo="Horas de paro por equipo")
        fig.update_layout(height=120 + 40 * len(g), xaxis_title="Horas")
        st.plotly_chart(fig, width="stretch", key="mdash_eq")
        st.caption("Barra completa = lo que la línea estuvo parada. Azul = alguien "
                   "reparando. Amarillo = espera (técnico, refacción, arranque…).")

        sem = cer.dropna(subset=["fecha"]).copy()
        if sem["fecha"].dt.to_period("W").nunique() > 1:
            sem["semana"] = sem["fecha"].dt.to_period("W").dt.start_time
            w = sem.groupby("semana")[["h_rep", "h_espera"]].sum()
            fig2 = _barras_apiladas([f"{d:%d/%m}" for d in w.index], w["h_rep"], w["h_espera"],
                                    horizontal=False, titulo="Por semana (inicio de semana)")
            fig2.update_layout(yaxis_title="Horas", height=330)
            st.plotly_chart(fig2, width="stretch", key="mdash_sem")

# --- 2. Componentes -----------------------------------------------------------
with tab["Componentes"]:
    filas = []
    for r in acr_f[acr_f["id_paro"].isin(cer["id_paro"])].itertuples():
        for comp, tipo in separar_componentes(getattr(r, "componente", ""),
                                              getattr(r, "tipo_intervencion", "")):
            filas.append({"id_paro": r.id_paro, "componente": comp or "(sin pieza)",
                          "tipo": tipo, "h_int": r.h_int})
    comp = pd.DataFrame(filas)
    if comp.empty:
        st.info("Sin componentes registrados en el periodo.")
    else:
        con_pieza = comp[comp["componente"] != "(sin pieza)"]
        top = con_pieza["componente"].value_counts().head(10).index.tolist()[::-1]
        if top:
            fig = go.Figure()
            for tipo, color in COLOR_TIPO.items():
                n = (con_pieza[con_pieza["tipo"] == tipo]["componente"]
                     .value_counts().reindex(top).fillna(0))
                if n.sum():
                    fig.add_bar(y=top, x=n.values, name=tipo, orientation="h",
                                marker_color=color,
                                hovertemplate=f"<b>%{{y}}</b><br>{tipo}: %{{x:.0f}}<extra></extra>")
            fig.update_layout(barmode="stack", title="Piezas más intervenidas (top 10)",
                              xaxis_title="Intervenciones", height=140 + 36 * len(top),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                                          traceorder="normal"),
                              margin=dict(t=70, l=10, r=10), bargap=0.3)
            fig.update_layout(showlegend=True)   # aun con 1 tipo, la leyenda dice qué es
            fig.update_xaxes(tickformat=",d", dtick=1 if len(con_pieza) < 60 else None)
            fig.update_traces(marker_line_color="white", marker_line_width=1.5)
            st.plotly_chart(fig, width="stretch", key="mdash_comp")

        res = (comp.groupby("componente")
               .agg(veces=("id_paro", "nunique"),
                    tipos=("tipo", lambda s: ", ".join(f"{t} ×{n}" for t, n in s.value_counts().items())),
                    rep_media=("h_int", "mean"))
               .sort_values("veces", ascending=False).reset_index())
        res["rep_media"] = res["rep_media"].apply(fmt_h)
        st.dataframe(res, hide_index=True, width="stretch",
                     column_config={"componente": "Componente", "veces": "Paros",
                                    "tipos": "Qué se hizo", "rep_media": "Reparación media (h)"})
        n_rev = (comp["tipo"] == "Revisión / Diagnóstico").sum()
        if n_rev:
            st.caption(f"{n_rev} de {len(comp)} intervenciones fueron solo revisión / "
                       "diagnóstico. Si se repiten en la misma pieza, conviene un "
                       "análisis de causa raíz.")

# --- 3. Empresas (solo cuando se ven ambas) -----------------------------------
if "Empresas" in tab:
    with tab["Empresas"]:
        cols = st.columns(2)
        for col, emp in zip(cols, ("RSI", "STEO")):
            a = acrs[(acrs["empresa"] == emp) & acrs["id_paro"].isin(cer["id_paro"])]
            p_emp = pendientes(filtrar_linea(ev, linea), acrs, emp)
            with col.container(border=True):
                st.markdown(f"<span style='color:{COLOR_EMPRESA[emp]};font-size:1.3rem'>■</span> "
                            f"**{emp}**", unsafe_allow_html=True)
                st.metric("Paros cerrados", a["id_paro"].nunique())
                st.metric("Reparación promedio", f"{fmt_h(a['h_int'].mean())} h" if len(a) else "—")
                st.metric("Pendientes", len(p_emp),
                          f"más antiguo: {p_emp['dias'].max()} días" if len(p_emp) else None,
                          delta_color="off")
        st.caption("Un paro AMBOS cuenta para las dos empresas.")

# --- 4. Revisar ---------------------------------------------------------------
with tab["Revisar"]:
    st.markdown("**Pendientes de cerrar** (de cualquier fecha)")
    if pend.empty:
        st.success("Nada pendiente.")
    else:
        t = pend.assign(fecha_txt=pend["fecha"].dt.strftime("%d/%m"),
                        dur=pend["h_paro"].apply(fmt_h),
                        faltan_txt=pend["faltan"].str.join(" y "))
        st.dataframe(t[["dias", "fecha_txt", "linea", "equipo", "motivo", "dur", "faltan_txt", "id_paro"]],
                     hide_index=True, width="stretch",
                     column_config={"dias": "Días", "fecha_txt": "Fecha", "linea": "Línea",
                                    "equipo": "Equipo", "motivo": "Motivo", "dur": "Paro (h)",
                                    "faltan_txt": "Falta", "id_paro": "ID"})

    if not cer.empty:
        st.markdown("**Mayores esperas**")
        st.caption("Paros donde la línea estuvo más tiempo parada sin que nadie "
                   "reparara. Buenos candidatos para preguntar qué pasó.")
        top = cer.sort_values("h_espera", ascending=False).head(10)
        st.dataframe(
            top.assign(fecha_txt=top["fecha"].dt.strftime("%d/%m"),
                       paro=top["h_paro"].apply(fmt_h), rep=top["h_rep"].apply(fmt_h),
                       esp=top["h_espera"].apply(fmt_h))
               [["fecha_txt", "linea", "equipo", "motivo", "empresas", "paro", "rep", "esp", "id_paro"]],
            hide_index=True, width="stretch",
            column_config={"fecha_txt": "Fecha", "linea": "Línea", "equipo": "Equipo",
                           "motivo": "Motivo", "empresas": "Atendió", "paro": "Paro (h)",
                           "rep": "Reparación (h)", "esp": "Espera (h)", "id_paro": "ID"})

        raros = cer[cer["h_rep"] > cer["h_paro"] + 1 / 60]
        if len(raros):
            st.markdown("**Tiempos que no cuadran**")
            st.caption("La intervención dura más que el paro reportado por "
                       "producción. Suele ser un error de captura de alguna de las dos partes.")
            st.dataframe(
                raros.assign(paro=raros["h_paro"].apply(fmt_h), rep=raros["h_rep"].apply(fmt_h))
                     [["id_paro", "equipo", "empresas", "paro", "rep"]],
                hide_index=True, width="stretch",
                column_config={"id_paro": "ID", "equipo": "Equipo", "empresas": "Atendió",
                               "paro": "Paro (h)", "rep": "Reparación (h)"})
