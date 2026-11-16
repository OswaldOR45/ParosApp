"""
VISTA 3 — DASHBOARD (Gerencia).
Filtros: periodo (incluye rango personalizado), grupo (A/B/C) y línea
(una, todas o COMPARAR ambas). Las duraciones vienen en H:MM y se convierten a
horas decimales para graficar.

Tramos hijos (paros multi-turno): el PADRE solo trae la duración de SU tramo.
Las HORAS se suman con todos los registros (cada tramo cae en el día/grupo en
que ocurrió) y el CONTEO de paros usa solo padres (1 evento = 1 paro).
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from config import settings
from data.sheets import leer_paros
from utils.tiempo import hhmm_a_horas
from utils.filtros import (selector_periodo, filtrar_fechas, selector_grupo,
                           filtrar_grupo, filtrar_linea, expandir_por_linea,
                           marcar_hijos, texto_limpio, barras_comparadas,
                           COLOR_LINEA, COLOR_GRUPO, LINEA_AMBAS)

st.title("Dashboard de Paros")

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
df["tipo"] = df["h_prog"].apply(
    lambda x: settings.PROGRAMADO if x > 0 else settings.NO_PROGRAMADO)
df["linea"] = texto_limpio(df, "linea", "Sin línea")
df["turno"] = texto_limpio(df, "turno")
df["equipo"] = texto_limpio(df, "equipo", "Sin equipo")
df["motivo"] = texto_limpio(df, "motivo", "Sin motivo")

# --- Filtros ---------------------------------------------------------------
ini, fin, etiqueta = selector_periodo(df["fecha"], key="dash")
f1, f2 = st.columns(2)
with f1:
    grupo = selector_grupo(key="dash")
with f2:
    vista_linea = st.segmented_control(
        "Línea", ["Todas", "Línea 1", "Línea 2", "Comparar"],
        default="Todas", key="dash_linea") or "Todas"

df = filtrar_fechas(df, "fecha", ini, fin)
df = filtrar_grupo(df, grupo)
comparar = vista_linea == "Comparar"
if vista_linea in ("Línea 1", "Línea 2"):
    df = filtrar_linea(df, vista_linea)

partes = [f"**{etiqueta}**"]
if grupo != "Todos":
    partes.append(f"grupo **{grupo}**")
if vista_linea in ("Línea 1", "Línea 2"):
    partes.append(f"**{vista_linea}** (incluye «{LINEA_AMBAS}»)")
st.caption("Mostrando " + " · ".join(partes))

if df.empty:
    st.warning("No hay paros con estos filtros.")
    st.stop()

# --- Métricas --------------------------------------------------------------
if comparar:
    dfc = expandir_por_linea(df)
    cols = st.columns(2)
    for col, ln in zip(cols, ["Línea 1", "Línea 2"]):
        d = dfc[dfc["linea_cmp"] == ln]
        with col:
            st.markdown(f"**{ln}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Paros", int((~d["es_hijo"]).sum()))
            m2.metric("Horas", f"{d['horas'].sum():.1f} h")
            m3.metric("No prog.", f"{d['h_noprog'].sum():.1f} h")
    st.caption(f"Los paros de «{LINEA_AMBAS}» cuentan en las dos líneas.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Paros", int((~df["es_hijo"]).sum()))
    c2.metric("Horas perdidas", f"{df['horas'].sum():.1f} h")
    c3.metric("Horas NO programadas", f"{df['h_noprog'].sum():.1f} h")

st.divider()

COLORES_CMP = {k: COLOR_LINEA[k] for k in ("Línea 1", "Línea 2")}

# --- 1. Horas perdidas por equipo -----------------------------------------
if comparar:
    fig1 = barras_comparadas(dfc.rename(columns={"linea_cmp": "serie"}), "equipo",
                             "serie", COLORES_CMP,
                             "Horas perdidas por equipo (por línea)", "")
else:
    por_equipo = df.groupby("equipo")["horas"].sum().sort_values().reset_index()
    fig1 = px.bar(por_equipo, x="horas", y="equipo", orientation="h",
                  title="Horas perdidas por equipo",
                  labels={"horas": "Horas", "equipo": ""})
st.plotly_chart(fig1, width="stretch")

# --- 2. Top motivos por horas ---------------------------------------------
if comparar:
    fig2 = barras_comparadas(dfc.rename(columns={"linea_cmp": "serie"}), "motivo",
                             "serie", COLORES_CMP,
                             "Top 10 motivos por horas (por línea)", "", top=10)
else:
    top = (df.groupby("motivo")["horas"].sum()
           .sort_values(ascending=False).head(10).reset_index())
    fig2 = px.bar(top, x="motivo", y="horas", title="Top 10 motivos por horas",
                  labels={"horas": "Horas", "motivo": ""})
st.plotly_chart(fig2, width="stretch")

# --- 3. Programado vs No programado ---------------------------------------
if comparar:
    fig3 = barras_comparadas(dfc.rename(columns={"linea_cmp": "serie"}), "tipo",
                             "serie", COLORES_CMP,
                             "Programado vs. No programado (por línea)", "")
else:
    split = df.groupby("tipo")["horas"].sum().reset_index()
    fig3 = px.pie(split, names="tipo", values="horas",
                  title="Programado vs. No programado")
st.plotly_chart(fig3, width="stretch")

# --- 4. Horas por grupo (útil cuando se ven todos los grupos) -------------
if grupo == "Todos":
    dg = df[df["turno"].isin(COLOR_GRUPO)]
    if not dg.empty:
        fig4 = barras_comparadas(dg, "tipo", "turno", COLOR_GRUPO,
                                 "Horas perdidas por grupo", "")
        st.plotly_chart(fig4, width="stretch")