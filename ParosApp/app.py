"""
Punto de entrada de la app de Registro de Paros.
Usa la navegación moderna de Streamlit (st.navigation + st.Page).
Ejecuta con:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(
    page_title="Registro de Paros",
    page_icon="⏱️",
    layout="centered",          # centered = mejor para celular/tablet
    initial_sidebar_state="collapsed",
)

# Cada vista es un archivo en /views. El de operador es la página por defecto.
operador = st.Page(
    "views/operador.py", title="Registrar Paro", icon=":material/edit_note:", default=True
)
mantenimiento = st.Page(
    "views/mantenimiento.py", title="Mantenimiento", icon=":material/build:"
)
mantenimiento_dashboard = st.Page(
    "views/mantenimiento_dashboard.py", title="Dashboard Mtto",
    icon=":material/engineering:"
)
dashboard = st.Page(
    "views/dashboard.py", title="Dashboard", icon=":material/insights:"
)
exportacion = st.Page(
    "views/exportacion.py", title="Exportar", icon=":material/download:"
)

pg = st.navigation(
    {
        "Piso de producción": [operador, mantenimiento],
        "Análisis": [mantenimiento_dashboard, dashboard, exportacion],
    }
)
pg.run()
