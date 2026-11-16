"""
VISTA — PARETO POR ÁREA + TND (Tiempo Neto Disponible)
========================================================
Dos pestañas:

  · Supervisores  : Pareto de motivos NO PROGRAMADOS por área. Filtros de
                    periodo (incluye rango), área, línea y grupo; vistas para
                    COMPARAR líneas o COMPARAR grupos. Incluye los tramos hijo
                    de paros multi-turno tal cual (cada grupo ve SU aportación).
                    Debajo, el TND del periodo en formato visual: tarjetas por
                    grupo, mapa de calor día × grupo y lista de los turnos que
                    sí tuvieron paros programados.
  · Mantenimiento : Pareto por EQUIPO de los paros que requirieron apoyo
                    externo, separado por empresa (RSI / STEO) o comparando
                    ambas. Los tramos hijo se suman al padre (tiempo total del
                    evento). Sin TND: mantenimiento no produce.

TND = minutos que trabajó el grupo ese día − minutos de paros PROGRAMADOS de
esa línea, ese grupo y ese día de turno. Por defecto el grupo trabaja 480 min
(8 h); las excepciones (vacaciones = 0, turnos de 12 h, dobles) se capturan
en la hoja ROL_TURNOS desde el formulario de esta misma vista. Un paro de
"Línea 1 y 2" resta de las DOS líneas.
"""
import re
import unicodedata
from datetime import datetime as ddatetime, time as dtime, date as ddate, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import settings
from data.sheets import (leer_paros, cargar_catalogos, leer_rol_turnos,
                         guardar_rol_turnos)
from utils.tiempo import hhmm_a_horas, hoy_mx
from utils.auth import verificar_password
from utils.filtros import (selector_periodo, filtrar_fechas, filtrar_linea,
                           filtrar_grupo, expandir_por_linea, marcar_hijos,
                           pareto_fig, vitales_80, barras_comparadas,
                           COLOR_LINEA, COLOR_GRUPO, COLOR_EMPRESA,
                           LINEA_AMBAS, LINEAS, GRUPOS)

MIN_TURNO = 480  # 8 horas

# Áreas objetivo: clave normalizada -> (etiqueta, líneas que aplican)
AREAS_OBJETIVO = {
    "MOLIENDA":  {"label": "Molienda",  "lineas": ["Línea 1"]},
    "EXTRUSION": {"label": "Extrusión", "lineas": ["Línea 1", "Línea 2"]},
    "EMPAQUE":   {"label": "Envasado",  "lineas": ["Línea 1", "Línea 2"]},
}
ALIAS_AREA = {"MOLIENDA": "MOLIENDA", "EXTRUSION": "EXTRUSION",
              "EMPAQUE": "EMPAQUE", "ENVASADO": "EMPAQUE"}
LABEL_TO_KEY = {v["label"]: k for k, v in AREAS_OBJETIVO.items()}

# Escala secuencial de UN tono: blanco = turno completo, azul oscuro = más
# minutos perdidos por paros programados.
ESCALA_TND = [[0.0, "#F8FAFC"], [0.001, "#DBEAFE"], [0.5, "#60A5FA"], [1.0, "#1E3A8A"]]


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


def _fecha_turno(ts, hora_str):
    """
    Fecha en que ARRANCÓ el turno al que pertenece el paro.

    El turno nocturno (21:00-05:00) cruza la medianoche: un paro a las 03:00
    pertenece al turno que empezó la noche anterior. Sin este ajuste, el TND
    de un grupo nocturno mezclaría dos turnos en un mismo día calendario.

    ts       : momento de REGISTRO (Timestamp). Sirve para saber si el paro
               arrancó el día anterior (ej. paro 23:57 registrado a las 02:32).
    hora_str : hora de inicio del paro 'H:MM'.
    """
    if pd.isna(ts):
        return None
    s = str(hora_str).strip()
    if not s or ":" not in s:
        return None
    try:
        h, m = map(int, s.split(":")[:2])
    except ValueError:
        return None

    t = dtime(h, m)
    inicio = ddatetime.combine(ts.date(), t)
    # Un paro no puede arrancar después de registrarse: si "cae en el futuro"
    # (con 1 h de tolerancia), en realidad arrancó el día anterior.
    if inicio > ts.to_pydatetime() + timedelta(hours=1):
        inicio -= timedelta(days=1)

    fecha = inicio.date()
    h_ini, m_ini = map(int, settings.INTERVALOS_TURNO[0][0].split(":"))
    if t < dtime(h_ini, m_ini):      # madrugada = turno nocturno del día anterior
        fecha -= timedelta(days=1)
    return fecha


