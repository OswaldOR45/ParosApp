"""
================================================================================
 analisis_paros.py  —  Motor de análisis de confiabilidad (Etapa 4, provisional)
 Plan Maestro · Mantenimiento Preventivo · Planta Pet Food
--------------------------------------------------------------------------------
 Lee los datos capturados por ParosApp (Google Sheets / CSV exportado),
 los limpia, audita su calidad, calcula Pareto + MTBF/MTTR y produce un
 ajuste Weibull PROVISIONAL por componente con su intervalo óptimo de
 mantenimiento preventivo.

 Está pensado para RE-EJECUTARSE conforme crecen los datos (modelo vivo):
 cada corrida vuelve a leer la fuente, recalcula y reescribe los entregables.

 Uso:
   python analisis_paros.py --csv paros.csv
   python analisis_paros.py --sheets            # lee directo de Google Sheets
   python analisis_paros.py --csv paros.csv --min-fallas 6

 Salidas (carpeta ./salidas_analisis/):
   - auditoria_calidad.csv      estado de llenado de campos clave
   - pareto_motivos.csv         horas perdidas por motivo (regla 80/20)
   - pareto_componentes.csv     horas perdidas por componente
   - mtbf_mttr.csv              MTBF / MTTR por equipo-componente
   - historial_fallas.csv       INSUMO de Weibull (tiempo entre fallas)
   - weibull_resultados.csv     beta, eta, intervalo optimo, R(t)
   - resumen.txt                lectura ejecutiva de la corrida
================================================================================
"""
from __future__ import annotations

import argparse
import os
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------
# 1) CONFIGURACIÓN  (refleja config/settings.py de ParosApp)
# ------------------------------------------------------------------------------

# Encabezado EXACTO en la hoja  ->  clave interna estable que usa este script.
# Es el inverso de FIELD_TO_HEADER de la app. Empata por nombre normalizado,
# así que tolera acentos / mayúsculas / columnas reordenadas.
HEADER_TO_FIELD = {
    "TIMESTAMP":                              "timestamp",
    "ÁREA":                                   "area",
    "TURNO":                                  "turno",
    "LÍNEA":                                  "linea",
    "EQUIPO / ÁREA AFECTADA":                 "equipo",
    "MOTIVO DE PARO":                         "motivo",
    "DESCRIPCIÓN DEL PARO":                   "descripcion",
    "HORA DE INICIO (PARO PROGRAMADO)":       "ini_prog",
    "HORA DE FINALIZACIÓN (PARO PROGRAMADO)": "fin_prog",
    "DURACIÓN (PARO PROGRAMADO)":             "dur_prog",
    "HORA DE INICIO (PARO NO PROGRAMADO)":    "ini_noprog",
    "HORA DE FINALIZACIÓN (PARO NO PROGRAMADO)": "fin_noprog",
    "DURACIÓN (PARO NO PROGRAMADO)":          "dur_noprog",
    "ID_PARO":                                "id_paro",
    "¿NECESITA ACR?":                         "necesita_acr",
    "ORDEN DE TRABAJO":                       "orden_trabajo",
    "CAUSA RAÍZ":                             "causa_raiz",
    "COMPONENTE":                             "componente",
    "ACCIÓN REALIZADA":                       "accion",
    "REFACCIÓN":                              "refaccion",
    "TIPO DE INTERVENCIÓN":                   "tipo_intervencion",
}

# Motivos que SÍ representan una falla de componente (lo que mide Weibull).
# El resto (cambio de producto, falta de harina, tolvas llenas...) son paros
# operativos/logísticos y NO entran al modelo de confiabilidad.
MOTIVOS_FALLA = {
    "MTTTO CORRECTIVO",
    "AJUSTE DE NAVAJAS",
    "INSTRUMENTACIÓN",
    "INTERVENCIÓN TÉCNICO",
}

EQUIPOS_CRITICOS = {"EXTRUSOR", "SECADOR", "COATER"}

# Horas de producción programadas por día (3 turnos ~ continuo, menos comidas).
# Se usa SOLO como respaldo si aún no se integran las horas reales del OEE.
HORAS_OPER_POR_DIA = 22.0

CARPETA_SALIDA = "salidas_analisis"


# ------------------------------------------------------------------------------
# 2) UTILIDADES
# ------------------------------------------------------------------------------

def _norm(texto) -> str:
    """Normaliza para comparar: sin acentos, mayúsculas, sin espacios extra."""
    s = str(texto)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split()).strip().upper()


