"""
Lógica compartida por «Mantenimiento» (completar paros) y «Dashboard Mtto».

Tenerla en un solo lugar garantiza que el número de pendientes, la duración
de cada evento y el tiempo de intervención salgan IGUAL en las dos pantallas.
"""
import numpy as np
import pandas as pd

from utils.tiempo import hhmm_a_horas, hoy_mx

LEGACY = {"SI", "SÍ"}
TIPO_REVISION = "Revisión / Diagnóstico"
SIN_COMPONENTE = "—"          # se guarda cuando una intervención no lleva pieza

# Texto de ayuda para que el técnico elija bien: alimenta el análisis Weibull.
AYUDA_TIPOS = {
    "Reemplazo": "se puso una pieza nueva o reconstruida",
    "Reparación": "se reparó la misma pieza y se volvió a montar",
    "Ajuste": "se calibró, apretó o alineó sin cambiar piezas",
    "Revisión / Diagnóstico": "se revisó o diagnosticó sin cambiar ni reparar nada",
}

COLOR_REPARACION = "#2a78d6"
COLOR_ESPERA = "#eda100"
COLOR_TIPO = {"Reemplazo": "#6250d6", "Reparación": "#1baf7a",
              "Ajuste": "#eda100", "Revisión / Diagnóstico": "#9CA3AF"}


def _txt(df, col):
    return (df[col].fillna("").astype(str).str.strip() if col in df.columns
            else pd.Series("", index=df.index))


def a_fecha(serie: pd.Series) -> pd.Series:
    """Texto -> datetime64[ns] de NumPy (nunca Arrow), para que las restas de
    fechas funcionen igual en cualquier versión de pandas / pyarrow."""
    f = pd.to_datetime(serie.astype(object), errors="coerce")
    return pd.Series(f.to_numpy(dtype="datetime64[ns]"), index=serie.index)


def fmt_h(horas) -> str:
    """1.8333 -> '1:50'."""
    try:
        m = int(round(float(horas) * 60))
    except (TypeError, ValueError):
        return "—"
    return f"{m // 60}:{m % 60:02d}"


def visibles(empresa: str) -> set:
    if empresa == "RSI":
        return {"RSI", "AMBOS"} | LEGACY
    if empresa == "STEO":
        return {"STEO", "AMBOS"} | LEGACY
    return {"RSI", "STEO", "AMBOS"} | LEGACY


