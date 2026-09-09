"""
VISTA — PARETO POR ÁREA + TND (Tiempo Neto Disponible)
========================================================
Sección aparte del Pareto general. Dos pestañas:

  · Supervisores  : Pareto de motivos NO PROGRAMADOS por área, filtrable
                    por grupo (A/B/C). Incluye los tramos hijo de paros
                    multi-turno tal cual (cada supervisor ve SU aportación),
                    igual que decidimos para el Pareto general.
  · Mantenimiento : Pareto por EQUIPO de los paros que requirieron apoyo
                    externo (RSI/STEO/AMBOS). Aquí SÍ se excluyen los
                    tramos hijo y se suma su duración al padre, porque a
                    mantenimiento le interesa el tiempo total del evento,
                    no la fracción de cada turno.

TND (Tiempo Neto Disponible) = 480 min (turno de 8h) − minutos de paros
PROGRAMADOS de esa línea en ese turno horario (Matutino/Vespertino/
Nocturno) y ese día. Solo se resta lo PROGRAMADO: los correctivos son
pérdida de rendimiento, no de disponibilidad planeada, y ya se ven en
el Pareto.

Áreas cubiertas: Molienda (1 línea), Extrusión (2 líneas), Envasado/
Empaque (2 líneas). Un paro registrado en "Línea 1 y 2" resta de las
DOS líneas del área, porque detiene ambas a la vez.
"""
import re
import unicodedata
from datetime import time as dtime, date as ddate

import pandas as pd
from plotly.subplots import make_subplots
import streamlit as st

from config import settings
from data.sheets import leer_paros, cargar_catalogos
from utils.tiempo import hhmm_a_horas

MIN_TURNO = 480  # 8 horas
LINEA_AMBAS = "Línea 1 y 2"
TURNOS_HORARIO = ["Matutino", "Vespertino", "Nocturno"]  # orden = INTERVALOS_TURNO

COLOR_BARRA = "#2563EB"
COLOR_LINEA = "#DC2626"
COLOR_80 = "#9CA3AF"

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre",
    11: "Noviembre", 12: "Diciembre",
}

# Áreas objetivo: clave normalizada -> (etiqueta bonita, líneas que aplican)
AREAS_OBJETIVO = {
    "MOLIENDA":  {"label": "Molienda",  "lineas": ["Línea 1"]},
    "EXTRUSION": {"label": "Extrusión", "lineas": ["Línea 1", "Línea 2"]},
    "EMPAQUE":   {"label": "Envasado",  "lineas": ["Línea 1", "Línea 2"]},
}
# Alias -> hacia qué clave de AREAS_OBJETIVO mapea (por si el dato viene
# escrito distinto: "ENVASADO" en vez de "EMPAQUE", etc.)
ALIAS_AREA = {
    "MOLIENDA": "MOLIENDA",
    "EXTRUSION": "EXTRUSION",
    "EMPAQUE": "EMPAQUE",
    "ENVASADO": "EMPAQUE",
}


def _norm(texto) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _to_min(valor) -> float:
    """Convierte 'H:MM' o 'H:MM:SS' a minutos. Vacío/():0."""
    s = str(valor).strip()
    if not s or ":" not in s:
        return 0.0
    partes = s.split(":")
    try:
        h = int(partes[0])
        m = int(partes[1])
        return float(h * 60 + m)
    except (ValueError, IndexError):
        return 0.0


def _turno_horario(hora_str) -> str | None:
    """Dado 'HH:MM', devuelve 'Matutino' / 'Vespertino' / 'Nocturno' según
    settings.INTERVALOS_TURNO, o None si no se puede interpretar."""
    s = str(hora_str).strip()
    if not s or ":" not in s:
        return None
    try:
        h, m = map(int, s.split(":")[:2])
    except ValueError:
        return None
    t = dtime(h, m)
    for label, (ini_str, fin_str) in zip(TURNOS_HORARIO, settings.INTERVALOS_TURNO):
        h_ini, m_ini = map(int, ini_str.split(":"))
        h_fin, m_fin = map(int, fin_str.split(":"))
        t_ini, t_fin = dtime(h_ini, m_ini), dtime(h_fin, m_fin)
        if t_ini < t_fin:
            if t_ini <= t < t_fin:
                return label
        else:  # cruza medianoche (Nocturno)
            if t >= t_ini or t < t_fin:
                return label
    return None


def pareto_fig(serie_horas: pd.Series, eje_label: str):
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
    s = serie_horas[serie_horas > 0].sort_values(ascending=False)
    if s.empty:
        return []
    acum = s.cumsum() / s.sum() * 100.0
    corte = acum[acum <= 80]
    n = len(corte) + (1 if len(corte) < len(s) else 0)
    return list(s.index[:max(n, 1)])