def hhmm_a_horas(valor) -> float:
    """'1:30' -> 1.5 ; '1.5' -> 1.5 ; '' -> 0.0  (tolerante)."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return 0.0
    s = str(valor).strip()
    if s == "":
        return 0.0
    if ":" in s:
        try:
            h, m = s.split(":")[:2]
            return round(int(h) + int(m) / 60, 4)
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# ------------------------------------------------------------------------------
# 3) CARGA DE DATOS
# ------------------------------------------------------------------------------

def cargar_desde_csv(ruta: str) -> pd.DataFrame:
    df = pd.read_csv(ruta, dtype=str).fillna("")
    return _renombrar_columnas(df)


def cargar_desde_sheets() -> pd.DataFrame:
    """Lee directo del Google Sheet (requiere credenciales tipo ParosApp)."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    # Ajusta esta ruta a tu service_account.json (NUNCA subir al repo).
    creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_KEY"])
    ws = sh.worksheet(os.environ.get("HOJA_PAROS", "PAROSV2"))
    df = pd.DataFrame(ws.get_all_records()).astype(str).fillna("")
    return _renombrar_columnas(df)


def _renombrar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    inverso = {_norm(k): v for k, v in HEADER_TO_FIELD.items()}
    df = df.rename(columns={c: inverso.get(_norm(c), c) for c in df.columns})

    # Excluir tramos hijos (ES_CONTINUACION == SÍ).
    # El análisis Weibull, MTBF/MTTR y Pareto deben trabajar sobre eventos
    # únicos. El padre ya acumula la duración total del evento multi-turno;
    # incluir hijos inflaría las frecuencias de falla y distorsionaría beta/eta.
    col_ec = next((c for c in df.columns if _norm(c) == _norm("ES_CONTINUACION")), None)
    if col_ec:
        _ec = df[col_ec].fillna("").str.strip().str.upper()
        df = df[~_ec.isin({"SÍ", "SI"})].copy()

    return df


# ------------------------------------------------------------------------------
# 4) NORMALIZACIÓN
# ------------------------------------------------------------------------------

def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Fecha/hora del evento
    df["fecha"] = pd.to_datetime(df.get("timestamp", ""), errors="coerce")

    # Duración total en horas (suma de columna prog + no prog)
    df["h_prog"]   = df.get("dur_prog", "").apply(hhmm_a_horas)
    df["h_noprog"] = df.get("dur_noprog", "").apply(hhmm_a_horas)
    df["horas"]    = df["h_prog"] + df["h_noprog"]
    df["tipo"] = np.where(df["h_prog"] > 0, "PROGRAMADO", "NO PROGRAMADO")

    # Texto normalizado para agrupar sin que los acentos fragmenten datos
    for col in ["equipo", "motivo", "componente", "linea", "area",
                "causa_raiz", "tipo_intervencion"]:
        if col in df.columns:
            df[col + "_n"] = df[col].apply(_norm)
        else:
            df[col] = ""
            df[col + "_n"] = ""

    # --- Clasificación de intervenciones (insumo de Weibull) -----------------
    # REEMPLAZO   -> punto de RENOVACIÓN: cierra una vida, abre otra. Es el
    #                evento que el modelo Weibull cuenta como "falla de vida".
    # REPARACIÓN  -> falla real pero NO reinicia el reloj de vida.
    #                Va a un análisis aparte (sistema reparable / NHPP).
    # AJUSTE      -> intervención menor; no entra al conteo de fallas.
    df["es_reemplazo"]  = df["tipo_intervencion_n"] == "REEMPLAZO"
    df["es_reparacion"] = df["tipo_intervencion_n"] == "REPARACION"
    df["es_ajuste"]     = df["tipo_intervencion_n"] == "AJUSTE"
    tiene_clasif = df["tipo_intervencion_n"].isin(
        ["REEMPLAZO", "REPARACION", "AJUSTE"]
    )

    # Compatibilidad hacia atrás: registros previos al campo no tienen
    # tipo_intervencion. Para ellos caemos al heurístico anterior y los
    # marcamos como "probables renovaciones" (asunción conservadora: en
    # piso, un MTTTO Correctivo casi siempre termina en reemplazo).
    heuristico_falla = df["motivo_n"].isin(MOTIVOS_FALLA) | (
        (df["tipo"] == "NO PROGRAMADO") & (df["componente_n"] != "")
    )
    df["clasif_origen"] = np.where(tiene_clasif, "explícita", "heurística")

    # es_falla  = cualquier falla real (reemplazo + reparación, o heurístico)
    # es_renov  = SOLO eventos que reinician el reloj de vida (Weibull renewal)
    df["es_falla"] = df["es_reemplazo"] | df["es_reparacion"] | (
        ~tiene_clasif & heuristico_falla
    )
    df["es_renovacion"] = df["es_reemplazo"] | (
        ~tiene_clasif & heuristico_falla
    )
    return df


