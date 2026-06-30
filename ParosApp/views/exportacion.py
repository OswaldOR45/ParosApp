"""VISTA 4 — EXPORTACIÓN (genérico, pre-Weibull)."""
import pandas as pd
import streamlit as st

from data.sheets import leer_paros, leer_acrs

st.title("Exportar datos")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para exportar.")
    st.stop()

df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")

# --- Trae los cierres de ACRS y los une al export ---------------------------
# Un paro AMBOS puede tener hasta 2 filas en ACRS (una por empresa). Se usa
# LEFT JOIN para no perder paros que aún no tienen ACR cerrado: esos quedan
# con las columnas de mantenimiento vacías (NaN).
acrs = leer_acrs()
if not acrs.empty and "id_paro" in acrs.columns:
    cols_acr = [c for c in ["id_paro", "empresa", "causa_raiz", "componente",
                            "tipo_intervencion", "accion", "refaccion",
                            "ini_int", "fin_int", "dur_int", "orden_trabajo",
                            "firma_produccion"]
               if c in acrs.columns]
    df = df.merge(acrs[cols_acr], on="id_paro", how="left", suffixes=("", "_acr"))

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