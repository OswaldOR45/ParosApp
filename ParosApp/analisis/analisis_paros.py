"""
================================================================================
 analisis_paros.py  —  Motor de análisis de confiabilidad (v2)
 Plan Maestro · Mantenimiento Preventivo · Planta Pet Food
--------------------------------------------------------------------------------
 Lee lo que captura ParosApp (PAROSV2 + ACRS + cat_componentes), audita la
 calidad del dato y produce tres niveles de análisis:

   1. PÉRDIDAS       Pareto de horas (no programado y programado por separado).
   2. EQUIPO         MTBF / MTTR / disponibilidad y tendencia Crow-AMSAA
                     (¿el equipo mejora o empeora?). Funciona con pocos datos.
   3. COMPONENTE     Weibull con datos censurados, intervalo de confianza de β,
                     intervalo óptimo de preventivo y ahorro esperado.
   + Vida de plato / navajas (exploratorio).

 Uso (desde la carpeta analisis/):
   python analisis_paros.py --xlsx "Base de Datos.xlsx"     # libro descargado
   python analisis_paros.py --sheets                        # directo del Sheet
   python analisis_paros.py --csv paros.csv [--componentes cat.csv]
 Opciones:
   --min-fallas 8      fallas mínimas para marcar un Weibull como CONFIABLE
   --razon-costo 5     costo de una falla / costo de un preventivo
   --ahorro-min 0.10   ahorro mínimo para recomendar preventivo por edad

 Salidas en ./salidas_analisis/:
   reporte_confiabilidad.xlsx   todas las tablas, una pestaña cada una
   resumen.txt                  lectura ejecutiva
   *.csv                        las mismas tablas sueltas

 Reglas de clasificación (por COMPONENTE, una por cierre de ACRS):
   Reemplazo  + paro NO programado  -> FALLA       (cierra una vida, observada)
   Reemplazo  + paro programado     -> PREVENTIVO  (cierra una vida, CENSURADA)
   Reparación                       -> REPARACIÓN  (no reinicia la vida)
   Ajuste / Revisión / Diagnóstico  -> sin efecto en la vida del componente
================================================================================
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------
# 1) CONFIGURACIÓN
# ------------------------------------------------------------------------------
HEADER_TO_FIELD = {
    "TIMESTAMP": "timestamp", "ÁREA": "area", "TURNO": "turno", "LÍNEA": "linea",
    "EQUIPO / ÁREA AFECTADA": "equipo", "MOTIVO DE PARO": "motivo",
    "DESCRIPCIÓN DEL PARO": "descripcion",
    "HORA DE INICIO (PARO PROGRAMADO)": "ini_prog",
    "HORA DE FINALIZACIÓN (PARO PROGRAMADO)": "fin_prog",
    "DURACIÓN (PARO PROGRAMADO)": "dur_prog",
    "HORA DE INICIO (PARO NO PROGRAMADO)": "ini_noprog",
    "HORA DE FINALIZACIÓN (PARO NO PROGRAMADO)": "fin_noprog",
    "DURACIÓN (PARO NO PROGRAMADO)": "dur_noprog",
    "ID_PARO": "id_paro", "¿NECESITA ACR?": "necesita_acr",
    "ORDEN DE TRABAJO": "orden_trabajo", "CAUSA RAÍZ": "causa_raiz",
    "COMPONENTE": "componente", "ACCIÓN REALIZADA": "accion",
    "REFACCIÓN": "refaccion", "TIPO DE INTERVENCIÓN": "tipo_intervencion",
    "PARO_PADRE": "paro_padre", "ES_CONTINUACION": "es_continuacion",
    "PARO_EN_CURSO": "paro_en_curso",
}
ACR_HEADER_TO_FIELD = {
    "ID_PARO": "id_paro", "EMPRESA": "empresa", "ORDEN_TRABAJO": "orden_trabajo",
    "CAUSA_RAIZ": "causa_raiz", "COMPONENTE": "componente",
    "TIPO_INTERVENCION": "tipo_intervencion", "ACCION": "accion",
    "REFACCION": "refaccion", "INI_INT": "ini_int", "FIN_INT": "fin_int",
    "DUR_INT": "dur_int", "FIRMA_PRODUCCION": "firma_produccion",
    "TIMESTAMP": "timestamp_acr",
}

# Motivos que cuentan como FALLA DEL EQUIPO (sistema reparable).
# Sin acentos: se comparan normalizados. «Espera de Refacción» NO es una falla
# nueva (es la misma falla esperando pieza): suma tiempo, no eventos.
MOTIVOS_FALLA_EQUIPO = {"MTTTO CORRECTIVO", "INSTRUMENTACION", "INTERVENCION TECNICA"}
MOTIVOS_ESPERA = {"ESPERA DE REFACCION"}
MOTIVOS_PLATO = re.compile(r"PLATO|NAVAJA|DADO")

# Marcador que escribe la app cuando una intervención no lleva componente.
SIN_COMPONENTE = {"", "—", "-", "(SIN COMPONENTE)"}

CARPETA_SALIDA = "salidas_analisis"
LINEA_AMBAS = "LINEA 1 Y 2"


# ------------------------------------------------------------------------------
# 2) UTILIDADES
# ------------------------------------------------------------------------------
def _norm(texto) -> str:
    s = "" if texto is None else str(texto)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split()).strip().upper()


def hhmm_a_horas(valor) -> float:
    """'1:30' / '01:30:00' / '26:15' -> horas. Vacío o basura -> 0."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return 0.0
    s = str(valor).strip()
    if not s:
        return 0.0
    if ":" in s:
        try:
            p = s.split(":")
            return int(p[0]) + int(p[1]) / 60
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _hora(valor):
    """'05:34' / '5:34:00' -> (5, 34) o None."""
    s = str(valor or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if h < 24 and mi < 60 else None


def _texto(df, col):
    return df[col].fillna("").astype(str).str.strip() if col in df.columns \
        else pd.Series("", index=df.index)


def _es_si(serie):
    return serie.fillna("").astype(str).str.strip().str.upper().isin({"SÍ", "SI"})


# ------------------------------------------------------------------------------
# 3) CARGA
# ------------------------------------------------------------------------------
def _renombrar(df: pd.DataFrame, mapa: dict) -> pd.DataFrame:
    df = df.loc[:, [str(c).strip() != "" and not str(c).startswith("Unnamed")
                    for c in df.columns]].copy()
    inverso = {_norm(k): v for k, v in mapa.items()}
    return df.rename(columns={c: inverso.get(_norm(c), c) for c in df.columns})


def _limpiar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("").astype(str)
    return df[df.apply(lambda r: any(v.strip() for v in r), axis=1)]


def _catalogo(df: pd.DataFrame) -> dict:
    """cat_componentes -> {COMPONENTE_normalizado: [equipos]}."""
    if df is None or df.empty:
        return {}
    cols = {_norm(c): c for c in df.columns}
    if "COMPONENTE" not in cols or "EQUIPO" not in cols:
        return {}
    out = {}
    for _, r in df.iterrows():
        comp = _norm(r[cols["COMPONENTE"]])
        if comp:
            eq = str(r[cols["EQUIPO"]]).strip()
            if eq and eq not in out.setdefault(comp, []):
                out[comp].append(eq)
    return out


def equipo_de_componente(catalogo: dict, comp: str, equipo_paro: str) -> str:
    """Equipo del catálogo; si el componente existe en varios, manda el del paro."""
    eqs = catalogo.get(_norm(comp), [])
    for e in eqs:
        if _norm(e) == _norm(equipo_paro):
            return e
    return eqs[0] if eqs else ""


def cargar_desde_xlsx(ruta: str):
    hojas = pd.read_excel(ruta, sheet_name=None, dtype=str)
    paros = _renombrar(_limpiar(hojas["PAROSV2"]), HEADER_TO_FIELD)
    acrs = _renombrar(_limpiar(hojas["ACRS"]), ACR_HEADER_TO_FIELD) \
        if "ACRS" in hojas else pd.DataFrame()
    cat = _catalogo(_limpiar(hojas["cat_componentes"])) \
        if "cat_componentes" in hojas else {}
    return paros, acrs, cat


def cargar_desde_sheets():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        "service_account.json",  # NUNCA subir este archivo al repo
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_KEY"])

    def _hoja(nombre):
        try:
            vals = sh.worksheet(nombre).get_all_values()
        except Exception:
            return pd.DataFrame()
        if not vals:
            return pd.DataFrame()
        return _limpiar(pd.DataFrame(vals[1:], columns=[str(h).strip() for h in vals[0]]))

    paros = _renombrar(_hoja(os.environ.get("HOJA_PAROS", "PAROSV2")), HEADER_TO_FIELD)
    acrs = _renombrar(_hoja(os.environ.get("HOJA_ACRS", "ACRS")), ACR_HEADER_TO_FIELD)
    return paros, acrs, _catalogo(_hoja("cat_componentes"))


def cargar_desde_csv(ruta: str, ruta_cat: str | None = None):
    """
    CSV de la vista Exportar: trae el paro repetido una vez por cada cierre
    de ACRS. Se separa de nuevo en (paros, acrs).
    """
    df = _renombrar(_limpiar(pd.read_csv(ruta, dtype=str)), HEADER_TO_FIELD)
    cols_paro = [c for c in df.columns if c in HEADER_TO_FIELD.values()]
    paros = df[cols_paro].drop_duplicates("id_paro")
    acrs = pd.DataFrame()
    if "empresa" in df.columns:
        acrs = df[_texto(df, "empresa") != ""][
            [c for c in ACR_HEADER_TO_FIELD.values() if c in df.columns]]
    cat = _catalogo(_limpiar(pd.read_csv(ruta_cat, dtype=str))) if ruta_cat else {}
    return paros, acrs, cat


# ------------------------------------------------------------------------------
# 4) EVENTOS: tramos consolidados + inicio/fin reales
# ------------------------------------------------------------------------------
def construir_eventos(paros: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Un renglón por EVENTO. Los tramos hijo suman su duración al padre. Un hijo
    cuyo padre no existe se conserva como evento propio (antes se perdía).

    inicio = fecha del TIMESTAMP + HORA DE INICIO. Si la hora de inicio es
    mayor que la hora de captura, el paro empezó el día anterior.
    fin    = inicio + duración total del evento.
    """
    df = paros.copy()
    for c in ("dur_prog", "dur_noprog", "ini_prog", "ini_noprog", "id_paro",
              "paro_padre", "es_continuacion", "timestamp", "motivo", "linea",
              "equipo", "area", "descripcion", "necesita_acr"):
        if c not in df.columns:
            df[c] = ""
    df["id_paro"] = _texto(df, "id_paro")
    df["h_prog"] = df["dur_prog"].apply(hhmm_a_horas)
    df["h_noprog"] = df["dur_noprog"].apply(hhmm_a_horas)

    es_hijo = _es_si(df["es_continuacion"])
    ids = set(df.loc[~es_hijo, "id_paro"])
    padre = _texto(df, "paro_padre")
    huerfano = es_hijo & ~padre.isin(ids)
    hijos = df[es_hijo & ~huerfano]
    ev = df[~es_hijo | huerfano].copy()

    extra = (hijos["h_prog"] + hijos["h_noprog"]).groupby(padre[hijos.index]).sum()
    ev["h_tramos"] = ev["id_paro"].map(extra).fillna(0.0)
    ev["n_tramos"] = 1 + ev["id_paro"].map(padre[hijos.index].value_counts()).fillna(0).astype(int)
    usa_prog = ev["h_prog"] > 0
    ev.loc[usa_prog, "h_prog"] += ev.loc[usa_prog, "h_tramos"]
    ev.loc[~usa_prog, "h_noprog"] += ev.loc[~usa_prog, "h_tramos"]
    ev["horas"] = ev["h_prog"] + ev["h_noprog"]

    ev["motivo_n"] = ev["motivo"].apply(_norm)
    ev["linea_n"] = ev["linea"].apply(_norm)
    ev["equipo_n"] = ev["equipo"].apply(_norm)
    # Programado: por columna Y por motivo (hay preventivos capturados en la
    # columna de no programado).
    ev["programado"] = (ev["h_prog"] > 0) | ev["motivo_n"].str.contains(
        "PREVENTIVO|PROGRAMADO", regex=True)
    ev["tipo"] = np.where(ev["programado"], "PROGRAMADO", "NO PROGRAMADO")

    ts = pd.to_datetime(ev["timestamp"], errors="coerce")
    inicios = []
    for t, a, b in zip(ts, ev["ini_noprog"], ev["ini_prog"]):
        hm = _hora(a) or _hora(b)
        if pd.isna(t):
            inicios.append(pd.NaT)
            continue
        if hm is None:
            inicios.append(t)
            continue
        ini = t.normalize() + timedelta(hours=hm[0], minutes=hm[1])
        if ini > t + timedelta(minutes=30):
            ini -= timedelta(days=1)
        inicios.append(ini)
    ev["inicio"] = pd.to_datetime(inicios)
    ev["fin"] = ev["inicio"] + pd.to_timedelta(ev["horas"], unit="h")
    ev["fecha"] = ev["inicio"]

    info = {"filas": len(df), "eventos": len(ev), "hijos": int(es_hijo.sum()),
            "huerfanos": int(huerfano.sum()),
            "sin_fecha": int(ev["inicio"].isna().sum())}
    return ev.reset_index(drop=True), info


# ------------------------------------------------------------------------------
# 5) RELOJ DE OPERACIÓN POR LÍNEA (unión de intervalos de paro)
# ------------------------------------------------------------------------------
class RelojOperacion:
    """
    Horas en que la línea estuvo corriendo = calendario − UNIÓN de paros.
    La unión evita restar dos veces cuando dos paros se traslapan (p. ej.
    molienda y extrusión parados a la vez). Un paro «Línea 1 y 2» detiene
    ambas líneas.
    """

    def __init__(self, eventos: pd.DataFrame):
        ev = eventos.dropna(subset=["inicio"])
        ev = ev[ev["horas"] > 0]
        self.t0 = eventos["inicio"].min()
        self.tf = eventos["fin"].max()
        self.int = {}
        lineas = {l for l in ev["linea_n"].unique() if l and l != LINEA_AMBAS}
        for ln in lineas:
            sel = ev[ev["linea_n"].isin([ln, LINEA_AMBAS])]
            self.int[ln] = self._unir(list(zip(sel["inicio"], sel["fin"])))

    @staticmethod
    def _unir(tramos):
        tramos = sorted(tramos)
        out = []
        for a, b in tramos:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out

    def _linea(self, ln):
        ln = _norm(ln)
        if ln == LINEA_AMBAS or ln not in self.int:
            # «Línea 1 y 2» o línea desconocida: se usa la primera disponible.
            return next(iter(sorted(self.int)), None)
        return ln

    def paro_entre(self, ln, a, b) -> float:
        ln = self._linea(ln)
        if ln is None or pd.isna(a) or pd.isna(b) or b <= a:
            return 0.0
        tot = 0.0
        for x, y in self.int[ln]:
            if y <= a:
                continue
            if x >= b:
                break
            tot += (min(y, b) - max(x, a)).total_seconds()
        return tot / 3600.0

    def operacion_entre(self, ln, a, b) -> float:
        if pd.isna(a) or pd.isna(b) or b <= a:
            return 0.0
        cal = (b - a).total_seconds() / 3600.0
        return max(cal - self.paro_entre(ln, a, b), 0.0)

    def reloj(self, ln, t) -> float:
        """Horas de operación acumuladas desde el inicio de los datos hasta t."""
        return self.operacion_entre(ln, self.t0, t)

    def fraccion_operando(self, ln) -> float:
        cal = (self.tf - self.t0).total_seconds() / 3600.0
        return self.operacion_entre(ln, self.t0, self.tf) / cal if cal > 0 else 0.0


# ------------------------------------------------------------------------------
# 6) CIERRES DE MANTENIMIENTO: una fila por componente intervenido
# ------------------------------------------------------------------------------
_JERARQUIA = ["REEMPLAZO", "REPARACION", "AJUSTE", "REVISION"]


def _clase_tipo(tipo_n: str) -> str:
    for k in _JERARQUIA:
        if k in tipo_n:
            return k
    return "OTRO" if tipo_n else ""


def emparejar(comp_str: str, tipo_str: str) -> tuple[list, bool]:
    """
    Empareja 'A | B' con 'Reemplazo | Ajuste'. Versiones anteriores de la app
    omitían el componente vacío de una Revisión, así que las listas pueden no
    medir lo mismo: se quitan Revisiones sin componente hasta que cuadren.
    Devuelve ([(componente, tipo), ...], desalineado).
    """
    comps = [c.strip() for c in str(comp_str).split("|")] if str(comp_str).strip() else []
    comps = ["" if _norm(c) in SIN_COMPONENTE else c for c in comps]
    tipos = [t.strip() for t in str(tipo_str).split("|")] if str(tipo_str).strip() else []
    if not tipos:
        return [(c, "") for c in comps] or [("", "")], False
    if len(comps) == len(tipos):
        return list(zip(comps, tipos)), False
    if len(tipos) == 1:
        return [(c, tipos[0]) for c in comps] or [("", tipos[0])], False
    sin_comp, t = [], list(tipos)
    while len(t) > len(comps):
        idx = next((i for i in range(len(t) - 1, -1, -1)
                    if _clase_tipo(_norm(t[i])) == "REVISION"), None)
        if idx is None:
            break
        sin_comp.append(("", t.pop(idx)))
    if len(t) == len(comps):
        return list(zip(comps, t)) + sin_comp, False
    dom = min(tipos, key=lambda x: _JERARQUIA.index(_clase_tipo(_norm(x)))
              if _clase_tipo(_norm(x)) in _JERARQUIA else 9)
    return [(c, dom) for c in comps] or [("", dom)], True


def construir_cierres(eventos: pd.DataFrame, acrs: pd.DataFrame,
                      paros: pd.DataFrame, catalogo: dict) -> pd.DataFrame:
    filas = []
    fuentes = []
    if acrs is not None and not acrs.empty and "id_paro" in acrs.columns:
        a = acrs.copy()
        for c in ("empresa", "componente", "tipo_intervencion", "causa_raiz", "dur_int"):
            a[c] = _texto(a, c)
        a["id_paro"] = _texto(a, "id_paro")
        fuentes.append(a)
    # Columnas legacy de PAROSV2 (paros sin ningún cierre en ACRS)
    if "componente" in paros.columns:
        con_acr = set(fuentes[0]["id_paro"]) if fuentes else set()
        leg = paros[(_texto(paros, "componente") != "")
                    & ~_texto(paros, "id_paro").isin(con_acr)].copy()
        if not leg.empty:
            for c in ("tipo_intervencion", "causa_raiz"):
                leg[c] = _texto(leg, c)
            leg["empresa"], leg["dur_int"] = "LEGACY", ""
            fuentes.append(leg)

    ev = eventos.set_index("id_paro")
    for fuente in fuentes:
        for _, r in fuente.iterrows():
            pid = str(r["id_paro"]).strip()
            if pid not in ev.index:
                continue
            e = ev.loc[pid]
            if isinstance(e, pd.DataFrame):
                e = e.iloc[0]
            pares, desal = emparejar(r["componente"], r["tipo_intervencion"])
            for comp, tipo in pares:
                clase = _clase_tipo(_norm(tipo))
                if clase == "REEMPLAZO":
                    evento = "PREVENTIVO" if e["programado"] else "FALLA"
                elif clase == "REPARACION":
                    evento = "REPARACIÓN"
                elif clase == "":
                    # Sin tipo (dato viejo): correctivo con componente = falla.
                    evento = ("FALLA (supuesta)" if comp and not e["programado"]
                              and e["motivo_n"] in MOTIVOS_FALLA_EQUIPO else "SIN TIPO")
                else:
                    evento = "SIN EFECTO EN VIDA"
                eq_cat = equipo_de_componente(catalogo, comp, e["equipo"]) if comp else ""
                filas.append({
                    "id_paro": pid, "empresa": r["empresa"],
                    "inicio": e["inicio"], "fin": e["fin"],
                    "linea": e["linea"], "linea_n": e["linea_n"],
                    "equipo_paro": e["equipo"],
                    "equipo": eq_cat or e["equipo"],
                    "equipo_de_catalogo": bool(eq_cat),
                    "componente": comp, "componente_n": _norm(comp),
                    "tipo_intervencion": tipo, "evento": evento,
                    "motivo": e["motivo"], "programado": bool(e["programado"]),
                    "horas_paro": e["horas"], "horas_interv": hhmm_a_horas(r["dur_int"]),
                    "causa_raiz": r.get("causa_raiz", ""),
                    "desalineado": desal,
                })
    return pd.DataFrame(filas)


# ------------------------------------------------------------------------------
# 7) WEIBULL CON CENSURA
# ------------------------------------------------------------------------------
def ajustar_weibull(fallas, censuras=()):
    """
    Weibull 2P por máxima verosimilitud con censura por la derecha.

    Con pocas fallas el β de máxima verosimilitud sale inflado (con 4 fallas
    puramente aleatorias, β=1, suele salir ≈1.3–1.5 y "parece" desgaste).
    Por eso:
      · β se corrige por sesgo:  β_U = β · (r − 2) / (r − 0.68), r = n.º fallas
      · el IC 90 % de β es por razón de verosimilitud (perfil), escalado por la
        misma corrección. Validado por simulación: con β real = 1 declara
        "desgaste" (límite inferior > 1) solo ≈5 % de las veces, con 3 a 15 fallas.
    Devuelve dict(beta, eta, beta_lo, beta_hi, beta_mle).
    """
    from scipy.optimize import brentq, minimize_scalar
    from scipy.stats import chi2

    f = np.asarray([x for x in fallas if x > 0], float)
    c = np.asarray([x for x in censuras if x > 0], float)
    r = len(f)
    if r < 2:
        return None
    escala = float(np.mean(np.concatenate([f, c])))   # evita desbordes numéricos
    fs, cs = f / escala, c / escala
    sum_log_f = float(np.sum(np.log(fs)))

    from scipy.special import logsumexp
    log_t = np.log(np.concatenate([fs, cs]))

    def perfil(lb):
        """−log-verosimilitud con η ya optimizado para este β (en escala log)."""
        b = math.exp(lb)
        log_s = float(logsumexp(b * log_t))           # log Σ t^β, sin desbordes
        nll = -(r * math.log(b) - r * (log_s - math.log(r)) + (b - 1) * sum_log_f - r)
        return nll, (log_s - math.log(r)) / b          # (nll, log η)

    res = minimize_scalar(lambda lb: perfil(lb)[0], bounds=(-4, 4), method="bounded")
    lb0, nll0 = float(res.x), float(res.fun)
    b_mle, eta = math.exp(lb0), math.exp(perfil(lb0)[1]) * escala
    k = (r - 2) / (r - 0.68) if r > 2 else 1.0

    crit = chi2.ppf(0.90, 1) / 2
    g = lambda lb: perfil(lb)[0] - nll0 - crit
    lo = math.exp(brentq(g, -8, lb0)) if g(-8) > 0 else 0.0
    hi = math.exp(brentq(g, lb0, 8)) if g(8) > 0 else float("inf")
    return {"beta": b_mle * k, "eta": eta, "beta_lo": lo * k, "beta_hi": hi * k,
            "beta_mle": b_mle}


def _costo_por_hora(T, beta, eta, razon):
    from scipy.integrate import quad
    R = math.exp(-((T / eta) ** beta))
    vida = quad(lambda t: math.exp(-((t / eta) ** beta)), 0, T)[0]
    return (1.0 * R + razon * (1 - R)) / max(vida, 1e-9)


def intervalo_optimo(beta: float, eta: float, razon_costo: float = 5.0):
    """
    Reemplazo por edad: T que minimiza costo por hora. Devuelve (T, ahorro),
    ahorro = 1 − costo(T) / costo de correr hasta la falla. Con β ≤ 1 no hay
    intervalo que convenga (devuelve inf, 0).
    """
    if beta <= 1:
        return float("inf"), 0.0
    from scipy.optimize import minimize_scalar
    res = minimize_scalar(lambda T: _costo_por_hora(T, beta, eta, razon_costo),
                          bounds=(eta * 0.02, eta * 3.0), method="bounded")
    mttf = eta * math.gamma(1 + 1 / beta)
    c_rtf = razon_costo / mttf
    return float(res.x), max(0.0, 1 - res.fun / c_rtf)


def diagnostico_beta(beta, lo, hi) -> str:
    if lo > 1:
        return "Desgaste (β > 1 con 90 % de confianza)"
    if hi < 1:
        return "Mortalidad infantil (β < 1): revisar montaje, calidad de refacción"
    return "Sin evidencia de desgaste (el IC de β incluye 1)"


def historial_vidas(cierres: pd.DataFrame, reloj: RelojOperacion) -> pd.DataFrame:
    """
    Por (línea, equipo, componente): cada renovación (FALLA o PREVENTIVO)
    cierra una vida. La vida va del FIN de la renovación anterior al INICIO
    de la actual, en horas de OPERACIÓN de la línea.
      - termina en FALLA       -> vida observada
      - termina en PREVENTIVO  -> vida censurada (no llegó a fallar)
      - la vida en curso       -> censurada a la fecha de corte
    La vida anterior a la primera renovación se desconoce y no se usa.
    """
    if cierres.empty:
        return pd.DataFrame()
    ren = cierres[cierres["evento"].isin(["FALLA", "FALLA (supuesta)", "PREVENTIVO"])
                  & (cierres["componente_n"] != "") & cierres["inicio"].notna()]
    filas = []
    for (ln, eq, comp), g in ren.groupby(["linea_n", "equipo", "componente_n"]):
        g = g.sort_values("inicio").drop_duplicates("id_paro")
        nombre = g["componente"].iloc[0]
        for prev, cur in zip(g.iloc[:-1].itertuples(), g.iloc[1:].itertuples()):
            filas.append({
                "linea": cur.linea, "equipo": eq, "componente": nombre,
                "desde": prev.fin, "hasta": cur.inicio,
                "vida_oper_h": round(reloj.operacion_entre(ln, prev.fin, cur.inicio), 1),
                "vida_cal_h": round(max((cur.inicio - prev.fin).total_seconds() / 3600, 0), 1),
                "estado": "FALLA" if cur.evento.startswith("FALLA") else "CENSURADA (preventivo)",
                "id_paro_cierre": cur.id_paro,
                "horas_paro": round(cur.horas_paro, 2),
                "horas_interv": round(cur.horas_interv, 2),
            })
        ult = g.iloc[-1]
        filas.append({
            "linea": ult["linea"], "equipo": eq, "componente": nombre,
            "desde": ult["fin"], "hasta": reloj.tf,
            "vida_oper_h": round(reloj.operacion_entre(ln, ult["fin"], reloj.tf), 1),
            "vida_cal_h": round(max((reloj.tf - ult["fin"]).total_seconds() / 3600, 0), 1),
            "estado": "CENSURADA (sigue operando)", "id_paro_cierre": "",
            "horas_paro": np.nan, "horas_interv": np.nan,
        })
    return pd.DataFrame(filas)


def analizar_weibull(vidas: pd.DataFrame, reloj: RelojOperacion, min_fallas=8,
                     razon_costo=5.0, ahorro_min=0.10) -> pd.DataFrame:
    if vidas.empty:
        return pd.DataFrame()
    filas = []
    for (eq, comp), g in vidas.groupby(["equipo", "componente"]):
        f = g.loc[g["estado"] == "FALLA", "vida_oper_h"].to_numpy(float)
        c = g.loc[g["estado"] != "FALLA", "vida_oper_h"].to_numpy(float)
        f = f[f > 0]
        base = {"equipo": eq, "componente": comp, "lineas": ", ".join(sorted(g["linea"].unique())),
                "n_fallas": len(f), "n_censuradas": int((c > 0).sum())}
        if len(f) < 3:
            filas.append({**base, "modelo": "SIN AJUSTE",
                          "recomendacion": f"Faltan datos: {len(f)} vida(s) hasta falla observada(s); "
                                           "se necesitan ≥ 3"})
            continue
        w = ajustar_weibull(f, c)
        T, ahorro = intervalo_optimo(w["beta"], w["eta"], razon_costo)
        mttf = w["eta"] * math.gamma(1 + 1 / w["beta"])
        if w["beta_lo"] <= 1:
            rec = "No programar preventivo por edad; usar inspección / monitoreo de condición"
            T_txt = None
        elif ahorro < ahorro_min:
            rec = f"Preventivo por edad ahorra solo {ahorro:.0%}: no compensa"
            T_txt = None
        else:
            frac = reloj.fraccion_operando(g["linea"].iloc[0])
            dias = T / 24 / frac if frac > 0 else float("nan")
            rec = f"Preventivo cada {T:,.0f} h de operación (≈ {dias:.0f} días calendario)"
            T_txt = round(T, 0)
        filas.append({
            **base,
            "modelo": "CONFIABLE" if len(f) >= min_fallas else "PROVISIONAL",
            "beta": round(w["beta"], 2), "beta_IC90": f"{w['beta_lo']:.2f} – {w['beta_hi']:.2f}",
            "eta_h": round(w["eta"], 1), "vida_media_h": round(mttf, 1),
            "diagnostico": diagnostico_beta(w["beta"], w["beta_lo"], w["beta_hi"]),
            "intervalo_preventivo_h": T_txt,
            "R_en_intervalo": round(math.exp(-((T / w["eta"]) ** w["beta"])), 3) if T_txt else None,
            "ahorro_vs_correr_a_falla": f"{ahorro:.0%}" if math.isfinite(T) else "0%",
            "recomendacion": rec,
        })
    out = pd.DataFrame(filas)
    return out.sort_values(["n_fallas", "n_censuradas"], ascending=False)


# ------------------------------------------------------------------------------
# 8) SISTEMA REPARABLE POR EQUIPO: MTBF / MTTR / Crow-AMSAA
# ------------------------------------------------------------------------------
def crow_amsaa(tiempos, T):
    """β de Crow-AMSAA (truncado por tiempo) y p-valor de H0: β = 1."""
    from scipy.stats import chi2
    t = np.asarray([x for x in tiempos if 0 < x < T], float)
    n = len(t)
    if n < 4:
        return None, None
    s = float(np.sum(np.log(T / t)))
    beta = n / s
    stat = 2 * s
    p = 2 * min(chi2.cdf(stat, 2 * n), chi2.sf(stat, 2 * n))
    return beta, p


def analisis_equipos(eventos: pd.DataFrame, cierres: pd.DataFrame,
                     reloj: RelojOperacion) -> pd.DataFrame:
    ev = eventos.dropna(subset=["inicio"])
    fallas = ev[ev["motivo_n"].isin(MOTIVOS_FALLA_EQUIPO) & ~ev["programado"]]
    esperas = ev[ev["motivo_n"].isin(MOTIVOS_ESPERA)]
    interv = (cierres.drop_duplicates(["id_paro", "empresa"])
                     .groupby("id_paro")["horas_interv"].max()) if not cierres.empty else pd.Series(dtype=float)
    filas = []
    for (ln, eq), g in fallas.groupby(["linea", "equipo"]):
        if not str(eq).strip():
            continue
        T = reloj.reloj(ln, reloj.tf)
        n = len(g)
        mtbf = T / n if n else float("nan")
        mttr = g["horas"].mean()
        h_int = g["id_paro"].map(interv).dropna()
        h_int = h_int[h_int > 0]
        esp = esperas[(esperas["linea"] == ln) & (esperas["equipo"] == eq)]["horas"].sum()
        b, p = crow_amsaa([reloj.reloj(ln, t) for t in g["inicio"]], T)
        if b is None:
            tend = "Pocos eventos (< 4)"
        elif p < 0.10:
            tend = "EMPEORANDO (fallas cada vez más seguidas)" if b > 1 else "MEJORANDO (fallas cada vez más espaciadas)"
        else:
            tend = "Estable (sin tendencia significativa)"
        filas.append({
            "linea": ln, "equipo": eq, "fallas": n,
            "horas_operacion": round(T, 0),
            "MTBF_h": round(mtbf, 1),
            "MTTR_paro_h": round(mttr, 2),
            "MTTR_mtto_h": round(h_int.mean(), 2) if len(h_int) else None,
            "fallas_con_ACR": f"{len(h_int)}/{n}",
            "horas_espera_refaccion": round(esp, 1),
            "disponibilidad_inherente": f"{mtbf / (mtbf + mttr):.1%}" if n else "",
            "beta_CrowAMSAA": round(b, 2) if b else None,
            "p_valor": round(p, 3) if p is not None else None,
            "tendencia": tend,
        })
    out = pd.DataFrame(filas)
    return out.sort_values("fallas", ascending=False) if not out.empty else out


# ------------------------------------------------------------------------------
# 9) PLATO / NAVAJAS (exploratorio)
# ------------------------------------------------------------------------------
_CAUSAS_PLATO = [
    ("Desgaste / daño", r"DESGAST|GASTAD|CHUEC|ROT[OA]|QUEBR|DESPOSTILL|FILO"),
    ("Taponamiento", r"TAP[OÓAE]|OBSTRU|DURA"),
    ("Calidad / figura", r"CALIDAD|FIGURA|DEFORM|EXPANSI|TAMA|LARG|CORT[OA]S? "),
    ("Cambio de producto", r"PRODUCTO|FORMULA|SKU|ORDEN"),
]


def _causa_plato(txt: str) -> str:
    t = _norm(txt)
    for nombre, patron in _CAUSAS_PLATO:
        if re.search(patron, t):
            return nombre
    return "Sin causa en la descripción"


def vida_plato(eventos: pd.DataFrame, reloj: RelojOperacion):
    ev = eventos[eventos["motivo_n"].str.contains(MOTIVOS_PLATO) & eventos["inicio"].notna()]
    ev = ev.sort_values("inicio")
    det, res = [], []
    for ln, g in ev.groupby("linea"):
        # cambios a menos de 2 h uno de otro = mismo cambio capturado en partes
        grupos, actual = [], None
        for r in g.itertuples():
            if actual is not None and r.inicio - actual["fin"] <= timedelta(hours=2):
                actual["fin"] = max(actual["fin"], r.fin)
                actual["horas"] += r.horas
                actual["desc"] += " / " + str(r.descripcion)
            else:
                actual = {"inicio": r.inicio, "fin": r.fin, "horas": r.horas,
                          "desc": str(r.descripcion)}
                grupos.append(actual)
        for prev, cur in zip(grupos[:-1], grupos[1:]):
            det.append({"linea": ln, "cambio": cur["inicio"],
                        "horas_oper_desde_cambio_anterior":
                            round(reloj.operacion_entre(ln, prev["fin"], cur["inicio"]), 1),
                        "causa_detectada": _causa_plato(cur["desc"]),
                        "duracion_cambio_h": round(cur["horas"], 2),
                        "descripcion": cur["desc"][:200]})
    det = pd.DataFrame(det)
    if det.empty:
        return det, det
    for ln, g in det.groupby("linea"):
        v = g["horas_oper_desde_cambio_anterior"]
        res.append({"linea": ln, "cambios": len(g) + 1,
                    "vida_mediana_h": round(v.median(), 1),
                    "vida_P25_h": round(v.quantile(.25), 1),
                    "vida_P75_h": round(v.quantile(.75), 1),
                    "duracion_media_cambio_min": round(g["duracion_cambio_h"].mean() * 60, 0),
                    "% sin causa": f"{(g['causa_detectada'] == 'Sin causa en la descripción').mean():.0%}",
                    "% desgaste": f"{(g['causa_detectada'] == 'Desgaste / daño').mean():.0%}"})
    return det, pd.DataFrame(res)


# ------------------------------------------------------------------------------
# 10) PARETO + AUDITORÍA
# ------------------------------------------------------------------------------
def pareto(df: pd.DataFrame, columna: str, valor: str = "horas") -> pd.DataFrame:
    g = df.groupby(columna)[valor].sum().sort_values(ascending=False).reset_index()
    g = g[g[valor] > 0]
    tot = g[valor].sum()
    g[valor] = g[valor].round(1)
    g["%"] = (g[valor] / tot * 100).round(1) if tot else 0
    g["% acumulado"] = g["%"].cumsum().round(1)
    return g


def pareto_componentes(cierres: pd.DataFrame) -> pd.DataFrame:
    c = cierres[cierres["evento"].isin(["FALLA", "FALLA (supuesta)", "REPARACIÓN"])
                & (cierres["componente_n"] != "")].copy()
    if c.empty:
        return pd.DataFrame()
    # Un paro con 2 componentes reparte sus horas: no se cuentan dos veces.
    n = c.groupby("id_paro")["componente"].transform("count")
    c["horas"] = c["horas_paro"] / n
    p = pareto(c, "componente")
    p.insert(1, "eventos", p["componente"].map(c.groupby("componente")["id_paro"].nunique()))
    return p


def auditoria(info, eventos, cierres, acrs, catalogo) -> pd.DataFrame:
    fallas_eq = eventos[eventos["motivo_n"].isin(MOTIVOS_FALLA_EQUIPO) & ~eventos["programado"]]
    ids_acr = set(_texto(acrs, "id_paro")) if acrs is not None and not acrs.empty else set()
    con_acr = fallas_eq["id_paro"].isin(ids_acr)
    c = cierres if not cierres.empty else pd.DataFrame(
        columns=["evento", "componente_n", "desalineado", "equipo_de_catalogo", "equipo", "equipo_paro"])
    con_comp = c[c["componente_n"] != ""]
    filas = [
        ("Filas en PAROSV2", info["filas"], ""),
        ("Eventos (tramos multiturno unidos)", info["eventos"], ""),
        ("Tramos hijo sin padre (se conservan como evento)", info["huerfanos"],
         "Revisar: el padre se borró o el ID no coincide" if info["huerfanos"] else "OK"),
        ("Eventos sin fecha válida", info["sin_fecha"], "OK" if not info["sin_fecha"] else "Revisar TIMESTAMP"),
        ("Fallas de equipo (correctivo / instrumentación)", len(fallas_eq), ""),
        ("  · con cierre en ACRS", int(con_acr.sum()),
         f"{con_acr.mean():.0%} — meta ≥ 90 %" if len(fallas_eq) else ""),
        ("Cierres ACRS (filas)", len(acrs) if acrs is not None else 0, ""),
        ("Intervenciones por componente", len(c), ""),
        ("  · FALLA (renueva la vida)", int(c["evento"].str.startswith("FALLA").sum()), ""),
        ("  · PREVENTIVO (renueva, censurada)", int((c["evento"] == "PREVENTIVO").sum()), ""),
        ("  · REPARACIÓN", int((c["evento"] == "REPARACIÓN").sum()), ""),
        ("  · Ajuste / Revisión (sin efecto en la vida)", int((c["evento"] == "SIN EFECTO EN VIDA").sum()), ""),
        ("Componente y tipo desalineados", int(c["desalineado"].sum()),
         "OK" if not c["desalineado"].any() else "Se usó el tipo dominante"),
        ("Componentes que NO están en cat_componentes", int((~con_comp["equipo_de_catalogo"]).sum()),
         "Texto libre: no se puede agrupar bien" if (~con_comp["equipo_de_catalogo"]).any() else "OK"),
        ("Componentes cuyo equipo ≠ equipo capturado por producción",
         int((con_comp["equipo_de_catalogo"] & (con_comp["equipo"].apply(_norm) != con_comp["equipo_paro"].apply(_norm))).sum()),
         "Se usa el equipo del catálogo"),
        ("Componentes distintos", con_comp["componente_n"].nunique(), ""),
    ]
    return pd.DataFrame(filas, columns=["Métrica", "Valor", "Comentario"])


# ------------------------------------------------------------------------------
# 11) ORQUESTACIÓN
# ------------------------------------------------------------------------------
def correr(paros, acrs, catalogo, min_fallas=8, razon_costo=5.0, ahorro_min=0.10) -> dict:
    eventos, info = construir_eventos(paros)
    reloj = RelojOperacion(eventos)
    cierres = construir_cierres(eventos, acrs, paros, catalogo)
    vidas = historial_vidas(cierres, reloj)
    plato_det, plato_res = vida_plato(eventos, reloj)
    nop = eventos[~eventos["programado"]]
    prog = eventos[eventos["programado"]]
    return {
        "Auditoria": auditoria(info, eventos, cierres, acrs, catalogo),
        "Pareto_no_programado": pareto(nop, "motivo"),
        "Pareto_programado": pareto(prog, "motivo"),
        "Pareto_componentes": pareto_componentes(cierres),
        "Equipos_MTBF_MTTR": analisis_equipos(eventos, cierres, reloj),
        "Weibull_componentes": analizar_weibull(vidas, reloj, min_fallas, razon_costo, ahorro_min),
        "Vidas_componentes": vidas,
        "Plato_navajas_resumen": plato_res,
        "Plato_navajas_detalle": plato_det,
        "Intervenciones": cierres,
        "_reloj": reloj,
    }


def resumen_texto(r: dict, args) -> str:
    rel = r["_reloj"]
    L = ["=" * 72, "RESUMEN — Análisis de confiabilidad de paros",
         f"Corrida: {datetime.now():%Y-%m-%d %H:%M} · Datos: {rel.t0:%d/%m/%Y} a {rel.tf:%d/%m/%Y}",
         f"Razón de costo falla/preventivo: {args.razon_costo} · Ahorro mínimo: {args.ahorro_min:.0%}",
         "=" * 72, "\n[1] CALIDAD DE DATOS"]
    for _, x in r["Auditoria"].iterrows():
        L.append(f"   {x['Métrica']}: {x['Valor']}" + (f"  ({x['Comentario']})" if x["Comentario"] else ""))
    L.append("\n[2] PÉRDIDAS NO PROGRAMADAS — top 5")
    for _, x in r["Pareto_no_programado"].head(5).iterrows():
        L.append(f"   {x['motivo']}: {x['horas']:.1f} h ({x['%']}%, acum {x['% acumulado']}%)")
    L.append("\n[3] EQUIPOS (sistema reparable)")
    eq = r["Equipos_MTBF_MTTR"]
    if eq.empty:
        L.append("   Sin fallas de equipo registradas.")
    for _, x in eq.head(8).iterrows():
        L.append(f"   {x['linea']} · {x['equipo']}: {x['fallas']} fallas, MTBF {x['MTBF_h']} h, "
                 f"MTTR {x['MTTR_paro_h']} h, disp. {x['disponibilidad_inherente']} → {x['tendencia']}")
    L.append("\n[4] COMPONENTES (Weibull con censura)")
    wb = r["Weibull_componentes"]
    if wb.empty:
        L.append("   Aún no hay componentes con dos o más renovaciones.")
    sin = wb[wb["modelo"] == "SIN AJUSTE"] if not wb.empty else wb
    if len(sin):
        L.append(f"   {len(sin)} componente(s) aún sin datos suficientes para Weibull; los más avanzados:")
    for _, x in pd.concat([wb[wb["modelo"] != "SIN AJUSTE"], sin.head(3)]).iterrows() if not wb.empty else []:
        if x["modelo"] == "SIN AJUSTE":
            L.append(f"   {x['equipo']} / {x['componente']}: {x['recomendacion']}")
        else:
            L.append(f"   {x['equipo']} / {x['componente']} [{x['modelo']}, {x['n_fallas']} fallas + "
                     f"{x['n_censuradas']} censuradas]: β={x['beta']} (IC90 {x['beta_IC90']}), "
                     f"η={x['eta_h']} h → {x['recomendacion']}")
    L.append("\n[5] PLATO / NAVAJAS (exploratorio)")
    for _, x in r["Plato_navajas_resumen"].iterrows():
        L.append(f"   {x['linea']}: {x['cambios']} cambios, vida mediana {x['vida_mediana_h']} h de operación "
                 f"(P25–P75 {x['vida_P25_h']}–{x['vida_P75_h']} h); sin causa en descripción: {x['% sin causa']}")
    L += ["\n[6] NOTAS",
          "   · Horas de operación = calendario − unión de paros de la línea (proxy hasta tener OEE).",
          "   · Un Weibull PROVISIONAL no debe usarse para fijar frecuencias; sirve para orientar.",
          "=" * 72]
    return "\n".join(L)


def guardar(r: dict, carpeta: str):
    os.makedirs(carpeta, exist_ok=True)
    ruta_x = os.path.join(carpeta, "reporte_confiabilidad.xlsx")
    with pd.ExcelWriter(ruta_x, engine="openpyxl") as xw:
        for nombre, df in r.items():
            if nombre.startswith("_") or not isinstance(df, pd.DataFrame):
                continue
            d = df.copy()
            for c in d.columns:
                if pd.api.types.is_datetime64_any_dtype(d[c]):
                    d[c] = d[c].dt.strftime("%Y-%m-%d %H:%M")
            d.to_excel(xw, sheet_name=nombre[:31], index=False)
            d.to_csv(os.path.join(carpeta, nombre.lower() + ".csv"), index=False, encoding="utf-8-sig")
            ws = xw.sheets[nombre[:31]]
            for i, c in enumerate(d.columns, 1):
                largo = max([len(str(c))] + [len(str(v)) for v in d[c].head(200)])
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(10, largo + 2), 60)
            ws.freeze_panes = "A2"
    return ruta_x


def main():
    ap = argparse.ArgumentParser(description="Análisis de confiabilidad de paros")
    ap.add_argument("--xlsx", help="Libro de Excel descargado del Sheet")
    ap.add_argument("--csv", help="CSV de la vista Exportar")
    ap.add_argument("--componentes", help="CSV de cat_componentes (solo con --csv)")
    ap.add_argument("--sheets", action="store_true", help="Leer de Google Sheets")
    ap.add_argument("--min-fallas", type=int, default=8)
    ap.add_argument("--razon-costo", type=float, default=5.0)
    ap.add_argument("--ahorro-min", type=float, default=0.10)
    ap.add_argument("--salida", default=CARPETA_SALIDA)
    args = ap.parse_args()

    if args.sheets:
        paros, acrs, cat = cargar_desde_sheets()
    elif args.xlsx:
        paros, acrs, cat = cargar_desde_xlsx(args.xlsx)
    elif args.csv:
        paros, acrs, cat = cargar_desde_csv(args.csv, args.componentes)
    else:
        sys.exit("Indica --xlsx RUTA, --csv RUTA o --sheets")

    r = correr(paros, acrs, cat, args.min_fallas, args.razon_costo, args.ahorro_min)
    ruta = guardar(r, args.salida)
    txt = resumen_texto(r, args)
    with open(os.path.join(args.salida, "resumen.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    print(f"\nReporte: {ruta}")


if __name__ == "__main__":
    main()
