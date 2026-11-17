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
- Paros multi-turno: si el paro continúa al siguiente turno, el supervisor
  marca "Continúa" y el sistema calcula el fin automático del intervalo.
  Los siguientes supervisores cierran o extienden desde la tabla de paros
  en curso que aparece al inicio de esta vista.
"""
from datetime import datetime, time as dtime

import pandas as pd
import streamlit as st

from config import settings
from data.sheets import (cargar_catalogos, guardar_paro, actualizar_paro,
                          leer_paros, leer_paros_en_curso, leer_hijos_de_paro,
                          cerrar_tramo_en_curso, guardar_hijo_en_curso)
from utils.tiempo import (duracion_hhmm, total_minutos, ahora_mx,
                           fin_de_turno_actual, sumar_duraciones_hhmm)

def _inicio_intervalo_actual(ahora: datetime) -> dtime:
    """Devuelve la hora de INICIO del intervalo de turno en que cae `ahora`."""
    t = ahora.time()
    for ini_str, fin_str in settings.INTERVALOS_TURNO:
        h_ini, m_ini = map(int, ini_str.split(":"))
        h_fin, m_fin = map(int, fin_str.split(":"))
        t_ini = dtime(h_ini, m_ini)
        t_fin = dtime(h_fin, m_fin)
        if t_ini < t_fin:
            if t_ini <= t < t_fin:
                return t_ini
        else:
            if t >= t_ini or t < t_fin:
                return t_ini
    return dtime(5, 0)

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

st.title("Registrar Paro")

cat = cargar_catalogos()

if "v" not in st.session_state:
    st.session_state.v = 0
v = st.session_state.v

# ===========================================================================
# SECCIÓN: PAROS EN CURSO (multi-turno)
# ---------------------------------------------------------------------------
# Modelo de datos:
#   · PADRE  = primer tramo. Es el ÚNICO que lleva PARO_EN_CURSO = SÍ mientras
#              el evento sigue abierto.
#   · HIJOS  = un registro por cada turno adicional, SIEMPRE completo
#              (inicio, fin y duración). Nunca se reescribe un tramo anterior.
#   · Inicio de cada tramo nuevo = FIN del último tramo registrado.
# Compatibilidad: si el último hijo quedó abierto (esquema anterior, sin fin),
# se cierra ese hijo en lugar de crear uno nuevo.
# ===========================================================================
def _parse_hora(valor):
    """'05:00' / '5:00' / '05:00:00' -> time | None."""
    s = str(valor or "").strip()
    if ":" not in s:
        return None
    try:
        h, m = map(int, s.split(":")[:2])
        return dtime(h % 24, m)
    except ValueError:
        return None


paros_en_curso = leer_paros_en_curso()

if not paros_en_curso.empty:
    # Descartar filas sin ID (registros corruptos o borrados parcialmente)
    paros_en_curso = paros_en_curso[
        paros_en_curso["id_paro"].fillna("").astype(str).str.strip() != ""
    ]

if not paros_en_curso.empty:
    col_titulo, col_btn = st.columns([5, 1])
    with col_titulo:
        st.warning("⚠️ Hay paros activos del turno anterior. Revísalos antes de "
                   "registrar uno nuevo.", icon="🔄")
    with col_btn:
        if st.button("🔄 Actualizar", key="btn_refresh_ec", use_container_width=True,
                     help="Fuerza la recarga desde Google Sheets"):
            leer_paros_en_curso.clear()
            leer_hijos_de_paro.clear()
            leer_paros.clear()
            st.rerun()
    st.subheader("Paros en curso")

    cols_vista = [c for c in ["id_paro", "turno", "linea", "area", "equipo",
                              "motivo", "ini_noprog", "ini_prog"]
                  if c in paros_en_curso.columns]
    st.dataframe(paros_en_curso[cols_vista], use_container_width=True, hide_index=True)

    paro_sel = st.selectbox("Selecciona el paro a gestionar",
                            paros_en_curso["id_paro"].tolist(),
                            key="paro_en_curso_sel")
    fila_ec = paros_en_curso[paros_en_curso["id_paro"] == paro_sel].iloc[0]

    es_prog = str(fila_ec.get("ini_prog", "")).strip() != ""
    suf = "prog" if es_prog else "noprog"

    hijos = leer_hijos_de_paro(paro_sel)
    todos_tramos = [fila_ec] + [hijos.iloc[i] for i in range(len(hijos))]
    duraciones = [str(tr.get(f"dur_{suf}") or "").strip() for tr in todos_tramos]
    duraciones = [d for d in duraciones if d]
    dur_total = sumar_duraciones_hhmm(duraciones)

    # --- ¿Dónde arranca el tramo que falta registrar? ----------------------
    ultimo = todos_tramos[-1]
    ultimo_id = str(ultimo.get("id_paro", ""))
    ultimo_ini = _parse_hora(ultimo.get(f"ini_{suf}"))
    ultimo_fin = _parse_hora(ultimo.get(f"fin_{suf}"))
    tramo_abierto = ultimo_fin is None and ultimo_id != str(paro_sel)  # legacy
    ini_tramo = ultimo_ini if tramo_abierto else ultimo_fin

    ahora_ec = ahora_mx()
    fin_turno_actual = fin_de_turno_actual(ahora_ec)
    # Si el último tramo ya termina al cierre del turno actual, este turno
    # YA quedó registrado (lo registró el grupo anterior o tú mismo).
    turno_ya_cubierto = (not tramo_abierto) and ultimo_fin == fin_turno_actual

    with st.expander(f"Ver tramos registrados · Duración acumulada: {dur_total} h",
                     expanded=False):
        st.dataframe(pd.DataFrame([{
            "Grupo": tr.get("turno", "—"),
            "Inicio": str(tr.get(f"ini_{suf}") or "—"),
            "Fin": str(tr.get(f"fin_{suf}") or "⏳ en curso"),
            "Duración": str(tr.get(f"dur_{suf}") or "—"),
            "Notas": str(tr.get("descripcion", "") or ""),
        } for tr in todos_tramos]), use_container_width=True, hide_index=True)

    if ini_tramo is None:
        st.error("No pude leer la hora del último tramo de este paro. "
                 "Corrígela en la hoja (formato HH:MM) y pulsa 🔄 Actualizar.")
    else:
        st.markdown("**¿Qué ocurre con este paro?**")
        accion_ec = st.segmented_control(
            "Acción", ["Continúa al siguiente turno", "Finalizó en mi turno"],
            key="accion_en_curso", label_visibility="collapsed")

        if accion_ec:
            grupo_ec = st.segmented_control("Tu grupo", cat["turnos"], key="grupo_ec",
                                            help="Grupo que atiende este tramo")

            def _registro_tramo(ini_t: dtime, fin_t: dtime, dur_t: str) -> dict:
                ts = ahora_mx()
                return {
                    "timestamp":       ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "area":            fila_ec.get("area", ""),
                    "turno":           grupo_ec,
                    "linea":           fila_ec.get("linea", ""),
                    "equipo":          fila_ec.get("equipo", ""),
                    "motivo":          fila_ec.get("motivo", ""),
                    "descripcion":     fila_ec.get("descripcion", ""),
                    "ini_prog":        ini_t.strftime("%H:%M") if es_prog else "",
                    "fin_prog":        fin_t.strftime("%H:%M") if es_prog else "",
                    "dur_prog":        dur_t if es_prog else "",
                    "ini_noprog":      "" if es_prog else ini_t.strftime("%H:%M"),
                    "fin_noprog":      "" if es_prog else fin_t.strftime("%H:%M"),
                    "dur_noprog":      "" if es_prog else dur_t,
                    "id_paro":         f"P-{ts:%Y%m%d-%H%M%S}",
                    "necesita_acr":    fila_ec.get("necesita_acr", "NO"),
                    "paro_padre":      paro_sel,
                    "es_continuacion": "SÍ",
                    "paro_en_curso":   "",   # el tramo hijo siempre nace cerrado
                }

            def _limpiar_y_recargar():
                leer_paros_en_curso.clear()
                leer_hijos_de_paro.clear()
                leer_paros.clear()

            fecha_ref = ahora_ec.date()  # solo para el cálculo con cruce de medianoche

            # ---------------- FINALIZÓ ----------------
            if accion_ec == "Finalizó en mi turno":
                st.caption("Indica la hora exacta en que el paro terminó.")
                hora_fin_ec = st.time_input("Hora de fin real", value=None,
                                            key="hora_fin_ec", step=60)

                if turno_ya_cubierto:
                    # Este turno ya tiene tramo (terminaba al cierre del turno):
                    # se AJUSTA ese tramo al fin real, no se crea otro.
                    ini_calc = ultimo_ini
                    st.info("Tu turno ya tiene un tramo registrado hasta "
                            f"{ultimo_fin:%H:%M}; se ajustará a la hora real de fin.",
                            icon="✏️")
                else:
                    ini_calc = ini_tramo

                if hora_fin_ec and grupo_ec and ini_calc:
                    dur_ec = duracion_hhmm(fecha_ref, ini_calc, hora_fin_ec)
                    base = duraciones[:-1] if turno_ya_cubierto else duraciones
                    if tramo_abierto:
                        base = duraciones  # el abierto no tiene duración aún
                    total_ev = sumar_duraciones_hhmm(base + [dur_ec])
                    m1, m2 = st.columns(2)
                    m1.metric("Duración de este tramo", f"{dur_ec} h")
                    m2.metric("Duración total del evento", f"{total_ev} h")

                    if total_minutos(fecha_ref, ini_calc, hora_fin_ec) > 8 * 60 + 30:
                        st.warning("El tramo supera 8.5 h. Si el paro pasó por más "
                                   "de un turno sin registrarse, usa «Continúa» "
                                   "por cada turno faltante antes de finalizar.")

                    if total_minutos(fecha_ref, ini_calc, hora_fin_ec) <= 0:
                        st.error("La hora de fin debe ser distinta a la de inicio "
                                 f"del tramo ({ini_calc:%H:%M}).")
                    elif st.button("Cerrar paro", type="primary",
                                   use_container_width=True, key="btn_cerrar_ec"):
                        try:
                            hf = hora_fin_ec.strftime("%H:%M")
                            if tramo_abierto:
                                cerrar_tramo_en_curso(ultimo_id, hf, dur_ec,
                                                      grupo_ec, continua=False)
                            elif turno_ya_cubierto:
                                actualizar_paro(ultimo_id, {
                                    f"fin_{suf}": hf, f"dur_{suf}": dur_ec})
                            else:
                                guardar_hijo_en_curso(
                                    _registro_tramo(ini_calc, hora_fin_ec, dur_ec))
                            actualizar_paro(paro_sel, {"paro_en_curso": ""})
                            _limpiar_y_recargar()
                            st.toast(f"Paro {paro_sel} cerrado · Duración total: "
                                     f"{total_ev} h", icon="✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al cerrar el paro: {e}")

            # ---------------- CONTINÚA ----------------
            else:
                if turno_ya_cubierto:
                    st.info("Este turno ya quedó registrado hasta "
                            f"{ultimo_fin:%H:%M}. El siguiente grupo debe "
                            "actualizar el paro cuando entre.", icon="✅")
                else:
                    fin_turno = fin_de_turno_actual(datetime.combine(fecha_ref, ini_tramo))
                    dur_ec = duracion_hhmm(fecha_ref, ini_tramo, fin_turno)
                    st.caption(f"Se registrará el tramo **{ini_tramo:%H:%M} → "
                               f"{fin_turno:%H:%M}** y el paro seguirá activo.")
                    st.metric("Duración de este tramo", f"{dur_ec} h")

                    if st.button("Registrar tramo y continuar", type="primary",
                                 use_container_width=True, key="btn_continuar_ec"):
                        if not grupo_ec:
                            st.error("Selecciona tu grupo antes de continuar.")
                        else:
                            try:
                                if tramo_abierto:
                                    cerrar_tramo_en_curso(
                                        ultimo_id, fin_turno.strftime("%H:%M"),
                                        dur_ec, grupo_ec, continua=True)
                                else:
                                    guardar_hijo_en_curso(
                                        _registro_tramo(ini_tramo, fin_turno, dur_ec))
                                _limpiar_y_recargar()
                                st.toast("Tramo registrado · Paro activo para el "
                                         "siguiente turno", icon="🔄")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al registrar el tramo: {e}")

    st.divider()

# --- 1. Turno --------------------------------------------------------------
st.subheader("1 · Turno")
turno = st.segmented_control("Turno", cat["turnos"], key=f"turno_{v}",
                             label_visibility="collapsed")

# --- 2. Ubicación ----------------------------------------------------------
st.subheader("2 · Línea")
linea = st.pills("Línea", cat["lineas"], key=f"linea_{v}",
                 label_visibility="collapsed")

st.subheader("3 · Área donde se originó el paro")
st.caption("¿Dónde está la CAUSA? Ej.: no hay harina porque el molino falló → MOLIENDA.")
area = st.pills("Área", cat["areas"], key=f"area_{v}",
                label_visibility="collapsed")
if area and cat.get("descrip_area", {}).get(area):
    st.caption(f"📍 **{area}:** {cat['descrip_area'][area]}")

st.subheader("4 · Equipo que se detuvo")
st.caption("¿Qué dejó de producir? Normalmente el Extrusor (la línea).")
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

# --- ¿El paro continúa al siguiente turno? --------------------------------
st.subheader("¿El paro continúa al siguiente turno?")
extiende = st.segmented_control(
    "Extensión",
    ["No, finaliza en mi turno", "Sí, continúa al siguiente turno"],
    key=f"extiende_{v}",
    label_visibility="collapsed",
    help="Si el paro no terminará antes del cambio de turno, selecciona 'Sí'.",
)

if extiende == "Sí, continúa al siguiente turno":
    # Usamos hora_inicio (lo que el supervisor capturó) para determinar
    # a qué intervalo de turno pertenece el paro, no la hora actual del render.
    # Esto evita el bug donde la página se abre en un turno y se guarda en otro.
    from datetime import datetime as _dt
    _dt_inicio = _dt.combine(fecha, hora_inicio)
    fin_turno_auto = fin_de_turno_actual(_dt_inicio)
    st.info(
        f"La hora de fin se calculará automáticamente como el límite del turno "
        f"en que inició el paro: **{fin_turno_auto.strftime('%H:%M')}**",
        icon="🔄",
    )
    hora_fin_efectiva = fin_turno_auto
    dur_txt = duracion_hhmm(fecha, hora_inicio, hora_fin_efectiva)
else:
    hora_fin_efectiva = hora_fin
    dur_txt = duracion_hhmm(fecha, hora_inicio, hora_fin_efectiva)

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
    if not turno:        errores.append("Selecciona el **turno**.")
    if not linea:        errores.append("Selecciona la **línea**.")
    if not area:         errores.append("Selecciona el **área**.")
    if not equipo:       errores.append("Selecciona el **equipo**.")
    if not motivo:       errores.append("Selecciona el **motivo**.")
    if not necesita_acr: errores.append("Indica si **solicitaste apoyo externo**.")
    if not extiende:     errores.append("Indica si el paro **continúa al siguiente turno**.")
    if extiende != "Sí, continúa al siguiente turno" and total_minutos(fecha, hora_inicio, hora_fin_efectiva) <= 0:
        errores.append("Revisa las horas: la duración debe ser mayor a 0.")

    if errores:
        for e in errores:
            st.error(e, icon="🚫")
    else:
        ahora = ahora_mx()
        hi  = hora_inicio.strftime("%H:%M")
        hf  = hora_fin_efectiva.strftime("%H:%M")
        es_prog    = tipo_paro == settings.PROGRAMADO
        en_curso   = extiende == "Sí, continúa al siguiente turno"

        registro = {
            "timestamp":    ahora.strftime("%Y-%m-%d %H:%M:%S"),
            "area":         area,
            "turno":        turno,
            "linea":        linea,
            "equipo":       equipo,
            "motivo":       motivo,
            "descripcion":  descripcion.strip(),
            "ini_prog":     hi if es_prog else "",
            "fin_prog":     hf if es_prog else "",
            "dur_prog":     dur_txt if es_prog else "",
            "ini_noprog":   "" if es_prog else hi,
            "fin_noprog":   "" if es_prog else hf,
            "dur_noprog":   "" if es_prog else dur_txt,
            "id_paro":      f"P-{ahora:%Y%m%d-%H%M%S}",
            "necesita_acr": necesita_acr,
            "orden_trabajo": "",
            "causa_raiz":   "",
            "componente":   "",
            "accion":       "",
            "refaccion":    "",
            # Campos multi-turno
            "paro_padre":       "",
            "es_continuacion":  "",
            "paro_en_curso":    "SÍ" if en_curso else "",
        }
        try:
            guardar_paro(registro)
            st.session_state.v += 1
            if en_curso:
                st.toast(f"Paro guardado · Tramo {dur_txt} h · Activo para el siguiente turno", icon="🔄")
            else:
                st.toast(f"Paro guardado · {dur_txt} h", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo guardar. Detalle: {e}")