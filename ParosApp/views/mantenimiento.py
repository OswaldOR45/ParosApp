"""
VISTA 2 — MANTENIMIENTO · Cerrar paros (ACR)

Flujo en 3 pasos:
  1. Elegir el paro pendiente (el más antiguo arriba).
  2. Decir qué se hizo: componente(s), tipo de intervención, horas, causa raíz.
  3. Firma del supervisor de producción.

Pendiente = paro con ¿NECESITA ACR? = RSI / STEO / AMBOS (o SÍ legacy) que aún
no tiene fila en ACRS para la empresa que lo atiende. Un paro AMBOS queda
pendiente para cada empresa por separado. Los paros aún en curso no aparecen.
"""
from datetime import date as _date

import pandas as pd
import streamlit as st

from data.sheets import (leer_paros, leer_acrs, guardar_acr, cargar_catalogos,
                         leer_componentes, agregar_componente, leer_hijos_de_paro)
from utils.auth import requiere_empresa, verificar_password
from utils.mtto import (AYUDA_TIPOS, SIN_COMPONENTE, TIPO_REVISION, eventos, fmt_h,
                        pendientes)
from utils.tiempo import duracion_hhmm, total_minutos, ahora_mx

EMPRESA = requiere_empresa()

st.title("Mantenimiento · Cerrar paros")

df = leer_paros()
if df.empty:
    st.info("Aún no hay paros registrados.")
    st.stop()

acrs = leer_acrs()
ev = eventos(df)
pend = pendientes(ev, acrs, EMPRESA)

# ---------------------------------------------------------------------------
# PASO 1 · Elegir el paro
# ---------------------------------------------------------------------------
etiqueta_emp = "todas las empresas" if EMPRESA == "ADMIN" else EMPRESA
c1, c2, c3 = st.columns(3)
c1.metric("Pendientes", len(pend))
c2.metric("Más antiguo", f"{pend['dias'].max()} días" if len(pend) else "—")
c3.metric("Con más de 3 días", int((pend["dias"] > 3).sum()) if len(pend) else 0)

if pend.empty:
    st.success(f"Sin paros pendientes para {etiqueta_emp}. ¡Todo cerrado!")
    st.stop()

with st.expander(f"Ver lista de pendientes · {etiqueta_emp}", expanded=False):
    tabla = pend.assign(
        fecha_txt=pend["fecha"].dt.strftime("%d/%m %H:%M"),
        dur=pend["h_paro"].apply(fmt_h),
        faltan_txt=pend["faltan"].str.join(" y "),
    )
    st.dataframe(
        tabla[["dias", "fecha_txt", "linea", "equipo", "motivo", "dur",
               "faltan_txt", "descripcion", "id_paro"]],
        hide_index=True, width="stretch",
        column_config={
            "dias": st.column_config.NumberColumn("Días", help="Días desde el paro"),
            "fecha_txt": "Fecha", "linea": "Línea", "equipo": "Equipo",
            "motivo": "Motivo", "dur": "Duración",
            "faltan_txt": "Falta cerrar", "descripcion": "Descripción",
            "id_paro": "ID",
        },
    )


def _etiqueta(pid: str) -> str:
    r = pend.loc[pend["id_paro"] == pid].iloc[0]
    alerta = "🔴" if r["dias"] > 3 else "🟡" if r["dias"] > 1 else "🟢"
    fecha = r["fecha"].strftime("%d/%m %H:%M") if pd.notna(r["fecha"]) else "s/f"
    linea = r["linea"].replace("Línea ", "L") or "—"
    return (f"{alerta} {fecha} · {linea} · {r['equipo'] or '—'} · "
            f"{r['motivo'] or '—'} · {fmt_h(r['h_paro'])} h · …{pid[-6:]}")
    # La etiqueta DEBE ser única: Streamlit identifica la opción por su texto.


