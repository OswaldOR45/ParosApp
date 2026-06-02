"""
VISTA 3 — DASHBOARD (Gerencia). Sin pestaña de Microsoft (Ricardo usa Power Query).
Las duraciones vienen en H:MM y se convierten a horas decimales para graficar.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from config import settings
from data.sheets import leer_paros
from utils.tiempo import hhmm_a_horas

st.title("Dashboard de Paros")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

# --- Mapeo para expandir paros que afectan varias líneas ------------------
EXPANSION_LINEAS = {
    "Línea 1":      ["Línea 1"],
    "Línea 2":      ["Línea 2"],
    "Línea 1 y 2":  ["Línea 1", "Línea 2"],
}

def expandir_por_linea(df: pd.DataFrame) -> pd.DataFrame:
    """Duplica filas que afectan ambas líneas — solo para gráficos POR LÍNEA."""
    df = df.copy()
    df["linea"] = df["linea"].map(EXPANSION_LINEAS).fillna(
        df["linea"].apply(lambda x: [x])
    )
    return df.explode("linea", ignore_index=True)

# --- 1) Construir columnas derivadas --------------------------------------
df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")
df["h_prog"]   = df.get("dur_prog", "").apply(hhmm_a_horas)
df["h_noprog"] = df.get("dur_noprog", "").apply(hhmm_a_horas)
df["horas"]    = df["h_prog"] + df["h_noprog"]
df["tipo"] = df["h_prog"].apply(
    lambda x: settings.PROGRAMADO if x > 0 else settings.NO_PROGRAMADO
)

# --- 2) Filtro de periodo --------------------------------------------------
periodo = st.segmented_control("Periodo", ["Hoy", "Semana", "Mes", "Todo"],
                               default="Semana")
hoy = pd.Timestamp.today().normalize()
if periodo == "Hoy":
    df = df[df["fecha"] >= hoy]
elif periodo == "Semana":
    df = df[df["fecha"] >= hoy - pd.Timedelta(days=7)]
elif periodo == "Mes":
    df = df[df["fecha"] >= hoy - pd.Timedelta(days=30)]

if df.empty:
    st.warning("No hay paros en el periodo seleccionado.")
    st.stop()

# --- 3) KPIs totales de planta (NO duplicados) -----------------------------
c1, c2, c3 = st.columns(3)
c1.metric("Paros", len(df))
c2.metric("Horas perdidas", f"{df['horas'].sum():.1f} h")
c3.metric("Horas NO programadas", f"{df['h_noprog'].sum():.1f} h")

st.divider()

# --- 4) Expansión solo para análisis por línea -----------------------------
df_por_linea = expandir_por_linea(df)

por_linea = (df_por_linea.groupby("linea")["horas"].sum()
             .sort_values(ascending=False).reset_index())
st.plotly_chart(
    px.bar(por_linea, x="linea", y="horas",
           title="Horas perdidas por línea",
           labels={"horas": "Horas", "linea": ""}),
    use_container_width=True)

# --- 5) Resto de gráficos (usan df sin expandir) ---------------------------
por_equipo = (df.groupby("equipo")["horas"].sum()
              .sort_values().reset_index())
st.plotly_chart(
    px.bar(por_equipo, x="horas", y="equipo", orientation="h",
           title="Horas perdidas por equipo",
           labels={"horas": "Horas", "equipo": ""}),
    use_container_width=True)

top = (df.groupby("motivo")["horas"].sum()
       .sort_values(ascending=False).head(10).reset_index())
st.plotly_chart(
    px.bar(top, x="motivo", y="horas", title="Top motivos por horas",
           labels={"horas": "Horas", "motivo": ""}),
    use_container_width=True)

split = df.groupby("tipo")["horas"].sum().reset_index()
st.plotly_chart(
    px.pie(split, names="tipo", values="horas",
           title="Programado vs. No programado"),
    use_container_width=True)