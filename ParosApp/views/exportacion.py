"""VISTA 4 — EXPORTACIÓN (genérico, pre-Weibull)."""
import pandas as pd
import streamlit as st

from data.sheets import leer_paros

st.title("Exportar datos")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para exportar.")
    st.stop()

df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")

equipos = ["Todos"] + sorted(df["equipo"].dropna().unique().tolist())
equipo = st.selectbox("Equipo", equipos)
c1, c2 = st.columns(2)
desde = c1.date_input("Desde", value=df["fecha"].min())
hasta = c2.date_input("Hasta", value=df["fecha"].max())

f = df[(df["fecha"] >= pd.Timestamp(desde)) & (df["fecha"] <= pd.Timestamp(hasta))]
if equipo != "Todos":
    f = f[f["equipo"] == equipo]

st.write(f"**{len(f)}** registros en el filtro.")
st.dataframe(f, use_container_width=True, hide_index=True)

st.download_button("Descargar CSV", data=f.to_csv(index=False).encode("utf-8"),
                   file_name=f"paros_{equipo}_{desde}_{hasta}.csv".replace(" ", "_"),
                   mime="text/csv", type="primary", use_container_width=True)
