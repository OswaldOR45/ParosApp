# Análisis de confiabilidad — Plan Maestro de Mantenimiento Preventivo

Motor **fuera de línea** (no corre dentro de Streamlit) que lee lo que captura
ParosApp — `PAROSV2`, `ACRS` y `cat_componentes` — y produce:

| Nivel | Pregunta que responde | Funciona con pocos datos |
|---|---|---|
| **Pérdidas** | ¿Dónde se van las horas? (Pareto no programado y programado por separado) | Sí |
| **Equipo** | MTBF, MTTR, disponibilidad y tendencia Crow-AMSAA: ¿el equipo mejora o empeora? | Sí (≥ 4 fallas para la tendencia) |
| **Componente** | Weibull con censura: ¿hay desgaste? ¿cada cuánto conviene el preventivo y cuánto ahorra? | No (≥ 3 vidas observadas; CONFIABLE con ≥ 8) |
| **Plato / navajas** | Horas de operación entre cambios por línea (exploratorio) | Sí |

## Instalación (una vez)
```bash
cd analisis
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso
```bash
# Opción 1 (recomendada): descarga el Sheet como .xlsx (Archivo → Descargar)
python analisis_paros.py --xlsx "Base de Datos Produccion 2026.xlsx"

# Opción 2: directo del Sheet (service_account.json en esta carpeta, nunca en el repo)
export SPREADSHEET_KEY="..."
python analisis_paros.py --sheets

# Opción 3: CSV de la vista Exportar (+ catálogo de componentes opcional)
python analisis_paros.py --csv paros.csv --componentes cat_componentes.csv
```
Parámetros: `--razon-costo 5` (costo de una falla ÷ costo de un preventivo),
`--ahorro-min 0.10` (ahorro mínimo para recomendar preventivo por edad),
`--min-fallas 8` (fallas para marcar un Weibull como CONFIABLE).

## Salidas (`salidas_analisis/`, va en `.gitignore`)
`reporte_confiabilidad.xlsx` (una pestaña por tabla), `resumen.txt` y los mismos
CSV sueltos: Auditoria, Pareto_no_programado, Pareto_programado,
Pareto_componentes, Equipos_MTBF_MTTR, Weibull_componentes, Vidas_componentes,
Plato_navajas_resumen, Plato_navajas_detalle, Intervenciones.

## Reglas que usa el modelo
- **Evento** = paro con sus tramos multiturno unidos. Inicio = fecha + `HORA DE INICIO`
  (si la hora es mayor que la de captura, el paro empezó el día anterior).
- **Horas de operación** = calendario − *unión* de paros de la línea (no se resta dos
  veces un traslape; «Línea 1 y 2» detiene ambas). Proxy hasta integrar el OEE.
- **Clasificación por componente** (una por cierre de ACRS, no por paro):
  Reemplazo en paro no programado → **FALLA**; Reemplazo en paro programado →
  **PREVENTIVO** (vida censurada); Reparación → aparte; Ajuste/Revisión → no afecta la vida.
- El **equipo del componente** sale de `cat_componentes`, no de lo que capturó producción.
- **β** se corrige por sesgo de muestra chica e incluye IC 90 % por razón de
  verosimilitud. Solo se declara desgaste si el límite inferior es > 1. Validado por
  simulación: con fallas puramente aleatorias se equivoca ≈ 5 % de las veces.
- Solo se recomienda preventivo por edad si hay desgaste **y** el ahorro frente a
  correr hasta la falla es ≥ `--ahorro-min`.
