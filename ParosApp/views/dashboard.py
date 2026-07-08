"""
VISTA 3 — DASHBOARD (Gerencia).
Permite ver los datos de UNA sola línea, de TODAS juntas, o COMPARAR ambas.
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

# Excluir tramos hijos (ES_CONTINUACION == SÍ).
# Los hijos aportan duración parcial del mismo evento; para no duplicar horas
# en el dashboard solo se usa el padre, que ya suma la duración total del evento.
# Nota: los hijos SÍ aparecen en el Pareto de supervisores (vista separada).
if "es_continuacion" in df.columns:
    df = df[~df["es_continuacion"].fillna("").str.strip().str.upper().isin({"SÍ","SI"})].copy()

# Fecha desde el timestamp; horas desde las duraciones H:MM
df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")
df["h_prog"] = df.get("dur_prog", "").apply(hhmm_a_horas)
df["h_noprog"] = df.get("dur_noprog", "").apply(hhmm_a_horas)
df["horas"] = df["h_prog"] + df["h_noprog"]
df["tipo"] = df["h_prog"].apply(
    lambda x: settings.PROGRAMADO if x > 0 else settings.NO_PROGRAMADO
)
# Normaliza la línea (evita problemas por espacios o celdas vacías)
df["linea"] = df.get("linea", "").fillna("").astype(str).str.strip()
df.loc[df["linea"] == "", "linea"] = "Sin línea"

# --- Filtros ---------------------------------------------------------------
LINEA_AMBAS = "Línea 1 y 2"

f1, f2 = st.columns(2)
with f1:
    periodo = st.segmented_control("Periodo", ["Hoy", "Semana", "Este Mes", "Todo"],
                                   default="Este Mes")
with f2:
    vista_linea = st.segmented_control(
        "Línea", ["Todas", "Línea 1", "Línea 2", "Comparar"], default="Todas")

# Filtro por periodo
hoy = pd.Timestamp.today().normalize()
if periodo == "Hoy":
    df = df[df["fecha"] >= hoy]
elif periodo == "Semana":
    df = df[df["fecha"] >= hoy - pd.Timedelta(days=7)]
elif periodo == "Este Mes":
    df = df[df["fecha"] >= hoy.replace(day=1)]

# Filtro por línea
comparar = vista_linea == "Comparar"
if vista_linea in ("Línea 1", "Línea 2"):
    # Un paro de "Línea 1 y 2" afecta a ambas, por eso se incluye en cada una.
    df = df[df["linea"].isin([vista_linea, LINEA_AMBAS])]
    st.caption(f"Mostrando **{vista_linea}** "
               f"(incluye paros marcados como «{LINEA_AMBAS}»).")

if df.empty:
    st.warning("No hay paros en el periodo / línea seleccionados.")
    st.stop()

# --- Métricas --------------------------------------------------------------
c1, c2, c3 = st.columns(3)
c1.metric("Paros", len(df))
c2.metric("Horas perdidas", f"{df['horas'].sum():.1f} h")
c3.metric("Horas NO programadas", f"{df['h_noprog'].sum():.1f} h")

st.divider()

# --- 1. Horas perdidas por equipo -----------------------------------------
if comparar:
    orden_equipo = (df.groupby("equipo")["horas"].sum()
                    .sort_values().index.tolist())
    por_equipo = (df.groupby(["equipo", "linea"])["horas"].sum().reset_index())
    fig1 = px.bar(por_equipo, x="horas", y="equipo", color="linea",
                  orientation="h", barmode="group",
                  category_orders={"equipo": orden_equipo},
                  title="Horas perdidas por equipo (por línea)",
                  labels={"horas": "Horas", "equipo": "", "linea": "Línea"})
else:
    por_equipo = (df.groupby("equipo")["horas"].sum()
                  .sort_values().reset_index())
    fig1 = px.bar(por_equipo, x="horas", y="equipo", orientation="h",
                  title="Horas perdidas por equipo",
                  labels={"horas": "Horas", "equipo": ""})
st.plotly_chart(fig1, use_container_width=True)

# --- 2. Top motivos por horas ---------------------------------------------
if comparar:
    top_motivos = (df.groupby("motivo")["horas"].sum()
                   .sort_values(ascending=False).head(10).index.tolist())
    top = (df[df["motivo"].isin(top_motivos)]
           .groupby(["motivo", "linea"])["horas"].sum().reset_index())
    fig2 = px.bar(top, x="motivo", y="horas", color="linea", barmode="group",
                  category_orders={"motivo": top_motivos},
                  title="Top motivos por horas (por línea)",
                  labels={"horas": "Horas", "motivo": "", "linea": "Línea"})
else:
    top = (df.groupby("motivo")["horas"].sum()
           .sort_values(ascending=False).head(10).reset_index())
    fig2 = px.bar(top, x="motivo", y="horas",
                  title="Top motivos por horas",
                  labels={"horas": "Horas", "motivo": ""})
st.plotly_chart(fig2, use_container_width=True)

# --- 3. Programado vs No programado ---------------------------------------
if comparar:
    split = df.groupby(["tipo", "linea"])["horas"].sum().reset_index()
    fig3 = px.bar(split, x="tipo", y="horas", color="linea", barmode="group",
                  title="Programado vs. No programado (por línea)",
                  labels={"horas": "Horas", "tipo": "", "linea": "Línea"})
else:
    split = df.groupby("tipo")["horas"].sum().reset_index()
    fig3 = px.pie(split, names="tipo", values="horas",
                  title="Programado vs. No programado")
st.plotly_chart(fig3, use_container_width=True)