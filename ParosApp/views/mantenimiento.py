"""
VISTA 2 — MANTENIMIENTO (Complementar paro)
Pendientes = paros con ¿NECESITA ACR? != NO, y SIN cierre en ACRS para la
empresa actual. Un paro "AMBOS" queda pendiente para RSI hasta que RSI
cierre su parte, y pendiente para STEO hasta que STEO cierre la suya,
de forma independiente.
Orden de Trabajo es OPCIONAL (hay paros sin orden de mtto).
Aquí SÍ se permite selectbox: es para técnicos, no para piso.
"""
from datetime import date as _date, datetime as _datetime

import pandas as pd
import streamlit as st

from data.sheets import (leer_paros, leer_acrs, guardar_acr, cargar_catalogos,
                         leer_componentes, agregar_componente)
from utils.auth import requiere_empresa, verificar_password
from utils.tiempo import duracion_hhmm, total_minutos

# Pide contraseña antes de mostrar o modificar cualquier dato.
# Cada empresa entra con su contraseña y solo ve los paros que le tocan
# (RSI -> RSI+AMBOS, STEO -> STEO+AMBOS, ADMIN -> todo).
EMPRESA = requiere_empresa()

st.title("Mantenimiento · Completar paros")

df = leer_paros()
if df.empty:
    st.info("Aún no hay paros registrados.")
    st.stop()

df = df.copy()
acrs = leer_acrs()  # historial de cierres por empresa

# Fecha del paro a partir del TIMESTAMP (momento de registro).
if "timestamp" in df.columns:
    df["fecha"] = (pd.to_datetime(df["timestamp"], errors="coerce")
                   .dt.strftime("%Y-%m-%d").fillna(""))

acr = df.get("necesita_acr", "").fillna("").astype(str).str.strip().str.upper()

# Valores que mandan el paro a la cola de Mantenimiento:
#   - "SI"/"SÍ"            -> paros antiguos (esquema previo a Ola 1)
#   - "RSI"/"STEO"/"AMBOS" -> nuevos: a quién llamó el operador
# "NO" o cualquier otra cosa queda fuera (paro operativo sin intervención).
LEGACY = {"SI", "SÍ"}
if EMPRESA == "RSI":
    VISIBLES = {"RSI", "AMBOS"} | LEGACY
elif EMPRESA == "STEO":
    VISIBLES = {"STEO", "AMBOS"} | LEGACY
else:  # ADMIN
    VISIBLES = {"RSI", "STEO", "AMBOS"} | LEGACY

# --- Pendientes: cruce con ACRS --------------------------------------------
# Un paro está PENDIENTE para una empresa si no tiene fila en ACRS para esa
# combinación (id_paro, empresa). ADMIN ve pendiente si falta CUALQUIERA de
# las empresas que le tocan (para que pueda cerrar lo que sea que falte).
if not acrs.empty and "id_paro" in acrs.columns and "empresa" in acrs.columns:
    cerrados_set = set(zip(acrs["id_paro"].astype(str), acrs["empresa"].astype(str).str.upper()))
else:
    cerrados_set = set()

def _falta_cierre(row) -> bool:
    pid = str(row.get("id_paro", ""))
    apoyo = str(row.get("necesita_acr", "")).strip().upper()

    if EMPRESA in ("RSI", "STEO"):
        return (pid, EMPRESA) not in cerrados_set

    # ADMIN: pendiente si falta el cierre de cualquier empresa involucrada
    if apoyo == "AMBOS":
        return (pid, "RSI") not in cerrados_set or (pid, "STEO") not in cerrados_set
    elif apoyo in ("RSI", "STEO"):
        return (pid, apoyo) not in cerrados_set
    else:  # legacy SI/SÍ -> no sabemos quién, basta con que exista 1 cierre
        return not any(pid == c[0] for c in cerrados_set)

mask_visible = acr.isin(VISIBLES)
df_visible = df[mask_visible].copy()
pendientes = df_visible[df_visible.apply(_falta_cierre, axis=1)]

etiqueta = "todas las empresas" if EMPRESA == "ADMIN" else EMPRESA
st.subheader(f"Paros pendientes · {etiqueta} ({len(pendientes)})")

cols_vista = [c for c in ["fecha", "id_paro", "turno", "linea", "area", "equipo",
                          "motivo", "necesita_acr", "descripcion"]
              if c in pendientes.columns]
st.dataframe(
    pendientes[cols_vista],
    use_container_width=True,
    hide_index=True,
    column_config={
        "fecha": st.column_config.TextColumn("Fecha"),
        "necesita_acr": st.column_config.TextColumn("Apoyo solicitado"),
    },
)

if pendientes.empty:
    st.success("No hay paros pendientes de causa raíz.")
    st.stop()

st.divider()
st.subheader("Completar un paro")

paro_id = st.selectbox("ID de paro", pendientes["id_paro"].tolist())

fila_paro = pendientes[pendientes["id_paro"] == paro_id].iloc[0]
equipo_paro = str(fila_paro.get("equipo", "")).strip()
apoyo_paro = str(fila_paro.get("necesita_acr", "")).strip()
st.caption(f"Equipo del paro: **{equipo_paro or '—'}** · "
           f"Apoyo solicitado: **{apoyo_paro or '—'}**")

# Quién ATIENDE de verdad (se guarda como EMPRESA en la fila de ACRS).
# RSI/STEO: su propia empresa, automático. ADMIN debe indicar cuál cierra
# si el paro es AMBOS/legacy (puede cerrar cualquiera de las dos por separado).
if EMPRESA in ("RSI", "STEO"):
    empresa_atiende = EMPRESA
