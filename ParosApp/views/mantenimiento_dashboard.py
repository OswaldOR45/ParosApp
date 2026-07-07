"""
VISTA 5 — DASHBOARD DE MANTENIMIENTO.

Métrica central: TIEMPO MUERTO ADMINISTRATIVO
    = tiempo de paro (lo que reporta producción)
    − tiempo de intervención (lo que reporta mantenimiento).

Es el tiempo en que la línea estuvo caída pero nadie estaba reparando: espera
del técnico, espera de refacción, diagnóstico, autorizaciones, etc. Separa la
"tardanza de la reparación" (responsabilidad de mtto) de la "tardanza
administrativa" (no es suya). De paso, con tipo_intervencion y empresa_acr,
salen los "tiempos por reparación" que su empresa les pide.

Solo se calcula para paros CERRADOS (los que ya tienen dur_int). Se gatea con
la misma contraseña por empresa: RSI ve lo suyo, STEO lo suyo, ADMIN ve todo.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from data.sheets import leer_paros, leer_acrs
from utils.auth import requiere_empresa
from utils.tiempo import hhmm_a_horas

EMPRESA = requiere_empresa("Dashboard de Mantenimiento")

st.title("Dashboard de Mantenimiento")
st.caption("Tiempo muerto administrativo = tiempo de paro (producción) − "
           "tiempo de intervención (mantenimiento).")

df = leer_paros()
if df.empty:
    st.info("Aún no hay datos para mostrar.")
    st.stop()

df = df.copy()

# Excluir tramos hijos: el dashboard de mantenimiento trabaja sobre eventos
# únicos. La duración del paro (h_paro) que se compara con la intervención
# debe ser la del padre, no los tramos parciales.
if "es_continuacion" in df.columns:
    df = df[df["es_continuacion"].fillna("").str.strip().str.upper() != "SÍ"]

# --- Derivados base ---------------------------------------------------------
df["fecha"] = pd.to_datetime(df.get("timestamp"), errors="coerce")
# Tiempo de paro reportado por producción (solo una de las dos columnas trae dato).
df["h_paro"] = (df.get("dur_prog", "").apply(hhmm_a_horas)
                + df.get("dur_noprog", "").apply(hhmm_a_horas))

for col in ("equipo", "area", "motivo"):
    df[col] = df.get(col, "").fillna("").astype(str).str.strip()
    df.loc[df[col] == "", col] = "Sin dato"

# --- Trae los cierres de ACRS ----------------------------------------------
# Un paro AMBOS puede tener hasta 2 filas en ACRS (una por empresa). Cada
# fila de ACRS es UNA intervención cerrada -> se cruza por id_paro y se
# EXPANDE: si AMBOS cerraron, el paro aparece 2 veces (una por intervención),
# que es justo lo que se necesita para medir MTTR/empresa por separado.
acrs = leer_acrs()
if acrs.empty or "id_paro" not in acrs.columns:
    st.warning("Aún no hay paros con intervención registrada (cerrados). "
               "Cierra ACRs en la vista de Mantenimiento para alimentar este "
               "tablero.")
    st.stop()

acrs = acrs.copy()
acrs["h_int"] = acrs.get("dur_int", "").apply(hhmm_a_horas)
for col in ("componente", "tipo_intervencion", "empresa"):
    acrs[col] = acrs.get(col, "").fillna("").astype(str).str.strip()
    acrs.loc[acrs[col] == "", col] = "Sin dato"
acrs["empresa"] = acrs["empresa"].str.upper()
acrs.loc[~acrs["empresa"].isin(["RSI", "STEO"]), "empresa"] = "Sin asignar"

# Renombra columnas de ACRS antes del merge para evitar conflictos con PAROSV2
acrs_merge = acrs[["id_paro", "empresa", "componente", "tipo_intervencion", "h_int"]].rename(columns={
    "componente": "comp_acr",
    "tipo_intervencion": "tipo_acr",
})

cerrados = df.merge(acrs_merge, on="id_paro", how="inner")

if "tipo_acr" not in cerrados.columns:
    cerrados["tipo_acr"] = "Sin dato"
else:
    cerrados["tipo_acr"] = (cerrados["tipo_acr"]
                             .fillna("Sin dato").astype(str).str.strip())
    cerrados.loc[cerrados["tipo_acr"] == "", "tipo_acr"] = "Sin dato"

if "comp_acr" not in cerrados.columns:
    cerrados["comp_acr"] = "Sin dato"
else:
    cerrados["comp_acr"] = (cerrados["comp_acr"]
                             .fillna("Sin dato").astype(str).str.strip())
    cerrados.loc[cerrados["comp_acr"] == "", "comp_acr"] = "Sin dato"

cerrados["brecha"] = cerrados["h_paro"] - cerrados["h_int"]
cerrados["brecha_pos"] = cerrados["brecha"].clip(lower=0)

if cerrados.empty:
    st.warning("Aún no hay paros con intervención registrada (cerrados). "
               "Cierra ACRs en la vista de Mantenimiento para alimentar este "
               "tablero.")
    st.stop()

# --- Filtros ---------------------------------------------------------------
f1, f2 = st.columns(2)
with f1:
    periodo = st.segmented_control("Periodo", ["Semana", "Este Mes", "Trimestre", "Todo"],
                                   default="Este Mes")
# Empresa: RSI/STEO ven lo suyo; ADMIN elige.
if EMPRESA == "ADMIN":
    with f2:
        emp_sel = st.segmented_control("Empresa", ["Todas", "RSI", "STEO"],
                                       default="Todas")
else:
    emp_sel = EMPRESA
    with f2:
        st.caption(f"Mostrando paros atendidos por **{EMPRESA}**.")

hoy = pd.Timestamp.today().normalize()
if periodo == "Semana":
    cerrados = cerrados[cerrados["fecha"] >= hoy - pd.Timedelta(days=7)]
elif periodo == "Este Mes":
    cerrados = cerrados[cerrados["fecha"] >= hoy.replace(day=1)]
elif periodo == "Trimestre":
    cerrados = cerrados[cerrados["fecha"] >= hoy - pd.Timedelta(days=90)]

if emp_sel != "Todas":
    cerrados = cerrados[cerrados["empresa"] == emp_sel]

if cerrados.empty:
    st.warning("No hay paros cerrados en el periodo / empresa seleccionados.")
    st.stop()

# --- KPIs ------------------------------------------------------------------
t_paro = cerrados["h_paro"].sum()
t_int = cerrados["h_int"].sum()
t_admin = cerrados["brecha_pos"].sum()
pct_admin = (t_admin / t_paro * 100) if t_paro > 0 else 0
mttr = cerrados["h_int"].mean()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Paros atendidos", len(cerrados))
k2.metric("Tiempo de paro", f"{t_paro:.1f} h")
k3.metric("Intervención (mtto)", f"{t_int:.1f} h")
k4.metric("Tiempo muerto admin.", f"{t_admin:.1f} h", f"{pct_admin:.0f}% del paro",
          delta_color="off")
k5.metric("MTTR (prom.)", f"{mttr*60:.0f} min")

st.divider()

# --- 1. Por equipo: intervención vs administrativo (apilado) ---------------
g = (cerrados.groupby("equipo")
     .agg(paro=("h_paro", "sum"), inter=("h_int", "sum")).reset_index())
g["admin"] = (g["paro"] - g["inter"]).clip(lower=0)
orden_eq = g.sort_values("paro")["equipo"].tolist()
melt = g.melt(id_vars="equipo", value_vars=["inter", "admin"],
              var_name="parte", value_name="horas")
melt["parte"] = melt["parte"].map({"inter": "Intervención (mtto)",
                                    "admin": "Administrativo (espera)"})
fig1 = px.bar(melt, x="horas", y="equipo", color="parte", orientation="h",
              category_orders={"equipo": orden_eq},
              color_discrete_map={"Intervención (mtto)": "#2E86C1",
                                  "Administrativo (espera)": "#E67E22"},
              title="Tiempo de paro por equipo: reparación vs. espera",
              labels={"horas": "Horas", "equipo": "", "parte": ""})
st.plotly_chart(fig1, use_container_width=True)
st.caption("La barra total es lo que reportó producción. La parte naranja es el "
           "tiempo muerto administrativo (la línea caída sin intervención activa).")

# --- 2. Tiempo muerto administrativo por área ------------------------------
por_area = (cerrados.groupby("area")["brecha_pos"].sum()
            .sort_values().reset_index())
por_area = por_area[por_area["brecha_pos"] > 0]
if not por_area.empty:
    fig2 = px.bar(por_area, x="brecha_pos", y="area", orientation="h",
                  title="Tiempo muerto administrativo por área",
                  labels={"brecha_pos": "Horas de espera", "area": ""},
                  color_discrete_sequence=["#E67E22"])
    st.plotly_chart(fig2, use_container_width=True)

# --- 3. MTTR por tipo de intervención (tiempos por reparación) -------------
# tipo_intervencion puede tener múltiples valores separados por " | "
# Se expande para contar cada tipo por separado.
tipos_exp = (cerrados[["h_int", "tipo_acr"]]
             .assign(tipo=cerrados["tipo_acr"].str.split(r"\s*\|\s*"))
             .explode("tipo"))
tipos_exp["tipo"] = tipos_exp["tipo"].str.strip().replace("", "Sin dato")

por_tipo = (tipos_exp.groupby("tipo")
            .agg(mttr=("h_int", "mean"), n=("h_int", "size")).reset_index()
            .sort_values("mttr", ascending=False))
por_tipo["mttr_min"] = por_tipo["mttr"] * 60
fig3 = px.bar(por_tipo, x="tipo", y="mttr_min", text="n",
              title="Tiempo de reparación promedio por tipo de intervención",
              labels={"mttr_min": "Minutos (promedio)", "tipo": ""},
              color_discrete_sequence=["#2E86C1"])
fig3.update_traces(texttemplate="%{text} paros", textposition="outside")
st.plotly_chart(fig3, use_container_width=True)

# --- 4. MTTR por componente (top 10) ---------------------------------------
comps_exp = (cerrados[["h_int", "comp_acr"]]
             .assign(comp=cerrados["comp_acr"].str.split(r"\s*\|\s*"))
             .explode("comp"))
comps_exp["comp"] = comps_exp["comp"].str.strip().replace("", "Sin dato")
comps_exp = comps_exp[comps_exp["comp"] != "Sin dato"]

if not comps_exp.empty:
    por_comp = (comps_exp.groupby("comp")
                .agg(mttr=("h_int", "mean"), n=("h_int", "size")).reset_index())
    por_comp["mttr_min"] = por_comp["mttr"] * 60
    top_comp = por_comp.sort_values("mttr_min", ascending=False).head(5)
    top_comp = top_comp.sort_values("mttr_min")
    fig4 = px.bar(top_comp, x="mttr_min", y="comp", orientation="h",
                  text="n",
                  title="Tiempo de reparación promedio por componente Top 5",
                  labels={"mttr_min": "Minutos (promedio)", "comp": ""},
                  color_discrete_sequence=["#2E86C1"])
    fig4.update_traces(texttemplate="%{text}×", textposition="outside")
    st.plotly_chart(fig4, use_container_width=True)

# --- 5. RSI vs STEO --------------------------------------------------------
if emp_sel == "Todas":
    por_emp = (cerrados.groupby("empresa")
               .agg(paros=("h_int", "size"), mttr=("h_int", "mean"),
                    admin=("brecha_pos", "sum")).reset_index())
    por_emp["mttr_min"] = por_emp["mttr"] * 60
    cA, cB = st.columns(2)
    with cA:
        fig5a = px.bar(por_emp, x="empresa", y="paros", color="empresa",
                       title="Paros atendidos por empresa",
                       labels={"paros": "Paros", "empresa": ""},
                       color_discrete_map={"RSI": "#16A085", "STEO": "#8E44AD",
                                           "Sin asignar": "#95A5A6"})
        fig5a.update_layout(showlegend=False)
        st.plotly_chart(fig5a, use_container_width=True)
    with cB:
        fig5b = px.bar(por_emp, x="empresa", y="mttr_min", color="empresa",
                       title="MTTR por empresa (min)",
                       labels={"mttr_min": "Minutos (promedio)", "empresa": ""},
                       color_discrete_map={"RSI": "#16A085", "STEO": "#8E44AD",
                                           "Sin asignar": "#95A5A6"})
        fig5b.update_layout(showlegend=False)
        st.plotly_chart(fig5b, use_container_width=True)

# --- 6. Tendencia semanal --------------------------------------------------
tmp = cerrados.dropna(subset=["fecha"]).copy()
if not tmp.empty:
    tmp["semana"] = tmp["fecha"].dt.to_period("W").dt.start_time
    trend = (tmp.groupby("semana")
             .agg(paro=("h_paro", "sum"), inter=("h_int", "sum")).reset_index())
    trend["admin"] = (trend["paro"] - trend["inter"]).clip(lower=0)
    trend_m = trend.melt(id_vars="semana", value_vars=["inter", "admin"],
                         var_name="parte", value_name="horas")
    trend_m["parte"] = trend_m["parte"].map(
        {"inter": "Intervención (mtto)", "admin": "Administrativo (espera)"})
    fig6 = px.area(trend_m, x="semana", y="horas", color="parte",
                   color_discrete_map={"Intervención (mtto)": "#2E86C1",
                                       "Administrativo (espera)": "#E67E22"},
                   title="Tendencia semanal: reparación vs. espera",
                   labels={"horas": "Horas", "semana": "", "parte": ""})
    st.plotly_chart(fig6, use_container_width=True)

# --- 7. Tabla de mayores brechas administrativas ---------------------------
st.subheader("Mayores brechas administrativas")
st.caption("Paros donde la línea estuvo más tiempo caída de lo que duró la "
           "reparación. Útiles para investigar la causa de la espera.")
tabla = cerrados.sort_values("brecha", ascending=False).head(15).copy()
tabla["fecha_txt"] = tabla["fecha"].dt.strftime("%Y-%m-%d")
tabla["paro_min"] = (tabla["h_paro"] * 60).round().astype(int)
tabla["int_min"] = (tabla["h_int"] * 60).round().astype(int)
tabla["brecha_min"] = (tabla["brecha"] * 60).round().astype(int)
cols_tabla = [c for c in ["fecha_txt", "id_paro", "equipo", "comp_acr",
                          "motivo", "empresa", "paro_min", "int_min", "brecha_min"]
              if c in tabla.columns]
st.dataframe(
    tabla[cols_tabla],
    use_container_width=True,
    hide_index=True,
    column_config={
        "fecha_txt": st.column_config.TextColumn("Fecha"),
        "id_paro": st.column_config.TextColumn("ID"),
        "paro_min": st.column_config.NumberColumn("Paro (min)"),
        "int_min": st.column_config.NumberColumn("Interv. (min)"),
        "brecha_min": st.column_config.NumberColumn("Brecha admin. (min)"),
    },
)

n_neg = int((cerrados["brecha"] < 0).sum())
if n_neg:
    st.info(f"Nota: {n_neg} paro(s) tienen intervención mayor al tiempo de paro "
            "reportado (brecha negativa). Suele indicar que producción registró "
            "menos tiempo del real o que los tiempos se traslaparon. Vale la pena "
            "revisarlos.")