def _area_key(valor_area: str) -> str | None:
    n = _norm(valor_area)
    return ALIAS_AREA.get(n)




# ---------------------------------------------------------------------------
# TND
# ---------------------------------------------------------------------------
def base_turnos(rol: pd.DataFrame) -> dict:
    """{(fecha, grupo): minutos trabajados} solo para las EXCEPCIONES del rol."""
    if rol is None or rol.empty:
        return {}
    return {(r.fecha, r.grupo): float(r.horas) * 60 for r in rol.itertuples()}


def calcular_tnd(df_prog: pd.DataFrame, area_key: str, fecha_ini: ddate,
                 fecha_fin: ddate, grupos: list, lineas: list,
                 bases: dict | None = None) -> pd.DataFrame:
    """
    TND por (día de turno, línea, grupo).
    Base = minutos que el grupo trabajó ese día: 480 por defecto, o lo que
    diga ROL_TURNOS (0 = no trabajó, 720 = turno de 12 h, 960 = doble).
    Los días con base 0 se marcan como descanso y NO cuentan en promedios.
    """
    bases = bases or {}
    lineas_area = [l for l in AREAS_OBJETIVO[area_key]["lineas"] if l in lineas]
    filas = []
    for dia in pd.date_range(fecha_ini, fecha_fin, freq="D"):
        dia_d = dia.date()
        del_dia = df_prog[df_prog["fecha_turno"] == dia_d]
        for linea in lineas_area:
            d_ln = del_dia[del_dia["linea"].isin([linea, LINEA_AMBAS])]
            for grupo in grupos:
                base = bases.get((dia_d, grupo), float(MIN_TURNO))
                d = d_ln[d_ln["turno"] == grupo]
                # Tope = minutos trabajados: un paro programado más largo que
                # el turno no puede dejar un TND negativo.
                perdidos = min(float(d["min_prog"].sum()), base)
                filas.append({
                    "Fecha": dia_d, "Línea": linea, "Grupo": grupo,
                    "Turno (h)": round(base / 60, 1),
                    "Min. programados": round(perdidos),
                    "TND (h)": round((base - perdidos) / 60, 2),
                    "Motivos": ", ".join(sorted(set(d["motivo"]) - {""})),
                    "Descanso": base == 0,
                    "Min. registrados": round(float(d["min_prog"].sum())),
                })
    return pd.DataFrame(filas)