def eventos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Un renglón por EVENTO (padre) con la duración TOTAL de sus tramos.
    Columnas añadidas: fecha (datetime), h_paro, n_tramos, en_curso.
    """
    if df.empty:
        return df
    d = df.copy()
    d["id_paro"] = _txt(d, "id_paro")
    d["h_tramo"] = (_txt(d, "dur_prog").apply(hhmm_a_horas)
                    + _txt(d, "dur_noprog").apply(hhmm_a_horas))
    hijo = _txt(d, "es_continuacion").str.upper().isin(LEGACY)
    padre = _txt(d, "paro_padre")
    hijos = d[hijo]
    ev = d[~hijo].copy()
    ev["h_paro"] = ev["h_tramo"] + ev["id_paro"].map(
        hijos.groupby(padre[hijos.index])["h_tramo"].sum()).fillna(0.0)
    ev["n_tramos"] = 1 + ev["id_paro"].map(padre[hijos.index].value_counts()).fillna(0).astype(int)
    ev["en_curso"] = _txt(ev, "paro_en_curso").str.upper().isin(LEGACY)
    ev["fecha"] = a_fecha(_txt(ev, "timestamp"))
    ev["apoyo"] = _txt(ev, "necesita_acr").str.upper()
    for c in ("linea", "equipo", "area", "motivo", "descripcion", "turno"):
        ev[c] = _txt(ev, c)
    return ev


def cerrados_set(acrs: pd.DataFrame) -> set:
    if acrs.empty or "id_paro" not in acrs.columns or "empresa" not in acrs.columns:
        return set()
    return set(zip(_txt(acrs, "id_paro"), _txt(acrs, "empresa").str.upper()))


def empresas_faltantes(id_paro: str, apoyo: str, cerrados: set, empresa: str) -> list:
    """Empresas que aún deben cerrar este paro (según quién está viendo)."""
    if empresa in ("RSI", "STEO"):
        return [] if (id_paro, empresa) in cerrados else [empresa]
    if apoyo == "AMBOS":
        return [e for e in ("RSI", "STEO") if (id_paro, e) not in cerrados]
    if apoyo in ("RSI", "STEO"):
        return [] if (id_paro, apoyo) in cerrados else [apoyo]
    # legacy SI/SÍ: basta un cierre de cualquiera
    return [] if any(c[0] == id_paro for c in cerrados) else ["RSI", "STEO"]


def pendientes(ev: pd.DataFrame, acrs: pd.DataFrame, empresa: str) -> pd.DataFrame:
    """Paros que necesitan cierre de `empresa` (ADMIN: de cualquiera)."""
    if ev.empty:
        return ev
    cerr = cerrados_set(acrs)
    p = ev[ev["apoyo"].isin(visibles(empresa)) & ~ev["en_curso"]].copy()
    p["faltan"] = [empresas_faltantes(i, a, cerr, empresa)
                   for i, a in zip(p["id_paro"], p["apoyo"])]
    p = p[p["faltan"].str.len() > 0]
    # Resta en NumPy: con pandas 3 + pyarrow reciente, Timestamp − columna Arrow
    # lanza ArrowNotImplementedError (pasó en Streamlit Cloud, Python 3.14).
    hoy = np.datetime64(hoy_mx().to_datetime64(), "D")
    dias_f = p["fecha"].to_numpy(dtype="datetime64[ns]").astype("datetime64[D]")
    dias = (hoy - dias_f).astype("timedelta64[D]").astype(np.int64)
    p["dias"] = np.where(np.isnat(dias_f), 0, dias)
    return p.sort_values("fecha")


def _min(hhmm) -> int | None:
    s = str(hhmm or "").strip()
    try:
        h, m = s.split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def horas_intervencion(grupo: pd.DataFrame) -> float:
    """
    Horas en que AL MENOS una empresa estuvo trabajando en el paro: unión de
    los intervalos INI_INT–FIN_INT (RSI y STEO pueden trabajar a la vez; no se
    suman dos veces). Si faltan horas, se usa la mayor DUR_INT.
    """
    tramos = []
    for ini, fin in zip(grupo.get("ini_int", []), grupo.get("fin_int", [])):
        a, b = _min(ini), _min(fin)
        if a is None or b is None:
            tramos = None
            break
        if b <= a:
            b += 24 * 60
        tramos.append((a, b))
    if tramos:
        tramos.sort()
        tot, (ca, cb) = 0, tramos[0]
        for a, b in tramos[1:]:
            if a <= cb:
                cb = max(cb, b)
            else:
                tot += cb - ca
                ca, cb = a, b
        return (tot + cb - ca) / 60.0
    return float(grupo.get("dur_int", pd.Series(dtype=str)).apply(hhmm_a_horas).max() or 0.0)


def separar_componentes(comp: str, tipo: str) -> list[tuple[str, str]]:
    """'A | — | B' + 'Reemplazo | Revisión | Ajuste' -> pares alineados."""
    cs = [c.strip() for c in str(comp or "").split("|")] if str(comp or "").strip() else []
    ts = [t.strip() for t in str(tipo or "").split("|")] if str(tipo or "").strip() else []
    if len(cs) == len(ts):
        pares = list(zip(cs, ts))
    elif len(ts) == 1:
        pares = [(c, ts[0]) for c in cs] or [("", ts[0])]
    else:
        # Cierres viejos: la app omitía el componente vacío de una Revisión.
        ts2 = list(ts)
        extra = []
        while len(ts2) > len(cs) and TIPO_REVISION in ts2:
            ts2.remove(TIPO_REVISION)
            extra.append(("", TIPO_REVISION))
        pares = (list(zip(cs, ts2)) if len(ts2) == len(cs)
                 else [(c, ts[0]) for c in cs]) + extra
    return [("" if c in ("", SIN_COMPONENTE) else c, t or "Sin tipo") for c, t in pares]