st.subheader("1 · Elige el paro")
paro_id = st.selectbox("Paro pendiente (el más antiguo primero)",
                       pend["id_paro"].tolist(), format_func=_etiqueta,
                       key="mtto_paro")
p = pend.loc[pend["id_paro"] == paro_id].iloc[0]
equipo_paro = p["equipo"]
apoyo_paro = p["apoyo"]

# Ficha del paro: lo que capturó producción, para no tener que buscarlo.
with st.container(border=True):
    f1, f2, f3 = st.columns(3)
    f1.markdown(f"**Línea**  \n{p['linea'] or '—'}")
    f2.markdown(f"**Equipo / área**  \n{equipo_paro or '—'} · {p['area'] or '—'}")
    f3.markdown(f"**Duración total**  \n{fmt_h(p['h_paro'])} h"
                + (f" ({p['n_tramos']} turnos)" if p["n_tramos"] > 1 else ""))
    f1.markdown(f"**Fecha**  \n{p['fecha']:%d/%m/%Y %H:%M}" if pd.notna(p["fecha"]) else "**Fecha**  \n—")
    f2.markdown(f"**Motivo**  \n{p['motivo'] or '—'}")
    f3.markdown(f"**Apoyo pedido**  \n{apoyo_paro or '—'}")
    st.markdown(f"**Lo que reportó producción:** {p['descripcion'] or '_(sin descripción)_'}")
    st.caption(f"ID {paro_id} · Grupo {p['turno'] or '—'}")

if p["n_tramos"] > 1:
    with st.expander(f"Ver los {p['n_tramos']} tramos del paro"):
        hijos = leer_hijos_de_paro(paro_id)
        tramos = [p] + [hijos.iloc[i] for i in range(len(hijos))]
        st.dataframe(pd.DataFrame([{
            "Grupo": t.get("turno", "—"),
            "Inicio": t.get("ini_noprog") or t.get("ini_prog") or "—",
            "Fin": t.get("fin_noprog") or t.get("fin_prog") or "—",
            "Duración": t.get("dur_noprog") or t.get("dur_prog") or "—",
        } for t in tramos]), hide_index=True, width="stretch")

# Empresa que cierra: automática para RSI/STEO; ADMIN elige si hay dos.
if EMPRESA in ("RSI", "STEO"):
    empresa_atiende = EMPRESA
elif len(p["faltan"]) == 1:
    empresa_atiende = p["faltan"][0]
    st.caption(f"Se cerrará a nombre de **{empresa_atiende}**.")
else:
    empresa_atiende = st.radio("¿Qué empresa cierra este paro? *", p["faltan"],
                               index=None, horizontal=True, key=f"emp_{paro_id}")

# ---------------------------------------------------------------------------
# PASO 2 · ¿Qué se hizo?
# ---------------------------------------------------------------------------
st.subheader("2 · ¿Qué se hizo?")
cat = cargar_catalogos()
equipos = list(dict.fromkeys(([equipo_paro] if equipo_paro else []) + cat["equipos"]))
equipo_comp = st.selectbox(
    "¿En qué equipo está la pieza?", equipos, key=f"eqc_{paro_id}",
    help="Por defecto, el equipo que capturó producción. Cámbialo si la pieza "
         "pertenece a otro equipo (p. ej. producción puso Extrusor pero se cambiaron "
         "sellos del Secador).")
componentes_eq = leer_componentes(equipo_comp) if equipo_comp else []

OPCION_NUEVO = "➕ Agregar componente nuevo…"
k_n = f"n_comps_{paro_id}"
st.session_state.setdefault(k_n, 1)

with st.popover("¿Qué tipo de intervención elijo?"):
    for t, d in AYUDA_TIPOS.items():
        st.markdown(f"**{t}**: {d}.")
    st.caption("Esto alimenta el cálculo de vida útil de cada pieza: un "
               "Reemplazo reinicia su reloj; una Reparación o un Ajuste no.")

_campos = ("comp_sel", "tipo_sel", "comp_nuevo")


def _agregar_fila():
    st.session_state[k_n] += 1