def _heatmap_tnd(tabla: pd.DataFrame, label: str, varias_lineas: bool):
    t = tabla.copy()
    t["Fila"] = "Grupo " + t["Grupo"] + ((" · " + t["Línea"]) if varias_lineas else "")
    filas = sorted(t["Fila"].unique(), reverse=True)  # A arriba
    fechas = sorted(t["Fecha"].unique())

    def _piv(col):
        return t.pivot_table(index="Fila", columns="Fecha", values=col,
                             aggfunc="first").reindex(index=filas, columns=fechas)

    perd, base, tnd = _piv("Min. programados"), _piv("Turno (h)"), _piv("TND (h)")
    mot = _piv("Motivos").fillna("")
    z = perd.where(base > 0)          # descanso -> celda vacía (sin color)

    texto, custom = [], []
    for i in range(len(filas)):
        fila_txt, fila_cd = [], []
        for j in range(len(fechas)):
            b, p, v = base.iat[i, j], perd.iat[i, j], tnd.iat[i, j]
            if pd.isna(b):
                fila_txt.append(""); fila_cd.append(["", "", ""]); continue
            if b == 0:
                fila_txt.append("D")
                fila_cd.append([0, 0, "No trabajó (descanso / vacaciones)"])
                continue
            normal = abs(b - 8) < 0.01
            if p > 0:
                fila_txt.append(f"{v:.1f}" if normal else f"{v:.1f}/{b:g}")
            else:
                fila_txt.append("" if normal else f"{b:g}h")
            fila_cd.append([v, b, mot.iat[i, j] or "Sin paros programados"])
        texto.append(fila_txt); custom.append(fila_cd)

    fig = go.Figure(go.Heatmap(
        z=z.values, x=[pd.Timestamp(f) for f in fechas], y=filas,
        text=texto, texttemplate="%{text}", textfont=dict(size=10),
        customdata=custom,
        hovertemplate=("<b>%{y}</b> · %{x|%d/%m}<br>Turno: %{customdata[1]} h"
                       "<br>TND: %{customdata[0]} h<br>Perdido: %{z:.0f} min"
                       "<br>%{customdata[2]}<extra></extra>"),
        colorscale=ESCALA_TND, zmin=0, zmax=MIN_TURNO,
        xgap=2, ygap=2, colorbar=dict(title="Min<br>perdidos", thickness=12),
    ))
    fig.update_layout(title=f"{label} — TND por día",
                      height=140 + 36 * len(filas),
                      margin=dict(t=50, b=40, l=120, r=10),
                      plot_bgcolor="#E5E7EB",   # gris = descanso
                      xaxis=dict(tickformat="%d/%m", showgrid=False, automargin=True,
                                 dtick=86400000 * (1 if len(fechas) <= 35 else 7)),
                      yaxis=dict(showgrid=False, automargin=True))
    return fig


