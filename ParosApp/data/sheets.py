"""
Capa de acceso a datos (Google Sheets) — ESCRITURA Y LECTURA POR NOMBRE.
El código empata cada dato con su columna usando el ENCABEZADO de la fila 1,
no por posición. Inmune a reordenar columnas o a columnas de sobra.
"""
import re
import unicodedata

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

from config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# --- Normalización de encabezados (ignora acentos, mayúsculas y espacios) --
def _norm(texto) -> str:
    s = str(texto)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


# --- Conexión --------------------------------------------------------------
@st.cache_resource
def _get_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


@st.cache_resource
def _get_spreadsheet():
    return _get_client().open_by_key(st.secrets["app"]["spreadsheet_key"])


def _ws(nombre: str):
    return _get_spreadsheet().worksheet(nombre)


# --- Mapa encabezado_normalizado -> índice de columna (1-based) ------------
def _mapa_columnas(ws):
    header = ws.row_values(1)
    return {_norm(h): i + 1 for i, h in enumerate(header) if str(h).strip()}, header


# --- Lectura (cacheada 60s) -----------------------------------------------
@st.cache_data(ttl=60)
def leer_paros() -> pd.DataFrame:
    registros = _ws(settings.HOJA_PAROS).get_all_records()
    df = pd.DataFrame(registros)
    if df.empty:
        return df
    # Renombra columnas de la hoja -> claves internas, para que las vistas
    # trabajen con nombres estables (turno, equipo, motivo, etc.).
    inverso = {_norm(v): k for k, v in settings.FIELD_TO_HEADER.items()}
    df = df.rename(columns={c: inverso.get(_norm(c), c) for c in df.columns})
    return df


# --- Escritura: append seguro ante concurrencia ---------------------------
def guardar_paro(registro: dict):
    """registro usa claves internas (turno, area, motivo, ...)."""
    ws = _ws(settings.HOJA_PAROS)
    mapa, header = _mapa_columnas(ws)
    fila = [""] * len(header)
    faltantes = []
    for clave, valor in registro.items():
        encabezado = settings.FIELD_TO_HEADER.get(clave)
        if encabezado is None:
            continue
        idx = mapa.get(_norm(encabezado))
        if idx is None:
            faltantes.append(encabezado)
            continue
        fila[idx - 1] = valor
    if faltantes:
        raise ValueError(
            "No encontré estas columnas en la hoja: " + ", ".join(faltantes)
            + ". Encabezados detectados: " + ", ".join(header)
        )
    ws.append_row(fila, value_input_option="USER_ENTERED")
    leer_paros.clear()


def actualizar_paro(id_paro: str, campos: dict):
    """Actualiza un paro existente (lo usa Mantenimiento). Busca por ID_PARO."""
    ws = _ws(settings.HOJA_PAROS)
    mapa, _ = _mapa_columnas(ws)
    col_id = mapa.get(_norm(settings.FIELD_TO_HEADER["id_paro"]))
    if col_id is None:
        raise ValueError("La hoja no tiene columna ID_PARO.")
    ids = ws.col_values(col_id)
    fila = next((r for r, v in enumerate(ids, start=1) if v == str(id_paro)), None)
    if fila is None:
        raise ValueError(f"No se encontró el paro {id_paro}")
    for clave, valor in campos.items():
        encabezado = settings.FIELD_TO_HEADER.get(clave)
        idx = mapa.get(_norm(encabezado)) if encabezado else None
        if idx:
            ws.update_cell(fila, idx, valor)
    leer_paros.clear()


# --- Catálogos (usa defaults; lee pestañas cat_* si existen) ---------------
@st.cache_data(ttl=300)
def cargar_catalogos() -> dict:
    base = settings.catalogos_default()
    try:
        motivos = _ws(settings.HOJA_MOTIVOS).get_all_records()
        if motivos:
            base["motivos"] = [m["motivo"] for m in motivos]
            base["tipo_por_motivo"] = {m["motivo"]: m["tipo_paro"] for m in motivos}
    except Exception:
        pass
    try:
        equipos = _ws(settings.HOJA_EQUIPOS).get_all_records()
        if equipos:
            base["equipos"] = sorted({e["equipo"] for e in equipos})
    except Exception:
        pass
    return base


# --- Catálogo dinámico de componentes (por equipo) -------------------------
@st.cache_data(ttl=300)
def leer_componentes(equipo: str) -> list:
    """
    Devuelve los componentes del catálogo para `equipo`, filtrando los activos.
    Si la pestaña no existe o está vacía, devuelve [] (la app sigue funcionando
    y el usuario podrá agregar el primer componente desde la vista).

    Encabezados esperados en la fila 1 de `cat_componentes`:
        EQUIPO | COMPONENTE | ACTIVO   (orden libre; se empata por nombre)
    """
    try:
        registros = _ws(settings.HOJA_COMPONENTES).get_all_records()
    except Exception:
        return []
    if not registros:
        return []

    eq_target = _norm(equipo)
    nombres = []
    for r in registros:
        norm = {_norm(k): v for k, v in r.items()}
        if _norm(norm.get("EQUIPO", "")) != eq_target:
            continue
        # Si no hay columna ACTIVO o está vacía, asumimos activo.
        activo = _norm(norm.get("ACTIVO", "SI"))
        if activo not in ("SI", "S", "TRUE", "1", ""):
            continue
        nombre = str(norm.get("COMPONENTE", "")).strip()
        if nombre:
            nombres.append(nombre)
    return sorted(set(nombres), key=lambda s: s.lower())


def agregar_componente(equipo: str, componente: str):
    """
    Agrega un componente al catálogo. Devuelve (nombre_final, era_nuevo).

    Si ya existe una entrada equivalente (comparación normalizada — ignora
    acentos, mayúsculas y espacios), NO duplica: devuelve el nombre tal como
    está guardado y era_nuevo = False. Esto previene fragmentación silenciosa.
    """
    nombre = " ".join(str(componente).split()).strip()
    if not nombre:
        raise ValueError("El nombre del componente no puede estar vacío.")

    for ex in leer_componentes(equipo):
        if _norm(ex) == _norm(nombre):
            return ex, False  # ya existe -> reutilizar

    ws = _ws(settings.HOJA_COMPONENTES)
    mapa, header = _mapa_columnas(ws)
    fila = [""] * len(header)
    for clave, valor in {"EQUIPO": equipo, "COMPONENTE": nombre, "ACTIVO": "SÍ"}.items():
        idx = mapa.get(_norm(clave))
        if idx:
            fila[idx - 1] = valor
    ws.append_row(fila, value_input_option="USER_ENTERED")
    leer_componentes.clear()
    return nombre, True