"""
Filtros y utilidades compartidas por Dashboard, Pareto y Pareto por área.

Mantener aquí la lógica de periodo / grupo / línea garantiza que las tres
pantallas filtren EXACTAMENTE igual y que los totales cuadren entre ellas.
"""
from datetime import date as ddate, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from utils.tiempo import hoy_mx

LINEA_AMBAS = "Línea 1 y 2"
LINEAS = ["Línea 1", "Línea 2"]
GRUPOS = ["A", "B", "C"]

# Color fijo por ENTIDAD (nunca por posición): Línea 1 siempre azul, etc.
# Paleta categórica validada para daltonismo (primeros 3 slots).
COLOR_LINEA = {"Línea 1": "#2a78d6", "Línea 2": "#eb6834", LINEA_AMBAS: "#1baf7a",
               "Sin línea": "#9CA3AF"}
COLOR_GRUPO = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
COLOR_EMPRESA = {"RSI": "#2a78d6", "STEO": "#eb6834"}

COLOR_BARRA = "#2563EB"
COLOR_ACUM = "#DC2626"
COLOR_80 = "#9CA3AF"

MESES_ES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo",
            6: "Junio", 7: "Julio", 8: "Agosto", 9: "Septiembre",
            10: "Octubre", 11: "Noviembre", 12: "Diciembre"}

PERIODOS = ["Hoy", "7 días", "Este mes", "Mes anterior", "Rango", "Todo"]


# ---------------------------------------------------------------------------
# Preparación común
# ---------------------------------------------------------------------------
def marcar_hijos(df: pd.DataFrame) -> pd.Series:
    ec = df.get("es_continuacion", pd.Series("", index=df.index))
    return ec.fillna("").astype(str).str.strip().str.upper().isin({"SÍ", "SI"})