def mostrar_tnd(df_prog: pd.DataFrame, area_key: str, ini: ddate, fin: ddate,
                grupos: list, lineas: list, key: str, bases: dict | None = None):
    label = AREAS_OBJETIVO[area_key]["label"]
    tabla = calcular_tnd(df_prog, area_key, ini, fin, grupos, lineas, bases)
    if tabla.empty:
        st.info(f"{label}: no aplica para la línea seleccionada.")
        return

    st.markdown(f"#### {label}")
    varias_lineas = tabla["Línea"].nunique() > 1
    trab = tabla[~tabla["Descanso"]]

    # Paros registrados por un grupo en un día que, según ROL_TURNOS, no
    # trabajó: o el rol está mal o el paro tiene el grupo equivocado.
    conflicto = tabla[tabla["Descanso"] & (tabla["Min. registrados"] > 0)]
    if not conflicto.empty:
        casos = (conflicto.drop_duplicates(["Fecha", "Grupo"])
                 .apply(lambda r: f"{r['Fecha']:%d/%m} grupo {r['Grupo']}", axis=1))
        st.warning("Hay paros programados capturados por un grupo marcado como "
                   "**no trabajó**: " + ", ".join(casos) + ". Revisa el grupo del "
                   "paro o el registro de turnos especiales; esos minutos no se "
                   "están restando.", icon="⚠️")

    # 1) Tarjetas por grupo: % disponibilidad = horas netas / horas trabajadas.
    #    Con turnos de 8 y 12 h mezclados, el % es comparable; el promedio de
    #    horas por turno no.
    resumen = (trab.groupby(["Línea", "Grupo"])
               .agg(base_h=("Turno (h)", "sum"), tnd_h=("TND (h)", "sum"),
                    turnos=("Fecha", "size"),
                    afectados=("Min. programados", lambda x: int((x > 0).sum())),
                    especiales=("Turno (h)", lambda x: int((x != 8).sum())))
               .reset_index())
    descansos = tabla[tabla["Descanso"]].groupby(["Línea", "Grupo"]).size()

    for linea in sorted(tabla["Línea"].unique()):
        if varias_lineas:
            st.caption(f"**{linea}**")
        r_ln = resumen[resumen["Línea"] == linea].set_index("Grupo")
        cols = st.columns(len(grupos))
        for col, g in zip(cols, grupos):
            n_desc = int(descansos.get((linea, g), 0))
            if g not in r_ln.index:
                col.metric(f"Grupo {g}", "—", help=f"No trabajó en el periodo ({n_desc} días)")
                continue
            r = r_ln.loc[g]
            perd_h = r["base_h"] - r["tnd_h"]
            disp = r["tnd_h"] / r["base_h"] * 100 if r["base_h"] else 0
            extra = []
            if r["especiales"]:
                extra.append(f"{r['especiales']} turno(s) de 12 h o más")
            if n_desc:
                extra.append(f"{n_desc} día(s) sin trabajar")
            col.metric(
                f"Grupo {g}", f"{disp:.1f} %",
                delta=f"−{perd_h:.1f} h programadas" if perd_h > 0 else "Sin paros programados",
                delta_color="inverse" if perd_h > 0 else "off",
                help=(f"Disponibilidad = horas netas / horas trabajadas. "
                      f"{r['tnd_h']:.1f} h netas de {r['base_h']:.0f} h trabajadas en "
                      f"{r['turnos']} turnos · {r['afectados']} con paro programado"
                      + (" · " + " · ".join(extra) if extra else "")))

    # 2) Mapa de calor
    st.plotly_chart(_heatmap_tnd(tabla, label, varias_lineas), width="stretch",
                    key=f"{key}_heat")
    st.caption("Blanco = turno completo · azul = tiempo programado perdido "
               "(el número son las horas que quedaron) · **12h**/**16h** = turno "
               "especial · **D** = no trabajó.")

    # 3) Solo los turnos que perdieron tiempo
    afect = trab[trab["Min. programados"] > 0].sort_values(["Fecha", "Grupo", "Línea"])
    with st.expander(f"Turnos con paro programado · {len(afect)}"):
        if afect.empty:
            st.caption("Ningún turno tuvo paros programados en el periodo.")
        else:
            vista = afect.assign(
                Fecha=pd.to_datetime(afect["Fecha"]).dt.strftime("%d/%m/%Y"),
                **{"Disponible": afect["TND (h)"] / afect["Turno (h)"] * 100})
            st.dataframe(vista[["Fecha", "Grupo", "Línea", "Turno (h)", "TND (h)",
                                "Disponible", "Min. programados", "Motivos"]],
                         width="stretch", hide_index=True,
                         column_config={"Disponible": st.column_config.ProgressColumn(
                             "Disponible", min_value=0, max_value=100, format="%.0f%%")})
        st.download_button("⬇️ Descargar TND día por día (CSV)",
                           tabla.drop(columns=["Descanso", "Min. registrados"])
                                .to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"TND_{label}.csv", mime="text/csv",
                           key=f"{key}_csv")


