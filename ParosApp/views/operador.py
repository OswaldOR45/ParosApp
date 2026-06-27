"""
VISTA 1 — OPERADOR (Registro de paro post-evento)
=================================================
- Cero st.selectbox: segmented_control y pills (uso con guantes).
- TIMESTAMP oculto (se genera al guardar).
- tipo_paro DERIVADO del motivo -> manda las horas a las columnas
  PROGRAMADO o NO PROGRAMADO automáticamente.
- Botón del director: "¿Necesita ACR? SÍ / NO".
- La Orden de Trabajo NO se captura aquí (la asigna Mantenimiento).
- Duración en formato H:MM.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from config import settings
from data.sheets import cargar_catalogos, guardar_paro
from utils.tiempo import duracion_hhmm, total_minutos

TZ = ZoneInfo("America/Mexico_City")

def ahora_mx() -> datetime:
    return datetime.now(TZ)

st.markdown(
    """
    <style>
      div[data-testid="stButton"] button { min-height: 3rem; font-size: 1.1rem; }
      .stButton > button { font-weight: 600; }
      div[data-testid="stPills"] button,
      div[data-testid="stSegmentedControl"] button {
          min-height: 2.7rem; font-size: 1.02rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if "tg_debug" in st.session_state:
    st.error(st.session_state["tg_debug"])

st.title("Registrar Paro")

cat = cargar_catalogos()

if "v" not in st.session_state:
    st.session_state.v = 0
v = st.session_state.v

# --- 1. Turno --------------------------------------------------------------
st.subheader("1 · Turno")
turno = st.segmented_control("Turno", cat["turnos"], key=f"turno_{v}",
                             label_visibility="collapsed")

# --- 2. Ubicación ----------------------------------------------------------
st.subheader("2 · Línea")
linea = st.pills("Línea", cat["lineas"], key=f"linea_{v}",
                 label_visibility="collapsed")

st.subheader("3 · Área")
area = st.pills("Área", cat["areas"], key=f"area_{v}",
                label_visibility="collapsed")

st.subheader("4 · Equipo / Área afectada")
equipo = st.pills("Equipo", cat["equipos"], key=f"equipo_{v}",
                  label_visibility="collapsed")

# --- 5. Tiempos (24h) ------------------------------------------------------
st.subheader("5 · ¿Cuándo? (24h)")
_ahora = ahora_mx()
fecha = st.date_input("Fecha", value=_ahora.date(), key=f"fecha_{v}")
col_i, col_f = st.columns(2)
with col_i:
    hora_inicio = st.time_input("Inicio",
        value=_ahora.time().replace(second=0, microsecond=0),
        key=f"hi_{v}", step=60)
with col_f:
    hora_fin = st.time_input("Fin",
        value=_ahora.time().replace(second=0, microsecond=0),
        key=f"hf_{v}", step=60)

dur_txt = duracion_hhmm(fecha, hora_inicio, hora_fin)
st.metric("Duración", f"{dur_txt} h")

# --- 6. Motivo + tipo derivado --------------------------------------------
st.subheader("6 · Motivo del paro")
motivo = st.pills("Motivo", cat["motivos"], key=f"motivo_{v}",
                  label_visibility="collapsed")
descrip_paro = ""
tipo_paro = ""
if motivo:
    tipo_paro = cat["tipo_por_motivo"].get(motivo, "")
    descrip_paro = cat["descrip_motivo"].get(motivo, "")
    if tipo_paro == settings.PROGRAMADO:
        st.info(f"Paro **{tipo_paro}** (clasificado automáticamente)", icon="🗓️")
        st.info(f"Descripcion -> {descrip_paro}", icon="🔍")
    else:
        st.warning(f"Paro **{tipo_paro}** (clasificado automáticamente)", icon="⚠️")
        st.info(f"Descripcion -> {descrip_paro}", icon="🔍")

# --- 7. Apoyo externo (ACR) -----------------------------------------------
# A quién llamó el operador. "NO" = paro operativo sin intervención técnica.
# Cualquiera de las primeras tres manda el paro a la cola de Mantenimiento.
st.subheader("7 · ¿Solicitaste apoyo externo?")
necesita_acr = st.segmented_control(
    "Apoyo externo",
    ["RSI", "STEO", "AMBOS", "NO"],
    key=f"acr_{v}",
    label_visibility="collapsed",
    help="Indica a quién llamaste. Si no hubo intervención técnica, marca NO.",
)

# --- 8. Descripción (opcional) --------------------------------------------
st.subheader("8 · Descripción (opcional)")
descripcion = st.text_area("Descripción", key=f"desc_{v}", height=80,
                           label_visibility="collapsed",
                           placeholder="Síntoma o detalle del paro")

st.divider()

if st.button("Guardar Paro", type="primary", use_container_width=True):
    errores = []
    if not turno:   errores.append("Selecciona el **turno**.")
    if not linea:   errores.append("Selecciona la **línea**.")
    if not area:    errores.append("Selecciona el **área**.")
    if not equipo:  errores.append("Selecciona el **equipo**.")
    if not motivo:  errores.append("Selecciona el **motivo**.")
    if not necesita_acr: errores.append("Indica si **solicitaste apoyo externo**.")
    if total_minutos(fecha, hora_inicio, hora_fin) <= 0:
        errores.append("Revisa las horas: la duración debe ser mayor a 0.")

    if errores:
        for e in errores:
            st.error(e, icon="🚫")
    else:
        ahora = ahora_mx()
        hi = hora_inicio.strftime("%H:%M")
        hf = hora_fin.strftime("%H:%M")
        es_prog = tipo_paro == settings.PROGRAMADO

        registro = {
            "timestamp": ahora.strftime("%Y-%m-%d %H:%M:%S"),
            "area": area,
            "turno": turno,
            "linea": linea,
            "equipo": equipo,
            "motivo": motivo,
            "descripcion": descripcion.strip(),
            "ini_prog":   hi if es_prog else "",
            "fin_prog":   hf if es_prog else "",
            "dur_prog":   dur_txt if es_prog else "",
            "ini_noprog": "" if es_prog else hi,
            "fin_noprog": "" if es_prog else hf,
            "dur_noprog": "" if es_prog else dur_txt,
            "id_paro": f"P-{ahora:%Y%m%d-%H%M%S}",
            "necesita_acr": necesita_acr,
            "orden_trabajo": "",
            "causa_raiz": "",
            "componente": "",
            "accion": "",
            "refaccion": "",
        }
        try:
            guardar_paro(registro)
            st.session_state.v += 1
            st.toast(f"Paro guardado · {dur_txt} h", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo guardar. Detalle: {e}")