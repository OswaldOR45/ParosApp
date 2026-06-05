"""
VISTA 2 — MANTENIMIENTO (Complementar paro)
Pendientes = paros con ¿NECESITA ACR? = SÍ y sin Causa Raíz.
Así los paros programados/preventivos (ACR = NO) NO estorban la cola.
Orden de Trabajo es OPCIONAL (hay paros sin orden de mtto).
Aquí SÍ se permite selectbox: es para técnicos, no para piso.
"""
import streamlit as st

from data.sheets import leer_paros, actualizar_paro
from utils.auth import requiere_password

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
pendientes = df[(acr.isin(["SI", "SÍ"])) & (causa == "")]

st.subheader(f"Paros que requieren ACR y están pendientes ({len(pendientes)})")

cols_vista = [c for c in ["id_paro", "turno", "linea", "area", "equipo",
                          "motivo", "descripcion"] if c in pendientes.columns]
st.dataframe(pendientes[cols_vista], use_container_width=True, hide_index=True)

if pendientes.empty:
    st.success("No hay paros pendientes de causa raíz.")
    st.stop()

st.divider()
st.subheader("Completar un paro")

paro_id = st.selectbox("ID de paro", pendientes["id_paro"].tolist())

with st.form("completar"):
    causa_r = st.text_input("Causa raíz *")
    componente = st.text_input("Componente específico")
    accion = st.text_area("Acción realizada", height=80)
    refaccion = st.text_input("Refacción utilizada")
    orden = st.text_input("Orden de Trabajo (opcional)")
    enviar = st.form_submit_button("Guardar", type="primary",
                                   use_container_width=True)

if enviar:
    if not causa_r.strip():
        st.error("La causa raíz es obligatoria para cerrar un ACR.")
    else:
        campos = {
            "causa_raiz": causa_r.strip(),
            "componente": componente.strip(),
            "accion": accion.strip(),
            "refaccion": refaccion.strip(),
        }
        if orden.strip():
            campos["orden_trabajo"] = orden.strip()
        try:
            actualizar_paro(paro_id, campos)
            st.toast("Paro completado", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")