def formulario_rol_turnos(rol: pd.DataFrame):
    """Captura de excepciones de turno (vacaciones, 12 h, dobles, descansos)."""
    with st.expander("🗓️ Turnos especiales (vacaciones, 12 h, doble turno)"):
        st.caption("Por defecto cada grupo trabaja **8 h al día**. Registra aquí "
                   "solo los días distintos para que el TND sea correcto. Si te "
                   "equivocas, vuelve a registrar el mismo día y grupo: manda el último.")
        # El flag va en una llave propia: el valor de un text_input se borra
        # en cuanto el campo deja de dibujarse, y eso volvería a bloquear.
        if not st.session_state.get("rol_autorizado"):
            pwd = st.text_input("Contraseña", type="password", key="rol_pwd",
                                help="La de administrador (rol_password o mantenimiento_password).")
            if pwd:
                if verificar_password("rol", pwd) or verificar_password("mantenimiento", pwd):
                    st.session_state["rol_autorizado"] = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta.")
        else:
            caso = st.segmented_control(
                "Caso", ["Vacaciones de un grupo", "Día específico"],
                default="Vacaciones de un grupo", key="rol_caso") or "Vacaciones de un grupo"
            hoy = hoy_mx().date()
            rango = st.date_input("Del / al", value=(hoy, hoy), format="DD/MM/YYYY",
                                  key="rol_rango")
            if not (isinstance(rango, (tuple, list)) and len(rango) == 2):
                st.caption("Elige también la fecha final.")
                ini, fin = (rango[0], rango[0]) if rango else (hoy, hoy)
            else:
                ini, fin = rango
            dias = pd.date_range(ini, fin, freq="D").date

            filas = []
            if caso == "Vacaciones de un grupo":
                g_vac = st.segmented_control("Grupo de vacaciones", GRUPOS, key="rol_gvac")
                if g_vac:
                    otros = [g for g in GRUPOS if g != g_vac]
                    st.info(f"Se registrará: grupo **{g_vac} = 0 h** y grupos "
                            f"**{' y '.join(otros)} = 12 h** durante {len(dias)} día(s).")
                    for d in dias:
                        filas.append({"fecha": d, "grupo": g_vac, "horas": 0,
                                      "nota": f"Vacaciones {g_vac}"})
                        for g in otros:
                            filas.append({"fecha": d, "grupo": g, "horas": 12,
                                          "nota": f"Cubre vacaciones {g_vac}"})
            else:
                c1, c2 = st.columns(2)
                with c1:
                    g_sel = st.segmented_control("Grupo", GRUPOS, key="rol_g")
                with c2:
                    h_sel = st.segmented_control(
                        "Horas trabajadas", ["0 (no trabajó)", "8 (normal)", "12", "16 (doble)"],
                        key="rol_h")
                nota = st.text_input("Nota (opcional)", key="rol_nota")
                if g_sel and h_sel:
                    h = int(h_sel.split()[0])
                    filas = [{"fecha": d, "grupo": g_sel, "horas": h, "nota": nota}
                             for d in dias]

            if filas and st.button(f"Guardar {len(filas)} registro(s)", type="primary",
                                   key="rol_guardar"):
                try:
                    n = guardar_rol_turnos(filas)
                    st.toast(f"{n} registro(s) guardados en {settings.HOJA_ROL_TURNOS}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")

        if not rol.empty:
            st.markdown("**Excepciones registradas (últimos 60 días)**")
            lim = hoy_mx().date() - timedelta(days=60)
            v = rol[rol["fecha"] >= lim].sort_values(["fecha", "grupo"], ascending=[False, True])
            st.dataframe(v.rename(columns={"fecha": "Fecha", "grupo": "Grupo",
                                           "horas": "Horas", "nota": "Nota"}),
                         width="stretch", hide_index=True)


def _paretos_lado_a_lado(dfs: dict, colores: dict, eje: str, cat: str, key: str):
    """Un Pareto por serie (línea / grupo / empresa), uno junto al otro."""
    cols = st.columns(len(dfs))
    for col, (nombre, d) in zip(cols, dfs.items()):
        s = d.groupby(cat)["horas"].sum()
        with col:
            fig = pareto_fig(s, eje, color=colores[nombre], titulo=str(nombre), altura=380)
            if fig is None:
                st.info(f"{nombre}: sin datos.")
            else:
                st.plotly_chart(fig, width="stretch", key=f"{key}_{nombre}")
                st.caption(f"{d['horas'].sum():.1f} h · Pocos vitales: "
                           + ", ".join(map(str, vitales_80(s))))


# ===========================================================================
st.title("Pareto por área + TND")

df_raw = leer_paros()
if df_raw.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

