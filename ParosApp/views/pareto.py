"""
VISTA — PARETO DE PAROS NO PROGRAMADOS.
  1. Pareto general por ÁREA.
  2. Sub-Pareto por MOTIVO del área seleccionada.
  3. Detalle: descripciones de los paros, agrupadas por motivo (de mayor a
     menor en horas), para ver QUÉ pasó en cada motivo.

Filtros: periodo (incluye rango) y línea (una, todas o COMPARAR ambas).
Solo cuenta paros NO PROGRAMADOS: la clasificación se toma del catálogo
(tipo_por_motivo); los motivos sin clasificar se tratan como NO PROGRAMADO y
se avisa cuántos son.
"""
import re
import unicodedata

import pandas as pd
import streamlit as st

from config import settings
from data.sheets import leer_paros, cargar_catalogos
from utils.tiempo import hhmm_a_horas
from utils.filtros import (selector_periodo, filtrar_fechas, filtrar_linea,
                           expandir_por_linea, marcar_hijos, id_evento,
                           texto_limpio, pareto_fig, vitales_80,
                           barras_comparadas, COLOR_LINEA, LINEA_AMBAS, LINEAS)


def _norm(texto) -> str:
    """Ignora acentos, mayúsculas y espacios para empatar motivos."""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def eventos(d: pd.DataFrame) -> pd.DataFrame:
    """Une los tramos de un paro multi-turno en UNA fila (horas sumadas),
    para que la tabla de descripciones no repita el mismo paro por turno."""
    if d.empty:
        return d
    d = d.sort_values("fecha").copy()
    d["evento"] = id_evento(d)

    def _primera(x):
        x = x.astype(str).str.strip()
        x = x[(x != "") & (x.str.lower() != "nan")]
        return x.iloc[0] if not x.empty else ""

    return (d.groupby("evento", sort=False)
             .agg(fecha=("fecha", "first"), area=("area", "first"),
                  motivo=("motivo", "first"), linea=("linea", "first"),
                  grupo=("turno", "first"), equipo=("equipo", "first"),
                  descripcion=("descripcion", _primera),
                  tramos=("horas", "size"), horas=("horas", "sum"))
             .reset_index())


def tabla_descripciones(d: pd.DataFrame, titulo_area: str, key: str):
    """Un desplegable por motivo (mayor → menor en horas) con sus paros."""
    ev = eventos(d)
    if ev.empty:
        st.info("Sin paros para detallar.")
        return
    tot = ev.groupby("motivo")["horas"].agg(["sum", "size"]).sort_values("sum", ascending=False)
    total_h = tot["sum"].sum()

    resumen = tot.reset_index().rename(columns={"motivo": "Motivo", "sum": "Horas",
                                                "size": "Paros"})
    resumen["% del área"] = (resumen["Horas"] / total_h * 100).round(1)
    resumen["Horas"] = resumen["Horas"].round(2)
    st.dataframe(resumen, width="stretch", hide_index=True,
                 column_config={"% del área": st.column_config.ProgressColumn(
                     "% del área", min_value=0, max_value=100, format="%.1f%%")})

    for motivo, fila in tot.iterrows():
        sub = ev[ev["motivo"] == motivo].sort_values("horas", ascending=False)
        with st.expander(f"**{motivo}** · {fila['sum']:.1f} h · "
                         f"{int(fila['size'])} paro(s) · "
                         f"{fila['sum'] / total_h * 100:.0f}%"):
            vista = pd.DataFrame({
                "Fecha": sub["fecha"].dt.strftime("%d/%m/%Y %H:%M"),
                "Línea": sub["linea"], "Grupo": sub["grupo"],
                "Equipo": sub["equipo"], "Horas": sub["horas"].round(2),
                "Descripción": sub["descripcion"].replace("", "— sin descripción —"),
            })
            if (sub["tramos"] > 1).any():
                vista["Turnos"] = sub["tramos"].values
            st.dataframe(vista, width="stretch", hide_index=True,
                         column_config={"Descripción": st.column_config.TextColumn(
                             width="large")})

    csv = ev.sort_values(["motivo", "horas"], ascending=[True, False]).to_csv(index=False)
    st.download_button("⬇️ Descargar detalle (CSV)", csv.encode("utf-8-sig"),
                       file_name=f"detalle_motivos_{titulo_area}.csv",
                       mime="text/csv", key=f"{key}_csv")


# ===========================================================================
st.title("Pareto de paros no programados")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

df = df.copy()
df["es_hijo"] = marcar_hijos(df)
df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")
df["h_prog"] = df.get("dur_prog", "").apply(hhmm_a_horas)
df["h_noprog"] = df.get("dur_noprog", "").apply(hhmm_a_horas)
df["horas"] = df["h_prog"] + df["h_noprog"]

tipo_por_motivo = cargar_catalogos().get("tipo_por_motivo", {})
tipo_norm = {_norm(k): v for k, v in tipo_por_motivo.items()}
df["motivo"] = texto_limpio(df, "motivo", "Sin motivo")
df["tipo"] = df["motivo"].map(lambda m: tipo_norm.get(_norm(m), settings.NO_PROGRAMADO))
sin_clasificar = sorted({m for m in df["motivo"].unique()
                         if m and _norm(m) not in tipo_norm})

df["area"] = texto_limpio(df, "area", "Sin área")
df["linea"] = texto_limpio(df, "linea", "Sin línea")
df["turno"] = texto_limpio(df, "turno")
df["equipo"] = texto_limpio(df, "equipo", "Sin equipo")
df["descripcion"] = texto_limpio(df, "descripcion")