def _mes_selector(fechas: pd.Series, key: str):
    """Selector de mes a partir de las fechas presentes en los datos.
    Devuelve (año, mes, fecha_ini, fecha_fin)."""
    fechas_validas = fechas.dropna()
    if fechas_validas.empty:
        hoy = pd.Timestamp.today()
        opciones = [(hoy.year, hoy.month)]
    else:
        pares = sorted({(d.year, d.month) for d in fechas_validas}, reverse=True)
        opciones = pares

    etiquetas = [f"{MESES_ES[m]} {a}" for a, m in opciones]
    idx_default = 0
    hoy = pd.Timestamp.today()
    if (hoy.year, hoy.month) in opciones:
        idx_default = opciones.index((hoy.year, hoy.month))

    sel = st.selectbox("Mes", etiquetas, index=idx_default, key=key)
    anio, mes = opciones[etiquetas.index(sel)]
    fecha_ini = ddate(anio, mes, 1)
    if mes == 12:
        fecha_fin = ddate(anio, 12, 31)
    else:
        fecha_fin = ddate(anio, mes + 1, 1) - pd.Timedelta(days=1)
        fecha_fin = fecha_fin.date() if hasattr(fecha_fin, "date") else fecha_fin
    return anio, mes, fecha_ini, fecha_fin


def _area_key(valor_area: str) -> str | None:
    n = _norm(valor_area)
    return ALIAS_AREA.get(n)


def calcular_tnd(df_prog: pd.DataFrame, area_key: str,
                  fecha_ini: ddate, fecha_fin: ddate) -> pd.DataFrame:
    """
    df_prog: paros PROGRAMADOS ya filtrados a esta área, con columnas
             'fecha_dia' (date), 'turno_horario', 'linea', 'min_prog'.
    Devuelve una tabla con TND por (Fecha, Línea, Turno).
    """
    lineas_area = AREAS_OBJETIVO[area_key]["lineas"]
    dias = pd.date_range(fecha_ini, fecha_fin, freq="D")

    filas = []
    for dia in dias:
        dia_d = dia.date()
        for linea in lineas_area:
            mask_linea = df_prog["linea"].isin([linea, LINEA_AMBAS])
            for turno_lbl in TURNOS_HORARIO:
                mask = (
                    (df_prog["fecha_dia"] == dia_d)
                    & (df_prog["turno_horario"] == turno_lbl)
                    & mask_linea
                )
                min_perdidos = df_prog.loc[mask, "min_prog"].sum()
                tnd_min = MIN_TURNO - min_perdidos
                filas.append({
                    "Fecha": dia_d,
                    "Línea": linea,
                    "Turno": turno_lbl,
                    "Min. programados": round(min_perdidos, 0),
                    "TND (min)": round(tnd_min, 0),
                    "TND (h)": round(tnd_min / 60, 2),
                })
    return pd.DataFrame(filas)


def mostrar_tnd(df_prog_mes: pd.DataFrame, area_key: str,
                 fecha_ini: ddate, fecha_fin: ddate, key_prefix: str):
    """Renderiza el bloque de TND para un área: resumen + detalle expandible."""
    label = AREAS_OBJETIVO[area_key]["label"]
    tabla = calcular_tnd(df_prog_mes, area_key, fecha_ini, fecha_fin)

    if tabla.empty:
        st.info(f"Sin datos de TND para {label} en este periodo.")
        return

    resumen = (tabla.groupby(["Línea", "Turno"])
               .agg(**{"TND promedio (h)": ("TND (h)", "mean"),
                       "TND total (h)": ("TND (h)", "sum"),
                       "Días": ("Fecha", "nunique")})
               .reset_index())
    resumen["TND promedio (h)"] = resumen["TND promedio (h)"].round(2)
    resumen["TND total (h)"] = resumen["TND total (h)"].round(1)

    st.markdown(f"**TND — {label}**")
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    with st.expander(f"Ver detalle día por día · {label}"):
        st.dataframe(
            tabla.sort_values(["Fecha", "Línea", "Turno"]),
            use_container_width=True, hide_index=True,
        )


# ===========================================================================
st.title("Pareto por área + TND")

df_raw = leer_paros()
if df_raw.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

# --- Preparación común -------------------------------------------------
df_raw = df_raw.copy()
df_raw["fecha_ts"] = pd.to_datetime(df_raw.get("timestamp"), errors="coerce")
df_raw["fecha_dia"] = df_raw["fecha_ts"].dt.date
df_raw["h_prog"] = df_raw.get("dur_prog", "").apply(hhmm_a_horas)
df_raw["h_noprog"] = df_raw.get("dur_noprog", "").apply(hhmm_a_horas)
df_raw["horas"] = df_raw["h_prog"] + df_raw["h_noprog"]
df_raw["min_prog"] = df_raw.get("dur_prog", "").apply(_to_min)