else:  # ADMIN
    apoyo_norm = apoyo_paro.upper()
    if apoyo_norm in ("RSI", "STEO"):
        empresa_atiende = apoyo_norm
    else:  # AMBOS o legacy (SI/SÍ)
        # Solo ofrece las empresas que AÚN no han cerrado este paro
        opciones_emp = [e for e in ("RSI", "STEO")
                        if (str(paro_id), e) not in cerrados_set]
        empresa_atiende = st.radio(
            "¿Qué empresa atendió este paro? *",
            opciones_emp or ["RSI", "STEO"], index=None, horizontal=True,
            key=f"emp_{paro_id}",
        )

cat = cargar_catalogos()
componentes_eq = leer_componentes(equipo_paro) if equipo_paro else []

OPCION_NUEVO = "➕ Agregar componente nuevo…"
opciones = componentes_eq + [OPCION_NUEVO]
componente_sel = st.selectbox(
    "Componente afectado *",
    opciones,
    index=None,
    placeholder="Escribe para buscar o elige de la lista…",
    help=("Si la pieza no aparece, selecciona "
          f"\"{OPCION_NUEVO}\" para registrarla. Quedará disponible "
          "para futuros paros del mismo equipo."),
)
componente_nuevo = ""
if componente_sel == OPCION_NUEVO:
    componente_nuevo = st.text_input(
        "Nombre del nuevo componente *",
        placeholder="Ej.: Empaque de tapa del coater",
    )

# --- Tiempos de la intervención (fuera del form, para mostrar duración viva)
st.markdown("**Tiempos de la intervención**")
col_hi, col_hf = st.columns(2)
with col_hi:
    hora_ini_int = st.time_input("Hora de inicio *", value=None,
                                 key=f"hi_int_{paro_id}", step=60)
with col_hf:
    hora_fin_int = st.time_input("Hora de fin *", value=None,
                                 key=f"hf_int_{paro_id}", step=60)
dur_int_txt = ""
if hora_ini_int and hora_fin_int:
    dur_int_txt = duracion_hhmm(_date.today(), hora_ini_int, hora_fin_int)
    st.metric("Duración de la intervención", f"{dur_int_txt} h")

with st.form("completar"):
    causa_r = st.text_input("Causa raíz *")
    tipo_int = st.radio("Tipo de intervención *", cat["tipos_intervencion"],
                        index=None, horizontal=True,
                        help="Reemplazo reinicia la vida de la pieza; "
                             "Reparación/Ajuste no.")
    accion = st.text_area("Acción realizada", height=80)
    refaccion = st.text_input("Refacción utilizada")
    orden = st.text_input("Orden de Trabajo (opcional)")

    st.divider()
    st.markdown("### Firma del supervisor de producción")
    st.caption("Sin firma no se guarda. Si producción no está de acuerdo con "
               "los tiempos, corrígelos arriba y vuelvan a firmar.")
    firma_pwd = st.text_input("Contraseña de producción *", type="password",
                              help="La teclea el supervisor de producción.")

    enviar = st.form_submit_button("Guardar y cerrar ACR", type="primary",
                                   use_container_width=True)

if enviar:
    errores = []
    if componente_sel is None:
        errores.append("Selecciona un componente.")
    elif componente_sel == OPCION_NUEVO and not componente_nuevo.strip():
        errores.append("Escribe el nombre del nuevo componente.")
    if not causa_r.strip():
        errores.append("La causa raíz es obligatoria para cerrar un ACR.")
    if not tipo_int:
        errores.append("Selecciona el tipo de intervención "
                       "(Reemplazo / Reparación / Ajuste).")
    if not hora_ini_int or not hora_fin_int:
        errores.append("Captura las dos horas de la intervención.")
    elif total_minutos(_date.today(), hora_ini_int, hora_fin_int) <= 0:
        errores.append("La duración de la intervención debe ser mayor a 0.")
    if not firma_pwd:
        errores.append("Falta la firma del supervisor de producción.")
    elif not verificar_password("produccion", firma_pwd):
        errores.append("Contraseña de producción incorrecta. "
                       "Pide al supervisor que la verifique.")
    if not empresa_atiende:
        errores.append("Indica qué empresa atendió el paro (RSI o STEO).")

    if errores:
        for e in errores:
            st.error(e)
    else:
        if componente_sel == OPCION_NUEVO:
            try:
                componente_final, era_nuevo = agregar_componente(
                    equipo_paro, componente_nuevo
                )
            except Exception as e:
                st.error(f"No pude agregar el componente: {e}")
                st.stop()
            if not era_nuevo:
                st.info(f"Ya existía en el catálogo: «{componente_final}». "
                        "Se usó el nombre existente para no fragmentar el dato.")
        else:
            componente_final = componente_sel

        registro_acr = {
            "id_paro": paro_id,
            "empresa": empresa_atiende,
            "causa_raiz": causa_r.strip(),
            "componente": componente_final,
            "tipo_intervencion": tipo_int,
            "accion": accion.strip(),
            "refaccion": refaccion.strip(),
            "ini_int": hora_ini_int.strftime("%H:%M"),
            "fin_int": hora_fin_int.strftime("%H:%M"),
            "dur_int": dur_int_txt,
            "firma_produccion": "SÍ",
            "timestamp": _datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if orden.strip():
            registro_acr["orden_trabajo"] = orden.strip()
        try:
            guardar_acr(registro_acr)
            st.toast("Paro completado y firmado por producción", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")