# --- Filtros ---------------------------------------------------------------
ini, fin, etiqueta = selector_periodo(df["fecha"], key="par")
vista_linea = st.segmented_control("Línea", ["Todas", "Línea 1", "Línea 2", "Comparar"],
                                   default="Todas", key="par_linea") or "Todas"
comparar = vista_linea == "Comparar"

df = filtrar_fechas(df, "fecha", ini, fin)
if vista_linea in LINEAS:
    df = filtrar_linea(df, vista_linea)

df = df[(df["tipo"] == settings.NO_PROGRAMADO) & (df["horas"] > 0)]

st.caption(f"Mostrando **{etiqueta}**"
           + (f" · **{vista_linea}** (incluye «{LINEA_AMBAS}»)" if vista_linea in LINEAS else "")
           + (f" · los paros de «{LINEA_AMBAS}» cuentan en las dos líneas" if comparar else ""))

if df.empty:
    st.warning("No hay paros no programados con duración en el periodo / línea.")
    st.stop()

if sin_clasificar:
    st.info(f"⚠️ {len(sin_clasificar)} motivo(s) no están en el catálogo y se "
            f"contaron como **no programados**: {', '.join(sin_clasificar)}.")

dfc = expandir_por_linea(df) if comparar else None

# --- KPIs ------------------------------------------------------------------
por_area = df.groupby("area")["horas"].sum()
if comparar:
    cols = st.columns(2)
    for col, ln in zip(cols, LINEAS):
        d = dfc[dfc["linea_cmp"] == ln]
        with col:
            st.markdown(f"**{ln}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Paros", int((~d["es_hijo"]).sum()))
            m2.metric("Horas", f"{d['horas'].sum():.1f} h")
            m3.metric("Áreas 80%", len(vitales_80(d.groupby("area")["horas"].sum())))
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Paros no programados", int((~df["es_hijo"]).sum()))
    c2.metric("Horas perdidas", f"{df['horas'].sum():.1f} h")
    c3.metric("Áreas que causan el 80%", len(vitales_80(por_area)))

st.divider()

# --- 1. Pareto general por ÁREA --------------------------------------------
st.subheader("Pareto general — por área")
if comparar:
    st.plotly_chart(barras_comparadas(
        dfc, "area", "linea_cmp", {k: COLOR_LINEA[k] for k in LINEAS},
        "Horas no programadas por área — Línea 1 vs Línea 2", "Área"), width="stretch")
    cols = st.columns(2)
    for col, ln in zip(cols, LINEAS):
        s = dfc[dfc["linea_cmp"] == ln].groupby("area")["horas"].sum()
        with col:
            fig = pareto_fig(s, "Área", color=COLOR_LINEA[ln], titulo=ln)
            if fig is None:
                st.info(f"{ln}: sin paros no programados.")
            else:
                st.plotly_chart(fig, width="stretch", key=f"par_area_{ln}")
                st.caption("**Pocos vitales:** " + ", ".join(map(str, vitales_80(s))))
else:
    st.plotly_chart(pareto_fig(por_area, "Área"), width="stretch")
    st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, vitales_80(por_area))))

st.divider()

# --- 2. Sub-Pareto por MOTIVO del área elegida -----------------------------
st.subheader("Sub-Pareto — motivos de un área")
areas_orden = por_area.sort_values(ascending=False).index.tolist()
area_sel = st.selectbox("Área a analizar", areas_orden, index=0, key="par_area_sel",
                        help="Por defecto, el área con más horas perdidas.")
df_area = df[df["area"] == area_sel]

if comparar:
    dfc_area = dfc[dfc["area"] == area_sel]
    cols = st.columns(2)
    for col, ln in zip(cols, LINEAS):
        s = dfc_area[dfc_area["linea_cmp"] == ln].groupby("motivo")["horas"].sum()
        with col:
            fig = pareto_fig(s, "Motivo", color=COLOR_LINEA[ln], titulo=f"{area_sel} · {ln}")
            if fig is None:
                st.info(f"{ln}: sin paros en {area_sel}.")
            else:
                st.plotly_chart(fig, width="stretch", key=f"par_mot_{ln}")
                st.caption("**Pocos vitales:** " + ", ".join(map(str, vitales_80(s))))
else:
    por_motivo = df_area.groupby("motivo")["horas"].sum()
    fig_motivo = pareto_fig(por_motivo, "Motivo")
    if fig_motivo is None:
        st.warning("Esta área no tiene horas no programadas en el periodo.")
    else:
        st.plotly_chart(fig_motivo, width="stretch")
        st.caption(f"En **{area_sel}**, el 80% de las horas lo causan: "
                   + ", ".join(map(str, vitales_80(por_motivo))))

st.divider()

# --- 3. Detalle: descripciones por motivo ----------------------------------
st.subheader(f"Detalle de motivos — {area_sel}")
st.caption("Motivos de mayor a menor en horas. Abre cada uno para leer las "
           "descripciones de sus paros (los paros multi-turno se muestran como "
           "un solo evento con sus horas sumadas).")
if comparar:
    ln_det = st.segmented_control("Línea del detalle", ["Ambas"] + LINEAS,
                                  default="Ambas", key="par_det_linea") or "Ambas"
    df_det = filtrar_linea(df_area, ln_det) if ln_det in LINEAS else df_area
else:
    df_det = df_area
tabla_descripciones(df_det, area_sel, key="par_det")