df_raw["area"] = df_raw.get("area", "").fillna("").astype(str).str.strip()
df_raw["linea"] = df_raw.get("linea", "").fillna("").astype(str).str.strip()
df_raw["motivo"] = df_raw.get("motivo", "").fillna("").astype(str).str.strip()
df_raw["turno"] = df_raw.get("turno", "").fillna("").astype(str).str.strip()  # grupo A/B/C

df_raw["area_key"] = df_raw["area"].apply(_area_key)

# Clasificación PROGRAMADO / NO PROGRAMADO (mismo catálogo que pareto.py)
tipo_por_motivo = cargar_catalogos().get("tipo_por_motivo", {})
tipo_norm = {_norm(k): v for k, v in tipo_por_motivo.items()}
df_raw["tipo"] = df_raw["motivo"].map(lambda m: tipo_norm.get(_norm(m), settings.NO_PROGRAMADO))

# Turno horario (Matutino/Vespertino/Nocturno) a partir de la hora de inicio.
# Los paros PROGRAMADOS usan ini_prog; los NO PROGRAMADOS, ini_noprog.
df_raw["hora_ini_efectiva"] = df_raw.get("ini_prog", "").where(
    df_raw.get("ini_prog", "").astype(str).str.strip() != "",
    df_raw.get("ini_noprog", ""),
)
df_raw["turno_horario"] = df_raw["hora_ini_efectiva"].apply(_turno_horario)

# Solo nos interesan los registros de las 3 áreas objetivo para esta vista
df_areas = df_raw[df_raw["area_key"].notna()].copy()

if df_areas.empty:
    st.warning(
        "No se encontraron registros en Molienda, Extrusión o Envasado/Empaque. "
        "Revisa que el campo ÁREA use esos nombres."
    )
    st.stop()

tab_sup, tab_mtto = st.tabs(["👷 Supervisores", "🔧 Mantenimiento"])

# ===========================================================================
# PESTAÑA SUPERVISORES
# ===========================================================================
with tab_sup:
    st.caption(
        "Pareto de motivos no programados por área y grupo, con el TND del "
        "mismo periodo como referencia de disponibilidad."
    )

    anio_s, mes_s, ini_s, fin_s = _mes_selector(df_areas["fecha_ts"], key="mes_sup")

    fcol1, fcol2 = st.columns(2)
    with fcol1:
        opciones_area = ["Todas"] + [v["label"] for v in AREAS_OBJETIVO.values()]
        area_sel_sup = st.segmented_control("Área", opciones_area,
                                            default="Todas", key="area_sup")
    with fcol2:
        grupo_sel = st.segmented_control("Grupo", ["Todos", "A", "B", "C"],
                                         default="Todos", key="grupo_sup")

    label_to_key = {v["label"]: k for k, v in AREAS_OBJETIVO.items()}

    # --- Filtrado del periodo (mes completo) --------------------------
    df_mes_sup = df_areas[
        (df_areas["fecha_dia"] >= ini_s) & (df_areas["fecha_dia"] <= fin_s)
    ].copy()

    if area_sel_sup != "Todas":
        df_mes_sup = df_mes_sup[df_mes_sup["area_key"] == label_to_key[area_sel_sup]]

    if grupo_sel != "Todos":
        df_mes_sup = df_mes_sup[df_mes_sup["turno"] == grupo_sel]

    # --- Pareto: solo NO PROGRAMADOS, incluye tramos hijo tal cual -----
    # (cada supervisor ve su propia aportación, como se decidió para el
    # Pareto por grupo).
    df_pareto_sup = df_mes_sup[
        (df_mes_sup["tipo"] == settings.NO_PROGRAMADO) & (df_mes_sup["horas"] > 0)
    ]

    st.divider()
    st.subheader(f"Pareto de motivos — {MESES_ES[mes_s]} {anio_s}")

    if df_pareto_sup.empty:
        st.warning("No hay paros no programados para este filtro.")
    else:
        por_motivo_sup = df_pareto_sup.groupby("motivo")["horas"].sum()
        fig_sup = pareto_fig(por_motivo_sup, "Motivo")
        st.plotly_chart(fig_sup, width="stretch")

        c1, c2 = st.columns(2)
        c1.metric("Paros no programados", len(df_pareto_sup))
        c2.metric("Horas perdidas", f"{df_pareto_sup['horas'].sum():.1f} h")

        vitales = vitales_80(por_motivo_sup)
        if vitales:
            st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, vitales)))

    st.divider()
    st.subheader("TND del periodo")

    # Paros PROGRAMADOS del mes, dentro de las áreas objetivo (sin filtro
    # de grupo: el TND es de la línea, no del supervisor específico).
    df_prog_mes = df_areas[
        (df_areas["fecha_dia"] >= ini_s) & (df_areas["fecha_dia"] <= fin_s)
        & (df_areas["tipo"] == settings.PROGRAMADO)
        & (df_areas["turno_horario"].notna())
    ]

    areas_a_mostrar = (
        [label_to_key[area_sel_sup]] if area_sel_sup != "Todas"
        else list(AREAS_OBJETIVO.keys())
    )
    for ak in areas_a_mostrar:
        df_prog_area = df_prog_mes[df_prog_mes["area_key"] == ak]
        mostrar_tnd(df_prog_area, ak, ini_s, fin_s, key_prefix=f"sup_{ak}")

