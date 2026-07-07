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
    "empresa_acr":   "ATENDIDO POR",
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
    # --- Paros multi-turno ---------------------------------------------------
    "paro_padre":         "PARO_PADRE",
    "es_continuacion":    "ES_CONTINUACION",
    "paro_en_curso":      "PARO_EN_CURSO",
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
# Intervalos de turno fijos (hora_inicio_str, hora_fin_str).
# El grupo A/B/C rota, pero los bloques horarios son siempre estos.
# Se usan para calcular el fin automático cuando un paro se extiende
# al siguiente turno, y para asignar el tramo correcto al siguiente supervisor.
# ---------------------------------------------------------------------------
INTERVALOS_TURNO = [
    ("05:00", "13:00"),
    ("13:00", "21:00"),
    ("21:00", "05:00"),   # cruza medianoche
]

# ---------------------------------------------------------------------------
# Tipo de intervención de mantenimiento.
# Define cómo el modelo Weibull lee la VIDA del componente:
#   Reemplazo  -> reinicia el reloj de vida (punto de RENOVACIÓN). Es el evento
#                 que el modelo usa como "falla → pieza nueva".
#   Reparación -> restaura parcialmente; NO reinicia el reloj (sistema reparable).
#   Ajuste     -> intervención menor; normalmente no cuenta como fin de vida.
# ---------------------------------------------------------------------------
TIPOS_INTERVENCION = ["Reemplazo", "Reparación", "Ajuste", "Revisión / Diagnóstico"]

# Orden aprox. por frecuencia (define el orden de los botones en pantalla)
MOTIVOS = [
    ("Cambio de Producto",       PROGRAMADO, "Paro planificado para limpiar, cambiar dados, moldes o set-ups al pasar de un producto a otro diferente."),
    ("Ajuste de Navajas",        NO_PROGRAMADO, "Paro rápido no planificado para calibrar o corregir la alineación/filo de las navajas debido a un mal corte."),
    ("Taponamiento Ciclón",      NO_PROGRAMADO, "Paro por obstrucción física de material en el flujo del ciclón o transporte neumático que requiere destape manual."),
    ("MTTTO Correctivo",         NO_PROGRAMADO, "Paro por falla mecánica o eléctrica imprevista de un componente del equipo que requiere reparación, cambio de refacción o soldadura para volver a funcionar."),
    ("Tolvas Llenas",            NO_PROGRAMADO, "El equipo se detiene por seguridad porque el proceso posterior está saturado y no hay capacidad para envasar el producto."),
    ("Harina No Conforme",       NO_PROGRAMADO, "La harina que se está extruyendo no cumple con las características de calidad esperadas."),
    ("Falta de Harina",          NO_PROGRAMADO, "Línea detenida por desabasto de materia prima en los silos de alimentación o retraso en molienda."),
    ("Error Operativo",          NO_PROGRAMADO, "Paro causado por una mala maniobra, set-up incorrecto, omisión de un procedimiento estándar o descuido humano."),
    ("Alta Carga",               NO_PROGRAMADO, "Sobrecarga de motor / Amperaje Elevado"),
    ("Limpieza de Equipos",      PROGRAMADO, "Paro agendado por plan de higiene o inocuidad, que no se debe a una falla interna."),
    ("Instrumentación",          NO_PROGRAMADO, "Falla exclusiva de sensores, actuadores, PLCs, pantallas o pérdida de señales de control (falla electrónica/eléctrica de control)"),
    ("Producto No Conforme",     NO_PROGRAMADO, "Paro para corregir desviaciones de calidad del producto final o intermedio (ej. fuera de tamaño, densidad o humedad errónea)."),
    ("Falta de Servicios",       NO_PROGRAMADO, "Paro ajeno a la máquina provocado por la interrupción de energía eléctrica, agua, aire comprimido o vapor."),
    ("MTTTO Preventivo",         PROGRAMADO, "Paro por calendario para rutina de lubricación, inspección, cambio de piezas por desgaste planeado o calibración."),
    ("Falta de Personal",        NO_PROGRAMADO, "La máquina está disponible para operar, pero no hay operadores o cuadrilla suficiente para arrancar."),
    ("Error de Programación",    NO_PROGRAMADO, "Paro debido a un error en el plan de producción."),
    ("Intervención Técnico",     NO_PROGRAMADO, "Paro donde se necesita la asistencia de un técnico externo para el correcto funcionamiento de la máquina."),
    ("Paro Planta Programado",   PROGRAMADO, "Paro total de operaciones planificado (ej. días festivos, mantenimiento mayor anual, fin de semana sin producción)."),
    ("Arranque Planta Programado",  PROGRAMADO, "Tiempo estándar asignado para la puesta en marcha y estabilización de las áreas antes de producir."),
    ("Proyectos",                PROGRAMADO, "Paro asignado a ingeniería o mejora continua para instalar equipos nuevos, hacer pruebas o modificaciones de línea."),
    ("Inventario",               PROGRAMADO, "Paro total o parcial programado exclusivamente para el conteo de materiales o producto terminado."),
]


def catalogos_default() -> dict:
    return {
        "turnos": TURNOS,
        "lineas": LINEAS,
        "areas": AREAS,
        "equipos": EQUIPOS,
        "motivos": [m for m, _, _d in MOTIVOS],
        "tipo_por_motivo": {m: t for m, t, _d in MOTIVOS},
        "descrip_motivo": {m: d for m, t, d in MOTIVOS},
        "tipos_intervencion": TIPOS_INTERVENCION,
    }
HOJA_ACRS = "ACRS"

FIELD_TO_HEADER_ACR = {
    "id_paro":            "ID_PARO",
    "empresa":             "EMPRESA",
    "orden_trabajo":       "ORDEN_TRABAJO",
    "causa_raiz":          "CAUSA_RAIZ",
    "componente":          "COMPONENTE",
    "tipo_intervencion":   "TIPO_INTERVENCION",
    "accion":              "ACCION",
    "refaccion":           "REFACCION",
    "ini_int":             "INI_INT",
    "fin_int":             "FIN_INT",
    "dur_int":             "DUR_INT",
    "firma_produccion":    "FIRMA_PRODUCCION",
    "timestamp":           "TIMESTAMP",
}