df_raw = df_raw.copy()
df_raw["es_hijo"] = marcar_hijos(df_raw)
df_raw["fecha_ts"] = pd.to_datetime(df_raw.get("timestamp"), errors="coerce")
df_raw["h_prog"] = df_raw.get("dur_prog", "").apply(hhmm_a_horas)
df_raw["h_noprog"] = df_raw.get("dur_noprog", "").apply(hhmm_a_horas)
df_raw["horas"] = df_raw["h_prog"] + df_raw["h_noprog"]
df_raw["min_prog"] = df_raw.get("dur_prog", "").apply(_to_min)
for c in ("area", "linea", "motivo", "turno", "equipo"):
    df_raw[c] = df_raw.get(c, "").fillna("").astype(str).str.strip()
df_raw["area_key"] = df_raw["area"].apply(_area_key)

tipo_por_motivo = cargar_catalogos().get("tipo_por_motivo", {})
tipo_norm = {_norm(k): v for k, v in tipo_por_motivo.items()}
df_raw["tipo"] = df_raw["motivo"].map(lambda m: tipo_norm.get(_norm(m), settings.NO_PROGRAMADO))

ini_col = df_raw.get("ini_prog", pd.Series("", index=df_raw.index)).astype(str).str.strip()
df_raw["hora_ini_efectiva"] = ini_col.where(ini_col != "", df_raw.get("ini_noprog", ""))
df_raw["fecha_turno"] = df_raw.apply(
    lambda r: _fecha_turno(r["fecha_ts"], r["hora_ini_efectiva"]), axis=1)

df_areas = df_raw[df_raw["area_key"].notna()].copy()
if df_areas.empty:
    st.warning("No se encontraron registros en Molienda, Extrusión o Envasado/Empaque. "
               "Revisa que el campo ÁREA use esos nombres.")
    st.stop()

tab_sup, tab_mtto = st.tabs(["👷 Supervisores", "🔧 Mantenimiento"])

