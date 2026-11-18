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

# ---------------------------------------------------------------------------
# ÁREA = DÓNDE SE ORIGINÓ LA CAUSA del paro.
# EQUIPO / ÁREA AFECTADA = QUÉ SE DETUVO (normalmente el Extrusor = la línea).
#   Ej.: se acaba la harina porque el molino falla ->
#        Área = MOLIENDA · Equipo afectado = Extrusor.
#   Ej.: se cae una banda del elevador que alimenta el secador ->
#        Área = TRANSPORTE DE MATERIAL · Equipo afectado = Extrusor.
# Orden = frecuencia de uso real (orden de los botones en pantalla).
# ---------------------------------------------------------------------------
AREAS_DEF = [
    ("EXTRUSIÓN", "Extrusor y sus partes: alimentador, acondicionador, camisas, "
                  "tornillos, cojinetes, plato, navajas, bombas de color/agua."),
    ("MOLIENDA", "Molinos, cribas, martillos, tolvas de harina, revolvedora de "
                 "molienda. Incluye la falta de harina por molienda."),
    ("DOSIFICACIÓN", "Silos, básculas, volcador y recepción/dosificación de "
                     "ingredientes antes de molienda."),
    ("SECADOR", "Secador: zonas de calentamiento, quemadores, ventiladores, "
                "rotativas de entrada y salida."),
    ("TRANSPORTE DE MATERIAL", "Equipos que MUEVEN material entre áreas: "
                               "elevadores, rastras, helicoidales/gusanos, "
                               "transporte neumático, succionadores, ciclones."),
    ("EMPAQUE", "Envasado: tolvas de producto terminado, cosedoras, ribeteadora, "
                "bandas, tarimas y estiba."),
    ("SERVICIOS", "Luz (CFE, apagones, bajones), calderas/vapor, aire "
                  "comprimido, agua, gas."),
    ("COATER", "Coater: digesta, grasa, bombas y tubería de recubrimiento."),
    ("ENFRIADOR", "Enfriador y su transmisión (cadenas, cuñas)."),
    ("GENERAL", "Afecta a toda la planta o no tiene un área específica "
                "(paro de planta, falta de personal general)."),
    ("ZARANDA", "Zarandas / cribado de producto."),
    ("LIMPIADORES", "Limpiadores de grano."),
]
AREAS = [a for a, _ in AREAS_DEF]
DESCRIP_AREA = dict(AREAS_DEF)

# Áreas retiradas -> área vigente (para limpiar el histórico y agrupar).
AREAS_ALIAS = {
    "CALDERAS": "SERVICIOS",
    "SERVICIOS/ENERGÍA/AGUA/GAS/COMPRESOR": "SERVICIOS",
    "PLANTA": "GENERAL",
    "TRANSPORTE NEUMATICO": "TRANSPORTE DE MATERIAL",
    "RASTRA": "TRANSPORTE DE MATERIAL",
    "EXTRUSOR": "EXTRUSIÓN",
}

