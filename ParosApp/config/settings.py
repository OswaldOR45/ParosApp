"""
Configuración central de la aplicación.
Catálogos, mapeo de columnas y reglas de negocio en un solo lugar.
"""

# ---------------------------------------------------------------------------
# Pestañas (worksheets) dentro del Google Sheet "Base de Datos Producción 2026"
# ---------------------------------------------------------------------------
HOJA_PAROS = "PAROSV2"
HOJA_EQUIPOS = "cat_equipos"          # opcional
HOJA_MOTIVOS = "cat_motivos"          # opcional
HOJA_COMPONENTES = "cat_componentes"  # catálogo dinámico por equipo

# ---------------------------------------------------------------------------
# MAPEO interno -> ENCABEZADO EXACTO de tu hoja (fila 1).
# El código empata por NOMBRE (no por posición), así que el orden de tus
# columnas puede variar. Si algún encabezado en tu hoja está escrito distinto,
# corrige EL TEXTO de la derecha aquí (es el único lugar que hay que tocar).
# ---------------------------------------------------------------------------
FIELD_TO_HEADER = {
    "timestamp":     "TIMESTAMP",
    "area":          "ÁREA",
    "turno":         "TURNO",
    "linea":         "LÍNEA",
    "equipo":        "EQUIPO / ÁREA AFECTADA",
    "motivo":        "MOTIVO DE PARO",
    "descripcion":   "DESCRIPCIÓN DEL PARO",
    "ini_prog":      "HORA DE INICIO (PARO PROGRAMADO)",
    "fin_prog":      "HORA DE FINALIZACIÓN (PARO PROGRAMADO)",
    "dur_prog":      "DURACIÓN (PARO PROGRAMADO)",
    "ini_noprog":    "HORA DE INICIO (PARO NO PROGRAMADO)",
    "fin_noprog":    "HORA DE FINALIZACIÓN (PARO NO PROGRAMADO)",
    "dur_noprog":    "DURACIÓN (PARO NO PROGRAMADO)",
    "id_paro":       "ID_PARO",
    "necesita_acr":  "¿NECESITA ACR?",
    "orden_trabajo": "ORDEN DE TRABAJO",
    "causa_raiz":    "CAUSA RAÍZ",
    "componente":    "COMPONENTE",
    "tipo_intervencion": "TIPO DE INTERVENCIÓN",
    "accion":        "ACCIÓN REALIZADA",
    "refaccion":     "REFACCIÓN",
    "ini_int":            "INICIO INTERVENCIÓN",
    "fin_int":            "FIN INTERVENCIÓN",
    "dur_int":            "DURACIÓN INTERVENCIÓN",
    "firma_produccion":   "FIRMA PRODUCCIÓN",
}

# ---------------------------------------------------------------------------
# Catálogos por defecto (la app funciona desde el día 1 sin pestañas extra)
# ---------------------------------------------------------------------------
TURNOS = ["A", "B", "C"]
LINEAS = ["Línea 1", "Línea 2", "Línea 1 y 2"]

AREAS = [
    "EXTRUSIÓN", "DOSIFICACIÓN", "SERVICIOS/ENERGÍA/AGUA", "EMPAQUE", "GENERAL",
    "ENFRIADOR", "MOLIENDA", "PLANTA", "CALDERAS", "SECADOR", "COATER",
    "TRANSPORTE NEUMATICO", "ZARANDA", "RASTRA", "LIMPIADORES",
]

EQUIPOS = [
    "Extrusor", "Secador", "Coater", "Enfriador", "Molienda",
    "Dosificación", "Dosificación / Envasado", "Envasadora", "General",
]

PROGRAMADO = "PROGRAMADO"
NO_PROGRAMADO = "NO PROGRAMADO"

# ---------------------------------------------------------------------------
# Tipo de intervención de mantenimiento.
# Define cómo el modelo Weibull lee la VIDA del componente:
#   Reemplazo  -> reinicia el reloj de vida (punto de RENOVACIÓN). Es el evento
#                 que el modelo usa como "falla → pieza nueva".
#   Reparación -> restaura parcialmente; NO reinicia el reloj (sistema reparable).
#   Ajuste     -> intervención menor; normalmente no cuenta como fin de vida.
# ---------------------------------------------------------------------------
TIPOS_INTERVENCION = ["Reemplazo", "Reparación", "Ajuste"]

# Orden aprox. por frecuencia (define el orden de los botones en pantalla)
MOTIVOS = [
    ("Cambio de Producto",       PROGRAMADO),
    ("Ajuste de Navajas",        NO_PROGRAMADO),
    ("Taponamiento Ciclón",      NO_PROGRAMADO),
    ("MTTTO Correctivo",         NO_PROGRAMADO),
    ("Tolvas Llenas",            NO_PROGRAMADO),
    ("Harina No Conforme",       NO_PROGRAMADO),
    ("Falta de Harina",          NO_PROGRAMADO),
    ("Error Operativo",          NO_PROGRAMADO),
    ("Alta Carga",               NO_PROGRAMADO),
    ("Limpieza de Equipos",      PROGRAMADO),
    ("Instrumentación",          NO_PROGRAMADO),
    ("Producto No Conforme",     NO_PROGRAMADO),
    ("Falta de Servicios",       NO_PROGRAMADO),
    ("MTTTO Preventivo",         PROGRAMADO),
    ("Falta de Personal",        NO_PROGRAMADO),
    ("Error de Programación",    NO_PROGRAMADO),
    ("Intervención Técnico",     NO_PROGRAMADO),
    ("Paro Planta Programado",   PROGRAMADO),
    ("Arranque Planta Programado",  PROGRAMADO),
    ("Proyectos",                PROGRAMADO),
    ("Inventario",               PROGRAMADO),
]


def catalogos_default() -> dict:
    return {
        "turnos": TURNOS,
        "lineas": LINEAS,
        "areas": AREAS,
        "equipos": EQUIPOS,
        "motivos": [m for m, _ in MOTIVOS],
        "tipo_por_motivo": {m: t for m, t in MOTIVOS},
        "tipos_intervencion": TIPOS_INTERVENCION,
    }