# ===========================================================================
# PESTAÑA SUPERVISORES
# ===========================================================================
with tab_sup:
    st.caption("Pareto de motivos no programados por área, línea y grupo, con el "
               "TND del mismo periodo.")

    ini_s, fin_s, etq_s = selector_periodo(df_areas["fecha_ts"], key="sup",
                                           default="Este mes")
    f1, f2, f3 = st.columns(3)
    with f1:
        area_sel = st.selectbox("Área", ["Todas"] + list(LABEL_TO_KEY), key="sup_area")
    with f2:
        linea_sel = st.segmented_control("Línea", ["Todas"] + LINEAS,
                                         default="Todas", key="sup_linea") or "Todas"
    with f3:
        grupo_sel = st.segmented_control("Grupo", ["Todos"] + GRUPOS,
                                         default="Todos", key="sup_grupo") or "Todos"
    vista = st.segmented_control("Vista", ["Normal", "Comparar líneas", "Comparar grupos"],
                                 default="Normal", key="sup_vista") or "Normal"

    d_sup = filtrar_fechas(df_areas, "fecha_ts", ini_s, fin_s)
    if area_sel != "Todas":
        d_sup = d_sup[d_sup["area_key"] == LABEL_TO_KEY[area_sel]]
    if vista != "Comparar líneas":
        d_sup = filtrar_linea(d_sup, linea_sel)
    if vista != "Comparar grupos":
        d_sup = filtrar_grupo(d_sup, grupo_sel)

    if vista == "Comparar líneas" and linea_sel != "Todas":
        st.caption("Comparando ambas líneas (el filtro de línea no aplica en esta vista).")
    if vista == "Comparar grupos" and grupo_sel != "Todos":
        st.caption("Comparando los 3 grupos (el filtro de grupo no aplica en esta vista).")

    d_np = d_sup[(d_sup["tipo"] == settings.NO_PROGRAMADO) & (d_sup["horas"] > 0)]

    st.divider()
    st.subheader(f"Pareto de motivos — {etq_s}")

    if d_np.empty:
        st.warning("No hay paros no programados para este filtro.")
    elif vista == "Normal":
        s = d_np.groupby("motivo")["horas"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Paros no programados", int((~d_np["es_hijo"]).sum()))
        c2.metric("Horas perdidas", f"{d_np['horas'].sum():.1f} h")
        c3.metric("Motivos que causan el 80%", len(vitales_80(s)))
        st.plotly_chart(pareto_fig(s, "Motivo"), width="stretch", key="sup_par")
        st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, vitales_80(s))))
    elif vista == "Comparar líneas":
        dc = expandir_por_linea(d_np)
        cols = st.columns(2)
        for col, ln in zip(cols, LINEAS):
            d = dc[dc["linea_cmp"] == ln]
            col.metric(ln, f"{d['horas'].sum():.1f} h",
                       help=f"{int((~d['es_hijo']).sum())} paros no programados")
        st.plotly_chart(barras_comparadas(dc, "motivo", "linea_cmp",
                                          {k: COLOR_LINEA[k] for k in LINEAS},
                                          "Horas por motivo — Línea 1 vs Línea 2", "Motivo",
                                          top=12), width="stretch", key="sup_cmp_ln")
        _paretos_lado_a_lado({ln: dc[dc["linea_cmp"] == ln] for ln in LINEAS},
                             COLOR_LINEA, "Motivo", "motivo", key="sup_pln")
        st.caption(f"Los paros de «{LINEA_AMBAS}» cuentan en las dos líneas.")
    else:  # Comparar grupos
        dg = d_np[d_np["turno"].isin(GRUPOS)]
        cols = st.columns(3)
        for col, g in zip(cols, GRUPOS):
            d = dg[dg["turno"] == g]
            col.metric(f"Grupo {g}", f"{d['horas'].sum():.1f} h",
                       help=f"{int((~d['es_hijo']).sum())} paros no programados")
        st.plotly_chart(barras_comparadas(dg, "motivo", "turno", COLOR_GRUPO,
                                          "Horas por motivo — por grupo", "Motivo",
                                          top=12), width="stretch", key="sup_cmp_gr")
        tabs_g = st.tabs([f"Pareto grupo {g}" for g in GRUPOS])
        for t, g in zip(tabs_g, GRUPOS):
            with t:
                s = dg[dg["turno"] == g].groupby("motivo")["horas"].sum()
                fig = pareto_fig(s, "Motivo", color=COLOR_GRUPO[g])
                if fig is None:
                    st.info(f"Grupo {g}: sin paros no programados.")
                else:
                    st.plotly_chart(fig, width="stretch", key=f"sup_pg_{g}")
                    st.caption("**Pocos vitales:** " + ", ".join(map(str, vitales_80(s))))

    # --- TND -----------------------------------------------------------
    st.divider()
    st.subheader(f"TND — {etq_s}")
    st.caption("Horas disponibles por turno: horas trabajadas por el grupo menos "
               "paros programados. Pasa el cursor sobre una celda para ver el motivo.")

    base = df_areas[df_areas["fecha_turno"].notna()]
    ft = pd.to_datetime(base["fecha_turno"])
    d_prog = base[(ft >= pd.Timestamp(ini_s)) & (ft <= pd.Timestamp(fin_s))
                  & (base["tipo"] == settings.PROGRAMADO)]
    grupos_tnd = GRUPOS if (grupo_sel == "Todos" or vista == "Comparar grupos") else [grupo_sel]
    lineas_tnd = LINEAS if (linea_sel == "Todas" or vista == "Comparar líneas") else [linea_sel]
    areas_tnd = [LABEL_TO_KEY[area_sel]] if area_sel != "Todas" else list(AREAS_OBJETIVO)

    if (fin_s - ini_s).days > 62:
        st.info("Periodo largo: el mapa de calor puede verse comprimido. "
                "Usa «Este mes» o un rango para ver el detalle por día.")
    rol = leer_rol_turnos()
    bases = base_turnos(rol)
    for ak in areas_tnd:
        mostrar_tnd(d_prog[d_prog["area_key"] == ak], ak, ini_s, fin_s,
                    grupos_tnd, lineas_tnd, key=f"tnd_{ak}", bases=bases)

    formulario_rol_turnos(rol)