# Equipo / área AFECTADA = lo que dejó de producir. No es el lugar de la falla
# (eso es el Área) ni la pieza (eso es el componente en el ACR).
EQUIPOS = [
    "Extrusor", "Molienda", "Dosificación", "Secador", "Coater",
    "Enfriador", "Envasado", "General", "Volcador", "BÁSCULA"
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

# ---------------------------------------------------------------------------
# CATEGORÍAS DE PÉRDIDA (agrupan motivos para un Pareto de nivel superior,
# alineado a las pérdidas de disponibilidad del OEE).
# ---------------------------------------------------------------------------
CAT_FALLA = "Falla de equipo"
CAT_CAMBIOS = "Cambios y ajustes"
CAT_ABASTO = "Abastecimiento"
CAT_FLUJO = "Flujo / capacidad"
CAT_CALIDAD = "Calidad"
CAT_METODO = "Método / operación"
CAT_SERVICIOS = "Servicios"
CAT_PERSONAL = "Personal"
CAT_PLANEACION = "Planeación"
CAT_MTTO_PLAN = "Mantenimiento planeado"
CAT_PARO_PLAN = "Paro planeado"

# ---------------------------------------------------------------------------
# MOTIVOS ACTIVOS: (nombre, tipo, categoría, descripción para el operador)
# · El ORDEN es el de los botones en pantalla: por frecuencia real de uso.
# · La descripción es el CRITERIO DE DECISIÓN que ve el operador: qué es,
#   ejemplos reales y, si se confunde con otro, cuál usar en su lugar.
# · NUNCA renombres un motivo que ya tiene datos: pásalo a MOTIVOS_HISTORICOS
#   y crea el nuevo. Si no, los Paretos parten el mismo motivo en dos.
# ---------------------------------------------------------------------------
MOTIVOS = [
    ("Cambio de Producto", PROGRAMADO, CAT_CAMBIOS,
     "Paro planeado para pasar de un producto a otro: vaciado, limpieza, "
     "cambio de color y de plato/navajas del producto nuevo. Si el cambio se "
     "alarga por un error o porque faltó algo (color, harina), registra ese "
     "tiempo extra con su propio motivo."),
    ("Falta de Harina en tolvas de Extrusión", NO_PROGRAMADO, CAT_ABASTO,
     "El extrusor no puede arrancar o se detiene porque no hay harina "
     "suficiente: molienda va retrasada o no ha formado colchón. "
     "Área = MOLIENDA. NO usar si: el molino FALLÓ → «MTTTO Correctivo» "
     "(Área MOLIENDA); se está moliendo otro producto por programa → "
     "«Programa de Operación»; la harina salió mala → «Harina No Conforme»."),
    ("Error Operativo", NO_PROGRAMADO, CAT_METODO,
     "Error humano: maniobra incorrecta, set-up mal hecho, olvido de un paso "
     "del procedimiento, arranque tardío por descuido, mala comunicación "
     "entre turnos. NO usar para cambios de plato o navajas → «Cambio de "
     "Plato / Navajas»."),
    ("MTTTO Correctivo", NO_PROGRAMADO, CAT_FALLA,
     "Falla mecánica o eléctrica de potencia que obliga a reparar: cojinetes "
     "calientes, cadenas, bandas, poleas, motores, flechas, soldadura, "
     "tuberías. Área = donde está el equipo que falló. Si falló un sensor, "
     "PLC o señal → «Instrumentación». Si ya se diagnosticó y solo se espera "
     "la pieza → «Espera de Refacción»."),
    ("Cambio de Plato / Navajas", NO_PROGRAMADO, CAT_CAMBIOS,
     "Paro NO planeado para cambiar o limpiar plato (dado) o navajas por "
     "taponamiento, desgaste, croqueta deforme o corte malo. Si el cambio es "
     "parte de un cambio de producto → «Cambio de Producto». Si el plato se "
     "tapó con fierros → «Material Extraño / Metales»."
     "Si es taponamiento por mala molienda «Error Operativo» "),
    ("Secuencia de producción", NO_PROGRAMADO, CAT_PLANEACION,
    "Paro para cambiar de producto según el orden de fabricación definido en la programación. "
    "Incluye el tiempo de limpieza, purga, cambio de formulación o de plato/punta, y ajustes de "
    "arranque al pasar de una orden a otra (por ejemplo, de una formulación de perro a una de gato). "
    "No incluye paros por falta de programación (Error de Programación), por tiempo insuficiente "
    "para producir o por decisiones de operación (Programa de Operación), ni por falta de materia prima."),
    ("Paro Planta Programado", PROGRAMADO, CAT_PARO_PLAN,
     "Paro total planificado: días festivos, fin de semana sin producción, "
     "mantenimiento mayor, inventario."),
    ("MTTTO Preventivo", PROGRAMADO, CAT_MTTO_PLAN,
     "Mantenimiento que estaba en el plan: lubricación, inspección, cambio de "
     "piezas por desgaste planeado (martillos, cribas), calibración. Si se "
     "para porque algo YA falló, es «MTTTO Correctivo» aunque se aproveche "
     "para revisar otras cosas."),
    ("Falta de Materia Prima", NO_PROGRAMADO, CAT_ABASTO,
     "Falta un insumo o material: maíz, pasta de soya, harina de carne, "
     "aceite, vitaminas, colorante, costales o tarimas. Escribe en la "
     "descripción QUÉ faltó. Si el insumo sí hay pero no llega por falla del "
     "transportador → «MTTTO Correctivo» (Área TRANSPORTE DE MATERIAL)."),
    ("Falta de Servicios", NO_PROGRAMADO, CAT_SERVICIOS,
     "Se cae un servicio de planta: luz (CFE, apagón, bajón), vapor o "
     "calderas, aire comprimido, agua, gas. Área = SERVICIOS, aunque la "
     "línea afectada sea otra."),
    ("Arranque Planta Programado", PROGRAMADO, CAT_PARO_PLAN,
     "Tiempo estándar para poner en marcha y estabilizar la planta después "
     "de un «Paro Planta Programado»."),
    ("Programa de Operación", PROGRAMADO, CAT_PLANEACION,
     "Por decisión no se arranca o se detiene la línea: queda poco tiempo "
     "para producir, se trabaja con un solo extrusor, o el molino está "
     "moliendo otro producto según la secuencia del programa. Si la harina "
     "falta por retraso de molienda → «Falta de Harina en tolvas de "
     "Extrusión»."),
    ("Instrumentación", NO_PROGRAMADO, CAT_FALLA,
     "Falla de CONTROL: sensores, señales, PLC, pantallas, variadores, "
     "programa del equipo (ej. la dosificación no da el siguiente paso, "
     "falla de señal de rotativa, RPM erróneas). Si el problema es mecánico o "
     "de potencia → «MTTTO Correctivo»."),
    ("Espera de Refacción", NO_PROGRAMADO, CAT_FALLA,
     "La reparación está detenida porque falta una pieza: se llevó a "
     "reparar a taller o torno externo, o se espera refacción de almacén o "
     "proveedor. El diagnóstico y desarme van en «MTTTO Correctivo»; cuando "
     "la pieza sale a reparar, CIERRA ese paro y abre uno nuevo con este "
     "motivo. Escribe qué pieza y a dónde se llevó."),
    ("Atascamiento / Taponamiento", NO_PROGRAMADO, CAT_FLUJO,
     "Material atorado que hay que destapar a mano: ciclón, termo, "
     "succionador, elevador, rastra, tolva. Incluye el disparo del motor por "
     "sobrecarga cuando la causa es el atasco. Si se tapó el plato → «Cambio "
     "de Plato / Navajas»."),
    ("Tolvas Llenas", NO_PROGRAMADO, CAT_FLUJO,
     "La línea se detiene porque el proceso siguiente está lleno y no hay "
     "dónde recibir producto (tolvas de PT, supersacos). Si se llenaron "
     "porque el equipo siguiente falló (ej. cosedora) → «MTTTO Correctivo» "
     "con el área de ese equipo."),
    ("Arranque de Línea ", PROGRAMADO, CAT_CAMBIOS,
     "Tiempo estándar de puesta en marcha y estabilización de una línea "
     "antes de producir. Si el arranque se retrasa por un error → «Error "
     "Operativo»; por falta de harina → «Falta de Harina en tolvas de "
     "Extrusión»."),
    ("Producto No Conforme", NO_PROGRAMADO, CAT_CALIDAD,
     "Paro para corregir croqueta fuera de especificación: tamaño, densidad, "
     "humedad, expansión, color. Si se resolvió solo cambiando plato o "
     "navajas → «Cambio de Plato / Navajas»."),
    ("Harina No Conforme", NO_PROGRAMADO, CAT_CALIDAD,
     "La harina no cumple calidad (granulometría gruesa, criba rota, "
     "contaminación) y no se puede extruir. Incluye el tiempo de DESVIAR "
     "harina por el bypass del extrusor y VOLVER A MOLERLA. Área = MOLIENDA. "
     "Anota en la descripción cuánta harina se re-molió."),
    ("Material Extraño / Metales", NO_PROGRAMADO, CAT_CALIDAD,
     "Fierros, metales, plásticos u objetos extraños en plato, dado o "
     "producto. Paro de INOCUIDAD: avisa a Calidad y anota qué se encontró y "
     "de dónde vino."),
    ("Limpieza de Equipos", PROGRAMADO, CAT_MTTO_PLAN,
     "Limpieza agendada por plan de higiene o inocuidad. Una limpieza NO "
     "planeada porque el producto salía mal → «Producto No Conforme»."),
    ("Error de Programación", NO_PROGRAMADO, CAT_PLANEACION,
     "El plan de producción venía mal (producto, cantidad o secuencia "
     "equivocada) y obligó a parar. Si fue una decisión correcta del "
     "programa → «Programa de Operación»."),
    ("Falta de Personal", NO_PROGRAMADO, CAT_PERSONAL,
     "El equipo está disponible pero no hay operadores suficientes para "
     "arrancar u operar."),
    ("Falla de montacargas", NO_PROGRAMADO, CAT_FALLA,
     "Falla del montacargas que impide mover material o producto terminado."),
    ("Proyectos", PROGRAMADO, CAT_PLANEACION,
     "Paro asignado a ingeniería o mejora continua: instalación de equipos, "
     "pruebas o modificaciones de línea."),
]

# ---------------------------------------------------------------------------
# MOTIVOS HISTÓRICOS: ya no aparecen como botón, pero los registros viejos
# siguen clasificándose bien (tipo y categoría) en Dashboard y Paretos.
# (nombre, tipo, categoría, por qué se retiró / qué usar ahora)
# ---------------------------------------------------------------------------
MOTIVOS_HISTORICOS = [
    ("Ajuste de Navajas", NO_PROGRAMADO, CAT_CAMBIOS,
     "Integrado en «Cambio de Plato / Navajas»."),
    ("Intervención Técnica", NO_PROGRAMADO, CAT_FALLA,
     "Describía QUIÉN atendió, no la causa (eso ya se captura en «¿Solicitaste "
     "apoyo externo?»). Usar la causa real."),
    ("Taponamiento Ciclón", NO_PROGRAMADO, CAT_FLUJO,
     "Ampliado a «Atascamiento / Taponamiento»."),
    ("Alta Carga", NO_PROGRAMADO, CAT_FALLA,
     "Era un síntoma. Atasco → «Atascamiento / Taponamiento»; falla del "
     "motor → «MTTTO Correctivo»."),
    ("Inventario", PROGRAMADO, CAT_PARO_PLAN,
     "Integrado en «Paro Planta Programado»."),
    ("Falta de tarimas", NO_PROGRAMADO, CAT_ABASTO,
     "Integrado en «Falta de Materia Prima» (insumos y material de empaque)."),
]


def catalogos_default() -> dict:
    todos = MOTIVOS + MOTIVOS_HISTORICOS
    return {
        "turnos": TURNOS,
        "lineas": LINEAS,
        "areas": AREAS,
        "descrip_area": DESCRIP_AREA,
        "equipos": EQUIPOS,
        # Botones del operador: solo los activos
        "motivos": [m for m, _t, _c, _d in MOTIVOS],
        # Clasificación: activos + históricos (para no perder los datos viejos)
        "tipo_por_motivo": {m: t for m, t, _c, _d in todos},
        "categoria_por_motivo": {m: c for m, _t, c, _d in todos},
        "descrip_motivo": {m: d for m, _t, _c, d in todos},
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
# ---------------------------------------------------------------------------
# ROL DE TURNOS (excepciones para el TND)
# Por defecto cada grupo trabaja 1 turno de 8 h al día. En esta hoja SOLO se
# capturan las excepciones:
#   HORAS = 0   -> el grupo no trabajó (vacaciones / descanso)
#   HORAS = 12  -> turno de 12 h (cubriendo a un grupo de vacaciones)
#   HORAS = 16  -> doble turno
# Si hay varias filas para la misma FECHA + GRUPO, manda la ÚLTIMA (así se
# corrige un error capturando de nuevo). La hoja se crea sola la primera vez
# que se guarda una excepción desde la app.
# ---------------------------------------------------------------------------
HOJA_ROL_TURNOS = "ROL_TURNOS"
HORAS_TURNO_NORMAL = 8
ENCABEZADOS_ROL = ["FECHA", "GRUPO", "HORAS", "NOTA", "REGISTRADO"]