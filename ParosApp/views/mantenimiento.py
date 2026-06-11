"""
VISTA 2 — MANTENIMIENTO (Complementar paro)
Pendientes = paros con ¿NECESITA ACR? = SÍ y sin Causa Raíz.
Así los paros programados/preventivos (ACR = NO) NO estorban la cola.
Orden de Trabajo es OPCIONAL (hay paros sin orden de mtto).
Aquí SÍ se permite selectbox: es para técnicos, no para piso.
"""
from datetime import date as _date

import streamlit as st

from data.sheets import (leer_paros, actualizar_paro, cargar_catalogos,
                         leer_componentes, agregar_componente)
from utils.auth import requiere_password, verificar_password
from utils.tiempo import duracion_hhmm, total_minutos

# Pide contraseña antes de mostrar o modificar cualquier dato.
# Producción no puede entrar aquí sin la contraseña de Mantenimiento.
requiere_password("mantenimiento")

st.title("Mantenimiento · Completar paros")

df = leer_paros()
if df.empty:
    st.info("Aún no hay paros registrados.")
    st.stop()

acr = df.get("necesita_acr", "").fillna("").astype(str).str.strip().str.upper()
causa = df.get("causa_raiz", "").fillna("").astype(str).str.strip()

# Valores que mandan el paro a la cola de Mantenimiento:
#   - "SI"/"SÍ"            -> paros antiguos (esquema previo a Ola 1)
#   - "RSI"/"STEO"/"AMBOS" -> nuevos: a quién llamó el operador
# "NO" o cualquier otra cosa queda fuera (paro operativo sin intervención).
VALORES_CON_APOYO = {"SI", "SÍ", "RSI", "STEO", "AMBOS"}
pendientes = df[acr.isin(VALORES_CON_APOYO) & (causa == "")]

st.subheader(f"Paros que requieren ACR y están pendientes ({len(pendientes)})")

cols_vista = [c for c in ["id_paro", "turno", "linea", "area", "equipo",
                          "motivo", "necesita_acr", "descripcion"]
              if c in pendientes.columns]
st.dataframe(
    pendientes[cols_vista],
    use_container_width=True,
    hide_index=True,
    column_config={
        "necesita_acr": st.column_config.TextColumn("Apoyo solicitado"),
    },
)

if pendientes.empty:
    st.success("No hay paros pendientes de causa raíz.")
    st.stop()

st.divider()
st.subheader("Completar un paro")

paro_id = st.selectbox("ID de paro", pendientes["id_paro"].tolist())

# El componente se elige FUERA del form: el flujo "agregar nuevo" necesita
# re-render condicional, que dentro de st.form no ocurriría hasta el submit.
fila_paro = pendientes[pendientes["id_paro"] == paro_id].iloc[0]
equipo_paro = str(fila_paro.get("equipo", "")).strip()
apoyo_paro = str(fila_paro.get("necesita_acr", "")).strip()
st.caption(f"Equipo del paro: **{equipo_paro or '—'}** · "
           f"Apoyo solicitado: **{apoyo_paro or '—'}**")

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

# --- Tiempos de la intervención (fuera del form, para mostrar duración viva) -
# El técnico llena las dos horas al CERRAR el ACR (modelo "un solo toque").
# Si la intervención cruzó medianoche, duracion_hhmm lo maneja automáticamente.
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
    # Tipo de intervención: define cómo el modelo lee la vida de la pieza.
    # Reemplazo = pieza nueva (reinicia el reloj). Sin default: elección consciente.
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

    if errores:
        for e in errores:
            st.error(e)
    else:
        # Resuelve el componente final (lo agrega al catálogo si es nuevo).
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

        campos = {
            "causa_raiz": causa_r.strip(),
            "componente": componente_final,
            "tipo_intervencion": tipo_int,
            "accion": accion.strip(),
            "refaccion": refaccion.strip(),
            "ini_int": hora_ini_int.strftime("%H:%M"),
            "fin_int": hora_fin_int.strftime("%H:%M"),
            "dur_int": dur_int_txt,
            "firma_produccion": "SÍ",
        }
        if orden.strip():
            campos["orden_trabajo"] = orden.strip()
        try:
            actualizar_paro(paro_id, campos)
            st.toast("Paro completado y firmado por producción", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")