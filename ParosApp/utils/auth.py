"""
Control de acceso por contraseña para vistas sensibles (p. ej. Mantenimiento).
La contraseña se guarda en st.secrets, NUNCA en el código.

secrets.toml (local: .streamlit/secrets.toml  |  nube: Settings → Secrets):

    [app]
    spreadsheet_key = "TU_KEY_DE_SHEETS"
    mantenimiento_password = "la_contraseña_que_elijas"
"""
import hmac

import streamlit as st


def _password_esperada(seccion: str):
    """Lee la contraseña configurada para la sección desde st.secrets."""
    try:
        return st.secrets["app"].get(f"{seccion}_password")
    except Exception:
        return None


def _password_correcta(seccion: str, ingresada: str) -> bool:
    esperada = _password_esperada(seccion)
    if not esperada:
        # Si no se configuró contraseña, se bloquea por seguridad.
        return False
    # compare_digest evita fugas de información por tiempo de respuesta.
    return hmac.compare_digest(str(ingresada), str(esperada))


def verificar_password(seccion: str, ingresada: str) -> bool:
    """
    Valida una contraseña SIN bloquear la vista. Diseñado para autenticaciones
    secundarias dentro de un flujo ya autenticado — por ejemplo, la firma del
    supervisor de producción al cerrar un ACR (mantenimiento ya está adentro,
    producción solo firma puntualmente sin cambiar de sesión).
    """
    return _password_correcta(seccion, ingresada)


# ---------------------------------------------------------------------------
# Acceso a Mantenimiento POR EMPRESA (RSI / STEO) + maestra (ADMIN).
#
# Cada empresa entra con su propia contraseña y solo ve/atiende los paros que
# le tocan. La clave es la sección en secrets ({clave}_password); el valor es
# el rol interno que devolvemos.
#
# secrets.toml:
#     [app]
#     rsi_password           = "..."   # ve RSI + AMBOS
#     steo_password          = "..."   # ve STEO + AMBOS
#     mantenimiento_password = "..."   # ADMIN: ve y atiende todo (opcional)
#
# Si solo configuras mantenimiento_password, todo sigue funcionando como antes
# (un solo acceso que ve todos los paros).
# ---------------------------------------------------------------------------
ROLES_MANTENIMIENTO = {
    "rsi": "RSI",
    "steo": "STEO",
    "mantenimiento": "ADMIN",   # contraseña maestra: ve y atiende todo
}


def _rol_para_password(ingresada: str):
    """Devuelve el rol ('RSI'/'STEO'/'ADMIN') de la 1ª contraseña que coincida."""
    for seccion, rol in ROLES_MANTENIMIENTO.items():
        if _password_correcta(seccion, ingresada):
            return rol
    return None


def requiere_empresa(titulo: str = "Acceso a Mantenimiento") -> str:
    """
    Igual que requiere_password, pero acepta varias contraseñas (una por
    empresa) y DETIENE la vista hasta autenticarse. Devuelve el rol que
    coincidió: 'RSI', 'STEO' o 'ADMIN'. El estado se guarda por sesión.
    """
    estado_key = "rol_mantenimiento"

    # Ya autenticado en esta sesión.
    if st.session_state.get(estado_key):
        rol = st.session_state[estado_key]
        with st.sidebar:
            st.caption(f"Sesión de mantenimiento: **{rol}**")
            if st.button("🔓 Cerrar sesión", use_container_width=True):
                st.session_state[estado_key] = None
                st.rerun()
        return rol

    # Aviso si no hay NINGUNA contraseña configurada.
    if not any(_password_esperada(s) for s in ROLES_MANTENIMIENTO):
        st.error(
            "No hay contraseñas configuradas. Agrega al menos una de "
            "`rsi_password`, `steo_password` o `mantenimiento_password` "
            "en la sección [app] de secrets.toml."
        )
        st.stop()

    st.title("🔒 " + titulo)
    st.caption("Ingresa la contraseña de tu empresa (RSI o STEO).")

    with st.form("login_mtto"):
        pwd = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Entrar", type="primary",
                                   use_container_width=True)
    if ok:
        rol = _rol_para_password(pwd)
        if rol:
            st.session_state[estado_key] = rol
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")

    # No autenticado: no se renderiza el resto de la vista.
    st.stop()


def requiere_password(seccion: str = "mantenimiento",
                      titulo: str = "Acceso restringido") -> None:
    """
    Muestra una pantalla de contraseña y DETIENE la vista (st.stop) hasta que
    se ingrese la correcta. Llamar al inicio de la vista que se quiera proteger.

    El estado se guarda por sesión, así que solo se pide la contraseña una vez
    mientras la pestaña del navegador siga abierta.
    """
    estado_key = f"auth_{seccion}"

    # Ya autenticado en esta sesión.
    if st.session_state.get(estado_key):
        with st.sidebar:
            if st.button("🔓 Cerrar sesión de mantenimiento",
                         use_container_width=True):
                st.session_state[estado_key] = False
                st.rerun()
        return

    # Aviso si el administrador olvidó configurar la contraseña.
    if not _password_esperada(seccion):
        st.error(
            "No hay contraseña configurada para esta sección. "
            f"Agrega `{seccion}_password` en la sección [app] de secrets.toml."
        )
        st.stop()

    st.title("🔒 " + titulo)
    st.caption("Esta sección es solo para personal de Mantenimiento.")

    with st.form(f"login_{seccion}"):
        pwd = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Entrar", type="primary",
                                   use_container_width=True)

    if ok:
        if _password_correcta(seccion, pwd):
            st.session_state[estado_key] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")

    # No autenticado: no se renderiza el resto de la vista.
    st.stop()