# ===========================================================================
# PESTAÑA MANTENIMIENTO
# ===========================================================================
with tab_mtto:
    st.caption(
        "Pareto por equipo de los paros que requirieron apoyo externo "
        "(RSI / STEO / AMBOS), con el TND del mismo periodo. Los tramos "
        "de paros multi-turno se suman a su padre para reflejar el tiempo "
        "total del evento."
    )

    anio_m, mes_m, ini_m, fin_m = _mes_selector(df_areas["fecha_ts"], key="mes_mtto")

    area_sel_mtto = st.segmented_control(
        "Área", ["Todas"] + [v["label"] for v in AREAS_OBJETIVO.values()],
        default="Todas", key="area_mtto",
    )

    df_mes_mtto = df_areas[
        (df_areas["fecha_dia"] >= ini_m) & (df_areas["fecha_dia"] <= fin_m)
    ].copy()

    if area_sel_mtto != "Todas":
        df_mes_mtto = df_mes_mtto[df_mes_mtto["area_key"] == label_to_key[area_sel_mtto]]

    # Solo paros que requirieron apoyo externo (relevantes para mantenimiento)
    apoyo = df_mes_mtto.get("necesita_acr", "").fillna("").astype(str).str.strip().str.upper()
    df_mes_mtto = df_mes_mtto[apoyo.isin({"RSI", "STEO", "AMBOS", "SI", "SÍ"})]

    # Excluir hijos y sumar su duración al padre: a mantenimiento le
    # interesa el tiempo total del evento, no el tramo de cada turno.
    if "es_continuacion" in df_mes_mtto.columns:
        ec = df_mes_mtto["es_continuacion"].fillna("").str.strip().str.upper()
        hijos_m = df_mes_mtto[ec.isin({"SÍ", "SI"})].copy()
        df_mes_mtto = df_mes_mtto[~ec.isin({"SÍ", "SI"})].copy()

        if not hijos_m.empty and "paro_padre" in hijos_m.columns:
            suma_hijos = (hijos_m.groupby("paro_padre")["horas"]
                         .sum().reset_index()
                         .rename(columns={"paro_padre": "id_paro", "horas": "horas_hijos"}))
            df_mes_mtto = df_mes_mtto.merge(suma_hijos, on="id_paro", how="left")
            df_mes_mtto["horas_hijos"] = df_mes_mtto["horas_hijos"].fillna(0)
            df_mes_mtto["horas"] = df_mes_mtto["horas"] + df_mes_mtto["horas_hijos"]

    df_mes_mtto["equipo"] = df_mes_mtto.get("equipo", "").fillna("").astype(str).str.strip()
    df_pareto_mtto = df_mes_mtto[df_mes_mtto["horas"] > 0]

    st.divider()
    st.subheader(f"Pareto por equipo — {MESES_ES[mes_m]} {anio_m}")

    if df_pareto_mtto.empty:
        st.warning("No hay paros con apoyo externo para este filtro.")
    else:
        por_equipo = df_pareto_mtto.groupby("equipo")["horas"].sum()
        fig_mtto = pareto_fig(por_equipo, "Equipo")
        st.plotly_chart(fig_mtto, width="stretch")

        c1, c2 = st.columns(2)
        c1.metric("Eventos con apoyo externo", len(df_pareto_mtto))
        c2.metric("Horas totales", f"{df_pareto_mtto['horas'].sum():.1f} h")

        vitales_eq = vitales_80(por_equipo)
        if vitales_eq:
            st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, vitales_eq)))

    st.divider()
    st.subheader("TND del periodo")

    df_prog_mes_m = df_areas[
        (df_areas["fecha_dia"] >= ini_m) & (df_areas["fecha_dia"] <= fin_m)
        & (df_areas["tipo"] == settings.PROGRAMADO)
        & (df_areas["turno_horario"].notna())
    ]

    areas_a_mostrar_m = (
        [label_to_key[area_sel_mtto]] if area_sel_mtto != "Todas"
        else list(AREAS_OBJETIVO.keys())
    )
    for ak in areas_a_mostrar_m:
        df_prog_area_m = df_prog_mes_m[df_prog_mes_m["area_key"] == ak]
        mostrar_tnd(df_prog_area_m, ak, ini_m, fin_m, key_prefix=f"mtto_{ak}")