def id_evento(df: pd.DataFrame) -> pd.Series:
    """ID del EVENTO: el padre para los tramos hijo, el propio id para el resto."""
    padre = df.get("paro_padre", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    propio = df.get("id_paro", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    return padre.where(marcar_hijos(df) & (padre != ""), propio)


def texto_limpio(df: pd.DataFrame, col: str, vacio: str = "") -> pd.Series:
    s = df.get(col, pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    return s.where(s != "", vacio) if vacio else s


# ---------------------------------------------------------------------------
# Filtro de periodo
# ---------------------------------------------------------------------------
def selector_periodo(fechas: pd.Series, key: str, default: str = "Este mes",
                     incluir_hoy: bool = True) -> tuple[ddate, ddate, str]:
    """
    Dibuja el selector de periodo y devuelve (fecha_ini, fecha_fin, etiqueta),
    ambas fechas INCLUSIVAS. 'Rango' abre un calendario de/hasta.
    """
    opciones = PERIODOS if incluir_hoy else [p for p in PERIODOS if p != "Hoy"]
    periodo = st.segmented_control("Periodo", opciones, default=default,
                                   key=f"{key}_periodo") or default

    hoy = hoy_mx().date()
    validas = pd.to_datetime(fechas, errors="coerce").dropna()
    f_min = validas.min().date() if not validas.empty else hoy
    f_max = max(validas.max().date(), hoy) if not validas.empty else hoy

    if periodo == "Hoy":
        ini, fin = hoy, hoy
    elif periodo == "7 días":
        ini, fin = hoy - timedelta(days=6), hoy
    elif periodo == "Este mes":
        ini, fin = hoy.replace(day=1), hoy
    elif periodo == "Mes anterior":
        fin = hoy.replace(day=1) - timedelta(days=1)
        ini = fin.replace(day=1)
    elif periodo == "Rango":
        d_ini = min(max(hoy.replace(day=1), f_min), f_max)
        rango = st.date_input("Desde / hasta",
                              value=(d_ini, f_max),
                              min_value=f_min, max_value=f_max,
                              format="DD/MM/YYYY", key=f"{key}_rango")
        if isinstance(rango, (tuple, list)) and len(rango) == 2:
            ini, fin = rango
        else:  # el usuario solo ha elegido la primera fecha
            ini = rango[0] if isinstance(rango, (tuple, list)) and rango else hoy
            fin = ini
            st.caption("Elige también la fecha final del rango.")
    else:  
        ini, fin = f_min, f_max

    if periodo in ("Este mes", "Mes anterior"):
        etiqueta = f"{MESES_ES[ini.month]} {ini.year}"
    elif ini == fin:
        etiqueta = ini.strftime("%d/%m/%Y")
    else:
        etiqueta = f"{ini:%d/%m/%Y} – {fin:%d/%m/%Y}"
    return ini, fin, etiqueta


def filtrar_fechas(df: pd.DataFrame, col: str, ini: ddate, fin: ddate) -> pd.DataFrame:
    """Filtra por fecha inclusiva. `col` puede ser datetime o date."""
    f = pd.to_datetime(df[col], errors="coerce").dt.normalize()
    return df[(f >= pd.Timestamp(ini)) & (f <= pd.Timestamp(fin))]


# ---------------------------------------------------------------------------
# Filtros de línea / grupo
# ---------------------------------------------------------------------------
def filtrar_linea(df: pd.DataFrame, linea: str) -> pd.DataFrame:
    """Un paro de «Línea 1 y 2» detiene ambas: entra en cada línea."""
    if linea in LINEAS:
        return df[df["linea"].isin([linea, LINEA_AMBAS])]
    return df


def expandir_por_linea(df: pd.DataFrame) -> pd.DataFrame:
    """Para COMPARAR líneas: duplica los paros «Línea 1 y 2» en L1 y L2.
    (Por eso la suma de ambas líneas puede superar el total de planta.)"""
    partes = []
    for ln in LINEAS:
        p = df[df["linea"].isin([ln, LINEA_AMBAS])].copy()
        p["linea_cmp"] = ln
        partes.append(p)
    return pd.concat(partes, ignore_index=True) if partes else df.assign(linea_cmp=[])


def selector_grupo(key: str, label: str = "Grupo") -> str:
    return st.segmented_control(label, ["Todos"] + GRUPOS, default="Todos",
                                key=f"{key}_grupo") or "Todos"


def filtrar_grupo(df: pd.DataFrame, grupo: str) -> pd.DataFrame:
    if grupo in GRUPOS:
        return df[df["turno"].astype(str).str.strip().str.upper() == grupo]
    return df


# ---------------------------------------------------------------------------
# Pareto
# ---------------------------------------------------------------------------
def pareto_fig(serie_horas: pd.Series, eje_label: str, color: str = COLOR_BARRA,
               titulo: str | None = None, altura: int | None = None):
    """Barras de horas + % acumulado + corte 80%. Devuelve None si no hay datos."""
    s = serie_horas[serie_horas > 0].sort_values(ascending=False)
    if s.empty:
        return None
    acum = s.cumsum() / s.sum() * 100.0
    cats = [str(c) for c in s.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=cats, y=s.values, name="Horas perdidas", marker_color=color,
                hovertemplate="<b>%{x}</b><br>%{y:.1f} h<extra></extra>",
                secondary_y=False)
    fig.add_scatter(x=cats, y=acum.values, name="% acumulado",
                    mode="lines+markers", line=dict(color=COLOR_ACUM, width=2),
                    marker=dict(size=8),
                    hovertemplate="%{y:.0f}% acumulado<extra></extra>",
                    secondary_y=True)
    fig.add_hline(y=80, line_dash="dash", line_color=COLOR_80,
                  annotation_text="80%", annotation_position="top right",
                  secondary_y=True)
    fig.update_yaxes(title_text="Horas", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", range=[0, 105], secondary_y=True,
                     showgrid=False, tickmode="array",
                     tickvals=[0, 20, 40, 60, 80, 100], ticksuffix="%")
    fig.update_xaxes(tickangle=-35, automargin=True)
    fig.update_layout(
        title=titulo, xaxis_title=None,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        bargap=0.25, margin=dict(t=70 if titulo else 40),
        height=altura,
    )
    return fig


def vitales_80(serie_horas: pd.Series) -> list:
    """Categorías que acumulan hasta el 80% (incluye la que cruza el corte)."""
    s = serie_horas[serie_horas > 0].sort_values(ascending=False)
    if s.empty:
        return []
    acum = s.cumsum() / s.sum() * 100.0
    corte = acum[acum <= 80]
    n = len(corte) + (1 if len(corte) < len(s) else 0)
    return list(s.index[:max(n, 1)])


def barras_comparadas(df: pd.DataFrame, cat: str, serie: str, colores: dict,
                      titulo: str, eje_label: str, top: int | None = None):
    """Barras agrupadas (horas por categoría, una barra por serie) con un solo eje."""
    tot = df.groupby(cat)["horas"].sum().sort_values(ascending=False)
    if top:
        tot = tot.head(top)
    orden = tot.index.tolist()
    g = (df[df[cat].isin(orden)].groupby([cat, serie])["horas"].sum().reset_index())
    fig = go.Figure()
    for nombre, color in colores.items():
        d = g[g[serie] == nombre].set_index(cat).reindex(orden).fillna(0)
        if d["horas"].sum() == 0:
            continue
        fig.add_bar(x=orden, y=d["horas"].values, name=str(nombre),
                    marker_color=color,
                    hovertemplate=f"<b>%{{x}}</b><br>{nombre}: %{{y:.1f}} h<extra></extra>")
    fig.update_xaxes(tickangle=-35, automargin=True)
    fig.update_layout(barmode="group", title=titulo, xaxis_title=None,
                      yaxis_title="Horas", bargap=0.25, bargroupgap=0.05,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      margin=dict(t=70))
    return fig