def _quitar_fila(i: int):
    """Quita el renglón i recorriendo hacia arriba los de abajo."""
    n = st.session_state[k_n]
    for j in range(i, n - 1):
        for c in _campos:
            sig = f"{c}_{paro_id}_{j + 1}"
            st.session_state[f"{c}_{paro_id}_{j}"] = st.session_state.get(sig)
    for c in _campos:
        st.session_state.pop(f"{c}_{paro_id}_{n - 1}", None)
    st.session_state[k_n] = n - 1


componentes_data = []
for i in range(st.session_state[k_n]):
    ca, cb, cc = st.columns([3, 2, 0.6], vertical_alignment="bottom")
    comp_sel = ca.selectbox(
        f"Componente {i + 1}", componentes_eq + [OPCION_NUEVO], index=None,
        placeholder="Busca o elige la pieza…", key=f"comp_sel_{paro_id}_{i}")
    tipo_sel = cb.selectbox(
        f"Tipo {i + 1}", cat["tipos_intervencion"], index=None,
        placeholder="Tipo…", key=f"tipo_sel_{paro_id}_{i}")
    if st.session_state[k_n] > 1:
        cc.button("🗑️", key=f"del_comp_{paro_id}_{i}", help="Quitar este renglón",
                  on_click=_quitar_fila, args=(i,))
    comp_nuevo = ""
    if comp_sel == OPCION_NUEVO:
        comp_nuevo = st.text_input(
            f"Nombre del componente nuevo {i + 1} *",
            placeholder="Una pieza por nombre. Ej.: Rodamiento lado motor del extrusor",
            key=f"comp_nuevo_{paro_id}_{i}")
    componentes_data.append((comp_sel, comp_nuevo, tipo_sel))

st.button("➕ Otro componente", key=f"add_comp_{paro_id}", on_click=_agregar_fila)

st.markdown("**Horario de la intervención**")
hi_col, hf_col, dur_col = st.columns(3)
hora_ini_int = hi_col.time_input("Inicio *", value=None, key=f"hi_int_{paro_id}", step=60)
hora_fin_int = hf_col.time_input("Fin *", value=None, key=f"hf_int_{paro_id}", step=60)
dur_int_txt = ""
if hora_ini_int and hora_fin_int:
    dur_int_txt = duracion_hhmm(_date.today(), hora_ini_int, hora_fin_int)
    dur_col.metric("Duración", f"{dur_int_txt} h")
    min_int = total_minutos(_date.today(), hora_ini_int, hora_fin_int)
    if p["h_paro"] > 0 and min_int > p["h_paro"] * 60 + 1:
        st.warning(f"La intervención ({dur_int_txt} h) dura más que el paro "
                   f"({fmt_h(p['h_paro'])} h). Revisa las horas antes de firmar.")

with st.form(f"cerrar_{paro_id}"):
    causa_r = st.text_input(
        "Causa raíz *",
        placeholder="¿Por qué falló? Ej.: rodamiento sin lubricación por graseras tapadas")
    accion = st.text_area("Acción realizada", height=80,
                          placeholder="Qué se hizo para dejar el equipo operando")
    r1, r2 = st.columns(2)
    refaccion = r1.text_input("Refacción utilizada")
    orden = r2.text_input("Orden de trabajo (opcional)")

    # -----------------------------------------------------------------------
    # PASO 3 · Firma
    # -----------------------------------------------------------------------
    st.subheader("3 · Firma de producción")
    st.caption("El supervisor de producción revisa los datos y teclea su "
               "contraseña. Sin firma no se guarda.")
    firma_pwd = st.text_input("Contraseña de producción *", type="password")
    enviar = st.form_submit_button("Guardar y cerrar paro", type="primary",
                                   width="stretch")