# ------------------------------------------------------------------------------
# 5) AUDITORÍA DE CALIDAD DE DATOS
# ------------------------------------------------------------------------------

def auditoria_calidad(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    fallas = df[df["es_falla"]]
    nf = max(len(fallas), 1)

    n_explicita = int((df["clasif_origen"] == "explícita").sum())

    filas = [
        ("Registros totales", n, "—"),
        ("Fechas válidas (timestamp)", int(df["fecha"].notna().sum()),
         f"{df['fecha'].notna().mean()*100:.0f}%"),
        ("Fallas de componente detectadas", len(fallas),
         f"{len(fallas)/max(n,1)*100:.0f}% del total"),
        ("  · con tipo_intervencion explícito", n_explicita,
         f"{n_explicita/max(n,1)*100:.0f}% (datos nuevos)"),
        ("  · Reemplazos (renovaciones para Weibull)",
         int(df["es_reemplazo"].sum()), "—"),
        ("  · Reparaciones (sistema reparable, análisis aparte)",
         int(df["es_reparacion"].sum()), "—"),
        ("  · Ajustes (excluidos del modelo)",
         int(df["es_ajuste"].sum()), "—"),
        ("Fallas con COMPONENTE llenado",
         int((fallas["componente_n"] != "").sum()),
         f"{(fallas['componente_n'] != '').mean()*100:.0f}% de fallas"),
        ("Fallas con CAUSA RAÍZ llenada",
         int((fallas["causa_raiz_n"] != "").sum()),
         f"{(fallas['causa_raiz_n'] != '').mean()*100:.0f}% de fallas"),
        ("Componentes distintos (nombres)",
         fallas["componente_n"].replace("", np.nan).dropna().nunique(), "—"),
    ]
    return pd.DataFrame(filas, columns=["Métrica", "Valor", "Cobertura"])


# ------------------------------------------------------------------------------
# 6) PARETO + MTBF / MTTR
# ------------------------------------------------------------------------------

def pareto(df: pd.DataFrame, columna: str) -> pd.DataFrame:
    g = (df.groupby(columna)["horas"].sum()
           .sort_values(ascending=False).reset_index())
    g = g[g["horas"] > 0]
    total = g["horas"].sum()
    g["%"] = (g["horas"] / total * 100).round(1) if total else 0
    g["% acumulado"] = g["%"].cumsum().round(1)
    return g.rename(columns={columna: columna.replace("_n", "")})


def mtbf_mttr(historial: pd.DataFrame) -> pd.DataFrame:
    """MTBF (horas operativas entre fallas) y MTTR (horas de reparación)."""
    if historial.empty:
        return pd.DataFrame()
    g = historial.groupby(["equipo", "componente"]).agg(
        fallas=("tbf_oper_h", "count"),
        mtbf_oper_h=("tbf_oper_h", "mean"),
        mtbf_cal_h=("tbf_cal_h", "mean"),
        mttr_h=("dur_reparacion_h", "mean"),
    ).reset_index()
    return g.sort_values("fallas", ascending=False).round(1)


# ------------------------------------------------------------------------------
# 7) HISTORIAL DE FALLAS  (el insumo crítico de Weibull)
# ------------------------------------------------------------------------------

def construir_historial(df: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada (línea, equipo, componente) ordena las fallas en el tiempo y
    calcula el Tiempo Entre Fallas (TBF):

      - tbf_cal_h : horas de CALENDARIO entre falla previa y actual.
      - tbf_oper_h: horas OPERATIVAS netas = calendario − paros de esa línea
                    ocurridos en el intervalo. Es el mejor proxy de 'horas de
                    operación del componente' MIENTRAS no se integre el OEE.

    NOTA: este TBF operativo es PROVISIONAL. El dato definitivo son las horas
    de operación acumuladas que entregará el sistema OEE del Ing. Barba.

    Solo se cuentan los REEMPLAZOS (eventos de renovación). Las reparaciones
    salen por separado en eventos_reparacion.csv.
    """
    fallas = df[df["es_renovacion"] & df["fecha"].notna()].copy()
    if fallas.empty:
        return pd.DataFrame()

    # Paros por línea (para descontar downtime del intervalo)
    todos = df[df["fecha"].notna()].copy()

    registros = []
    claves = ["linea_n", "equipo_n", "componente_n"]
    for (lin, eq, comp), grupo in fallas.groupby(claves):
        if comp == "":
            continue  # sin componente no se puede modelar por componente
        grupo = grupo.sort_values("fecha")
        prev = None
        for _, fila in grupo.iterrows():
            if prev is not None:
                horas_cal = (fila["fecha"] - prev).total_seconds() / 3600.0
                # downtime de ESA línea dentro del intervalo (excluye la falla actual)
                en_intervalo = todos[
                    (todos["linea_n"] == lin)
                    & (todos["fecha"] > prev)
                    & (todos["fecha"] < fila["fecha"])
                ]
                downtime = en_intervalo["horas"].sum()
                horas_oper = max(horas_cal - downtime, 0.0)
                registros.append({
                    "linea": fila["linea"],
                    "equipo": fila["equipo"],
                    "componente": fila["componente"],
                    "fecha_falla": fila["fecha"],
                    "tbf_cal_h": round(horas_cal, 1),
                    "tbf_oper_h": round(horas_oper, 1),
                    "dur_reparacion_h": round(fila["horas"], 2),
                    "motivo": fila["motivo"],
                })
            prev = fila["fecha"]
    return pd.DataFrame(registros)


# ------------------------------------------------------------------------------
# 8) AJUSTE WEIBULL  +  INTERVALO ÓPTIMO  (provisional)
# ------------------------------------------------------------------------------

def _ajustar_weibull(tiempos: np.ndarray):
    """Devuelve (beta, eta). Usa 'reliability' si está; si no, scipy."""
    tiempos = tiempos[tiempos > 0]
    try:
        from reliability.Fitters import Fit_Weibull_2P
        f = Fit_Weibull_2P(failures=list(tiempos), show_probability_plot=False,
                           print_results=False)
        return float(f.beta), float(f.alpha)   # alpha = eta
    except Exception:
        from scipy.stats import weibull_min
        beta, loc, eta = weibull_min.fit(tiempos, floc=0)
        return float(beta), float(eta)


def intervalo_optimo(beta: float, eta: float, razon_costo: float = 5.0) -> float:
    """
    Intervalo de preventivo que minimiza el costo por unidad de tiempo
    (modelo de reemplazo por edad). razon_costo = costo_correctivo/costo_preventivo.
    Solo tiene sentido reemplazar por edad cuando hay desgaste (beta > 1).
    """
    if beta <= 1:
        return float("inf")  # falla aleatoria/infantil: preventivo por edad no ayuda
    from scipy.optimize import minimize_scalar
    from scipy.stats import weibull_min

    def costo(T):
        if T <= 0:
            return 1e9
        R = weibull_min.sf(T, beta, scale=eta)              # confiabilidad a T
        # vida esperada hasta intervención (integral de R de 0 a T)
        ts = np.linspace(0, T, 200)
        _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
        vida_esp = _trapz(weibull_min.sf(ts, beta, scale=eta), ts)
        c_prev, c_corr = 1.0, razon_costo
        return (c_prev * R + c_corr * (1 - R)) / max(vida_esp, 1e-9)

    res = minimize_scalar(costo, bounds=(eta * 0.05, eta * 2.0), method="bounded")
    return float(res.x)


def confiabilidad(t: float, beta: float, eta: float) -> float:
    return float(np.exp(-((t / eta) ** beta)))


def diagnostico_beta(beta: float) -> str:
    if beta < 0.95:
        return "Mortalidad infantil (defecto fab./instalación) — preventivo por edad NO aplica"
    if beta <= 1.05:
        return "Falla aleatoria — revisar predictivo/condición, no preventivo por edad"
    if beta <= 2:
        return "Desgaste incipiente — preventivo por edad recomendable"
    return "Desgaste marcado — preventivo por edad muy recomendable"


def analizar_weibull(historial: pd.DataFrame, min_fallas: int = 8,
                     razon_costo: float = 5.0) -> pd.DataFrame:
    if historial.empty:
        return pd.DataFrame()
    filas = []
    for (eq, comp), g in historial.groupby(["equipo", "componente"]):
        t = g["tbf_oper_h"].to_numpy(dtype=float)
        t = t[t > 0]
        n = len(t)
        if n < 2:
            continue
        beta, eta = _ajustar_weibull(t)
        confiable = n >= min_fallas
        T_opt = intervalo_optimo(beta, eta, razon_costo)
        filas.append({
            "equipo": eq,
            "componente": comp,
            "n_fallas": n,
            "modelo": "CONFIABLE" if confiable else "PROVISIONAL",
            "beta": round(beta, 2),
            "eta_h": round(eta, 1),
            "diagnostico": diagnostico_beta(beta),
            "mtbf_oper_h": round(float(np.mean(t)), 1),
            "intervalo_preventivo_h": (round(T_opt, 0)
                                       if np.isfinite(T_opt) else "N/A (no por edad)"),
            "R_en_intervalo": (round(confiabilidad(T_opt, beta, eta), 3)
                               if np.isfinite(T_opt) else "—"),
        })
    cols_orden = ["n_fallas"]
    out = pd.DataFrame(filas)
    return out.sort_values(cols_orden, ascending=False) if not out.empty else out


# ------------------------------------------------------------------------------
# 9) ORQUESTACIÓN
# ------------------------------------------------------------------------------

def guardar(df: pd.DataFrame, nombre: str):
    ruta = os.path.join(CARPETA_SALIDA, nombre)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


def main():
    ap = argparse.ArgumentParser(description="Análisis de confiabilidad de paros")
    ap.add_argument("--csv", help="Ruta al CSV exportado de ParosApp")
    ap.add_argument("--sheets", action="store_true", help="Leer de Google Sheets")
    ap.add_argument("--min-fallas", type=int, default=8,
                    help="Mínimo de fallas para marcar el modelo como CONFIABLE")
    ap.add_argument("--razon-costo", type=float, default=5.0,
                    help="costo_correctivo / costo_preventivo")
    args = ap.parse_args()

    os.makedirs(CARPETA_SALIDA, exist_ok=True)

    if args.sheets:
        df = cargar_desde_sheets()
    elif args.csv:
        df = cargar_desde_csv(args.csv)
    else:
        sys.exit("Indica --csv RUTA o --sheets")

    df = normalizar(df)

    aud = auditoria_calidad(df)
    guardar(aud, "auditoria_calidad.csv")

    par_mot = pareto(df, "motivo_n");  guardar(par_mot, "pareto_motivos.csv")
    par_com = pareto(df[df["es_falla"]], "componente_n")
    guardar(par_com, "pareto_componentes.csv")

    hist = construir_historial(df);     guardar(hist, "historial_fallas.csv")
    mm   = mtbf_mttr(hist);             guardar(mm, "mtbf_mttr.csv")
    wb   = analizar_weibull(hist, args.min_fallas, args.razon_costo)
    guardar(wb, "weibull_resultados.csv")

    # Reparaciones aparte: insumo para análisis de sistema reparable
    # (Crow-AMSAA / NHPP) — fuera del alcance del Weibull clásico.
    reparaciones = df[df["es_reparacion"]][
        ["fecha", "linea", "equipo", "componente", "causa_raiz",
         "accion", "horas"]
    ].copy()
    guardar(reparaciones, "eventos_reparacion.csv")

    # ---- Resumen ejecutivo ----
    lineas = []
    lineas.append("=" * 70)
    lineas.append("RESUMEN DE CORRIDA — Análisis de confiabilidad de paros")
    lineas.append(f"Fecha de corrida: {datetime.now():%Y-%m-%d %H:%M}")
    lineas.append("=" * 70)
    lineas.append("\n[1] CALIDAD DE DATOS")
    for _, r in aud.iterrows():
        lineas.append(f"   - {r['Métrica']}: {r['Valor']} ({r['Cobertura']})")

    lineas.append("\n[2] PARETO — top motivos por horas perdidas")
    for _, r in par_mot.head(5).iterrows():
        lineas.append(f"   - {r['motivo']}: {r['horas']:.1f} h "
                      f"({r['%']}%, acum {r['% acumulado']}%)")

    lineas.append("\n[3] MODELO WEIBULL (provisional)")
    if wb.empty:
        lineas.append("   Aún no hay suficientes fallas por componente para ajustar.")
        lineas.append("   -> Necesario: acumular eventos con COMPONENTE identificado.")
    else:
        for _, r in wb.iterrows():
            lineas.append(
                f"   - {r['equipo']} / {r['componente']} "
                f"[{r['modelo']}, n={r['n_fallas']}]: "
                f"β={r['beta']}, η={r['eta_h']} h, "
                f"intervalo={r['intervalo_preventivo_h']} h | {r['diagnostico']}"
            )

    lineas.append("\n[4] RECORDATORIO")
    lineas.append("   El TBF operativo es PROVISIONAL (calendario − downtime).")
    lineas.append("   El dato definitivo son las horas de operación del OEE (Ing. Barba).")
    lineas.append("=" * 70)

    resumen = "\n".join(lineas)
    with open(os.path.join(CARPETA_SALIDA, "resumen.txt"), "w", encoding="utf-8") as f:
        f.write(resumen)
    print(resumen)
    print(f"\nEntregables escritos en ./{CARPETA_SALIDA}/")


if __name__ == "__main__":
    main()