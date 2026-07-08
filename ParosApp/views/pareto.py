"""
VISTA — PARETO DE PAROS NO PROGRAMADOS.
Pareto general de horas perdidas por ÁREA y sub-Pareto por MOTIVO del área
seleccionada. Solo cuenta paros NO PROGRAMADOS: la clasificación se toma del
catálogo (tipo_por_motivo); los motivos sin clasificar se tratan como NO
PROGRAMADO y se avisa cuántos son.

Las horas se calculan con utils.tiempo.hhmm_a_horas (mismo parseo que el
Dashboard) para que los totales cuadren entre pantallas.
"""
import re
import unicodedata

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import settings
from data.sheets import leer_paros, cargar_catalogos
from utils.tiempo import hhmm_a_horas

LINEA_AMBAS = "Línea 1 y 2"
COLOR_BARRA = "#2563EB"
COLOR_LINEA = "#DC2626"
COLOR_80 = "#9CA3AF"


def _norm(texto) -> str:
    """Ignora acentos, mayúsculas y espacios para empatar motivos."""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def pareto_fig(serie_horas: pd.Series, eje_label: str) -> go.Figure | None:
    """Construye un Pareto (barras de horas + línea de % acumulado + corte 80%)."""
    s = serie_horas[serie_horas > 0].sort_values(ascending=False)
    if s.empty:
        return None
    acum = s.cumsum() / s.sum() * 100.0
    cats = [str(c) for c in s.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=cats, y=s.values, name="Horas perdidas",
                marker_color=COLOR_BARRA, secondary_y=False)
    fig.add_scatter(x=cats, y=acum.values, name="% acumulado",
                    mode="lines+markers", line=dict(color=COLOR_LINEA),
                    secondary_y=True)
    fig.add_hline(y=80, line_dash="dash", line_color=COLOR_80,
                  annotation_text="80%", annotation_position="top left",
                  secondary_y=True)
    fig.update_yaxes(title_text="Horas", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", range=[0, 105], secondary_y=True)
    fig.update_layout(
        xaxis_title=eje_label,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        bargap=0.25, margin=dict(t=40, b=10),
    )
    return fig


def vitales_80(serie_horas: pd.Series) -> list:
    """Categorías que acumulan hasta el 80% (los 'pocos vitales')."""
    s = serie_horas[serie_horas > 0].sort_values(ascending=False)
    if s.empty:
        return []
    acum = s.cumsum() / s.sum() * 100.0
    corte = acum[acum <= 80]
    # incluye la categoría que cruza el 80% para no dejar el corte por debajo
    n = len(corte) + (1 if len(corte) < len(s) else 0)
    return list(s.index[:max(n, 1)])


# ===========================================================================
st.title("Pareto de paros no programados")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

# Excluir tramos hijos: el Pareto de gerencia usa solo el padre para no
# contar el mismo evento múltiples veces. Los hijos SÍ se incluyen en el
# Pareto por supervisor (cuando se implemente el filtro por grupo).
if "es_continuacion" in df.columns:
    _ec = df["es_continuacion"].fillna("").str.strip().str.upper()
    df = df[~_ec.isin({"SÍ", "SI"})].copy()

# --- Horas (igual que el Dashboard) y fecha --------------------------------
df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")
df["h_prog"] = df.get("dur_prog", "").apply(hhmm_a_horas)
df["h_noprog"] = df.get("dur_noprog", "").apply(hhmm_a_horas)
df["horas"] = df["h_prog"] + df["h_noprog"]

# --- Clasificación por MOTIVO (catálogo); sin clasificar -> NO PROGRAMADO ---
tipo_por_motivo = cargar_catalogos().get("tipo_por_motivo", {})
tipo_norm = {_norm(k): v for k, v in tipo_por_motivo.items()}
df["motivo"] = df.get("motivo", "").fillna("").astype(str).str.strip()
df["tipo"] = df["motivo"].map(lambda m: tipo_norm.get(_norm(m), settings.NO_PROGRAMADO))

# Motivos presentes en los datos que el catálogo no reconoce
sin_clasificar = sorted({m for m in df["motivo"].unique()
                         if m and _norm(m) not in tipo_norm})

# Normaliza área
df["area"] = df.get("area", "").fillna("").astype(str).str.strip()
df.loc[df["area"] == "", "area"] = "Sin área"
df["linea"] = df.get("linea", "").fillna("").astype(str).str.strip()

# --- Filtros (mismo patrón que el Dashboard) -------------------------------
f1, f2 = st.columns(2)
with f1:
    periodo = st.segmented_control("Periodo", ["Hoy", "Semana", "Este Mes", "Todo"],
                                   default="Este Mes")
with f2:
    vista_linea = st.segmented_control("Línea", ["Todas", "Línea 1", "Línea 2"],
                                       default="Todas")

hoy = pd.Timestamp.today().normalize()
if periodo == "Hoy":
    df = df[df["fecha"] >= hoy]
elif periodo == "Semana":
    df = df[df["fecha"] >= hoy - pd.Timedelta(days=7)]
elif periodo == "Este Mes":
    df = df[df["fecha"] >= hoy.replace(day=1)]

if vista_linea in ("Línea 1", "Línea 2"):
    df = df[df["linea"].isin([vista_linea, LINEA_AMBAS])]
    st.caption(f"Mostrando **{vista_linea}** (incluye «{LINEA_AMBAS}»).")

# --- Solo NO PROGRAMADOS ---------------------------------------------------
df = df[df["tipo"] == settings.NO_PROGRAMADO]
df = df[df["horas"] > 0]

if df.empty:
    st.warning("No hay paros no programados con duración en el periodo / línea.")
    st.stop()

if sin_clasificar:
    st.info(
        f"⚠️ {len(sin_clasificar)} motivo(s) no están en el catálogo y se "
        f"contaron como **no programados**: {', '.join(sin_clasificar)}."
    )

# --- KPIs ------------------------------------------------------------------
por_area = df.groupby("area")["horas"].sum()
areas_vitales = vitales_80(por_area)

c1, c2, c3 = st.columns(3)
c1.metric("Paros no programados", len(df))
c2.metric("Horas perdidas", f"{df['horas'].sum():.1f} h")
c3.metric("Áreas que causan el 80%", len(areas_vitales))

st.divider()

# --- 1. Pareto general por ÁREA --------------------------------------------
st.subheader("Pareto general — por área")
fig_area = pareto_fig(por_area, "Área")
st.plotly_chart(fig_area, width="stretch")
if areas_vitales:
    st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, areas_vitales)))

st.divider()

# --- 2. Sub-Pareto por MOTIVO del área elegida -----------------------------
st.subheader("Sub-Pareto — motivos de un área")
areas_orden = por_area.sort_values(ascending=False).index.tolist()
area_sel = st.selectbox("Área a analizar", areas_orden, index=0,
                        help="Por defecto, el área más problemática.")

df_area = df[df["area"] == area_sel]
por_motivo = df_area.groupby("motivo")["horas"].sum()
fig_motivo = pareto_fig(por_motivo, "Motivo")
if fig_motivo is None:
    st.warning("Esta área no tiene horas no programadas en el periodo.")
else:
    st.plotly_chart(fig_motivo, width="stretch")
    motivos_vitales = vitales_80(por_motivo)
    st.caption(
        f"En **{area_sel}**, el 80% de las horas lo causan: "
        + ", ".join(map(str, motivos_vitales))
    )