if enviar:
    errores = []
    comps_validos = []
    for i, (comp_sel, comp_nuevo, tipo_sel) in enumerate(componentes_data, 1):
        if not tipo_sel:
            errores.append(f"Componente {i}: elige el tipo de intervención.")
        elif tipo_sel != TIPO_REVISION and comp_sel is None:
            errores.append(f"Componente {i}: «{tipo_sel}» requiere indicar la pieza.")
        elif comp_sel == OPCION_NUEVO and not comp_nuevo.strip():
            errores.append(f"Componente {i}: escribe el nombre de la pieza nueva.")
        else:
            comps_validos.append((comp_sel, comp_nuevo, tipo_sel))
    if not causa_r.strip():
        errores.append("La causa raíz es obligatoria.")
    if not hora_ini_int or not hora_fin_int:
        errores.append("Captura la hora de inicio y fin de la intervención.")
    elif total_minutos(_date.today(), hora_ini_int, hora_fin_int) <= 0:
        errores.append("La intervención debe durar más de 0 minutos.")
    if not empresa_atiende:
        errores.append("Indica qué empresa cierra el paro.")
    if not firma_pwd:
        errores.append("Falta la firma del supervisor de producción.")
    elif not verificar_password("produccion", firma_pwd):
        errores.append("Contraseña de producción incorrecta.")

    if errores:
        for e in errores:
            st.error(e)
        st.stop()

    comps, tipos = [], []
    for comp_sel, comp_nuevo, tipo_sel in comps_validos:
        if comp_sel == OPCION_NUEVO:
            try:
                comp_final, era_nuevo = agregar_componente(equipo_comp, comp_nuevo)
            except Exception as e:
                st.error(f"No pude agregar el componente: {e}")
                st.stop()
            if not era_nuevo:
                st.info(f"Ya existía en el catálogo como «{comp_final}»; se usó ese nombre.")
        else:
            comp_final = comp_sel or ""
        # Componente y tipo SIEMPRE alineados posición a posición; una revisión
        # sin pieza se guarda como «—» para no desfasar las listas.
        comps.append(comp_final or SIN_COMPONENTE)
        tipos.append(tipo_sel)

    registro = {
        "id_paro": paro_id,
        "empresa": empresa_atiende,
        "causa_raiz": causa_r.strip(),
        "componente": " | ".join(comps),
        "tipo_intervencion": " | ".join(tipos),
        "accion": accion.strip(),
        "refaccion": refaccion.strip(),
        "ini_int": hora_ini_int.strftime("%H:%M"),
        "fin_int": hora_fin_int.strftime("%H:%M"),
        "dur_int": dur_int_txt,
        "firma_produccion": "SÍ",
        "timestamp": ahora_mx().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if orden.strip():
        registro["orden_trabajo"] = orden.strip()
    try:
        guardar_acr(registro)
    except Exception as e:
        st.error(f"Error al guardar: {e}")
        st.stop()
    st.session_state.pop(k_n, None)
    st.session_state.pop("mtto_paro", None)
    st.toast("Paro cerrado y firmado por producción", icon="✅")
    st.rerun()

# ---------------------------------------------------------------------------
# Últimos cierres (para verificar lo capturado)
# ---------------------------------------------------------------------------
if not acrs.empty and "id_paro" in acrs.columns:
    ult = acrs.copy()
    if EMPRESA in ("RSI", "STEO") and "empresa" in ult.columns:
        ult = ult[ult["empresa"].astype(str).str.upper() == EMPRESA]
    if not ult.empty:
        with st.expander("Mis últimos 10 cierres"):
            cols = [c for c in ["timestamp", "id_paro", "empresa", "componente",
                                "tipo_intervencion", "dur_int", "causa_raiz"] if c in ult.columns]
            st.dataframe(ult[cols].tail(10).iloc[::-1], hide_index=True,
                         width="stretch",
                         column_config={"timestamp": "Cerrado", "id_paro": "ID",
                                        "empresa": "Empresa", "componente": "Componente",
                                        "tipo_intervencion": "Tipo", "dur_int": "Duración",
                                        "causa_raiz": "Causa raíz"})