# ===========================================================================
# PESTAÑA MANTENIMIENTO
# ===========================================================================
with tab_mtto:
    st.caption("Pareto por equipo de los paros que requirieron apoyo externo. "
               "Los tramos de paros multi-turno se suman a su padre (tiempo total "
               "del evento). Un paro «AMBOS» cuenta para RSI y para STEO.")

    ini_m, fin_m, etq_m = selector_periodo(df_areas["fecha_ts"], key="mtto",
                                           default="Este mes")
    m1, m2 = st.columns(2)
    with m1:
        area_m = st.selectbox("Área", ["Todas"] + list(LABEL_TO_KEY), key="mtto_area")
    with m2:
        empresa = st.segmented_control("Empresa", ["Todas", "RSI", "STEO", "Comparar"],
                                       default="Todas", key="mtto_emp") or "Todas"

    d_m = filtrar_fechas(df_areas, "fecha_ts", ini_m, fin_m).copy()
    if area_m != "Todas":
        d_m = d_m[d_m["area_key"] == LABEL_TO_KEY[area_m]]
    d_m["apoyo"] = d_m.get("necesita_acr", "").fillna("").astype(str).str.strip().str.upper()
    d_m = d_m[d_m["apoyo"].isin({"RSI", "STEO", "AMBOS"})]

    # Hijos -> se suman al padre
    hijos_m = d_m[d_m["es_hijo"]]
    d_m = d_m[~d_m["es_hijo"]].copy()
    if not hijos_m.empty and "paro_padre" in hijos_m.columns:
        suma = hijos_m.groupby(hijos_m["paro_padre"].astype(str).str.strip())["horas"].sum()
        d_m["horas"] = d_m["horas"] + d_m["id_paro"].astype(str).str.strip().map(suma).fillna(0)
    d_m = d_m[d_m["horas"] > 0]
    d_m["equipo"] = d_m["equipo"].where(d_m["equipo"] != "", "Sin equipo")

    def _de_empresa(emp: str) -> pd.DataFrame:
        return d_m[d_m["apoyo"].isin({emp, "AMBOS"})]

    st.divider()
    st.subheader(f"Pareto por equipo — {etq_m}")

    if d_m.empty:
        st.warning("No hay paros con apoyo externo para este filtro.")
    elif empresa == "Comparar":
        por_emp = {e: _de_empresa(e) for e in ("RSI", "STEO")}
        cols = st.columns(2)
        for col, (e, d) in zip(cols, por_emp.items()):
            col.metric(e, f"{d['horas'].sum():.1f} h", help=f"{len(d)} eventos")
        dc = pd.concat([d.assign(empresa=e) for e, d in por_emp.items()], ignore_index=True)
        st.plotly_chart(barras_comparadas(dc, "equipo", "empresa", COLOR_EMPRESA,
                                          "Horas por equipo — RSI vs STEO", "Equipo"),
                        width="stretch", key="mtto_cmp")
        _paretos_lado_a_lado(por_emp, COLOR_EMPRESA, "Equipo", "equipo", key="mtto_p")
    else:
        d = d_m if empresa == "Todas" else _de_empresa(empresa)
        if d.empty:
            st.warning(f"No hay paros con apoyo de {empresa} en este periodo.")
        else:
            s = d.groupby("equipo")["horas"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Eventos con apoyo", len(d))
            c2.metric("Horas totales", f"{d['horas'].sum():.1f} h")
            c3.metric("Equipos que causan el 80%", len(vitales_80(s)))
            color = COLOR_EMPRESA.get(empresa, "#2563EB")
            st.plotly_chart(pareto_fig(s, "Equipo", color=color), width="stretch",
                            key="mtto_par")
            st.caption("**Pocos vitales (≈80%):** " + ", ".join(map(str, vitales_80(s))))
            if empresa == "Todas":
                rep = d["apoyo"].value_counts()
                st.caption(" · ".join(f"{k}: {v}" for k, v in rep.items()))