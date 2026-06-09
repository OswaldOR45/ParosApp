# Análisis de confiabilidad — Plan Maestro de Mantenimiento Preventivo

Motor de análisis que lee los datos capturados por **ParosApp** (Google Sheet o
CSV exportado), audita la calidad, calcula Pareto + MTBF/MTTR y ajusta el
modelo **Weibull** por componente para proponer intervalos óptimos de
mantenimiento preventivo.

Es un proceso **fuera de línea**: se corre a demanda (semanal, mensual o cuando
se quiera refrescar el modelo). **NO va dentro de la app Streamlit** — son dos
sistemas con vidas distintas que comparten la misma fuente de datos.

## Instalación (una sola vez)

```bash
cd analisis
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

### Modo CSV (más simple)
Exporta primero desde la vista "Exportar" de la app y corre:
```bash
python analisis_paros.py --csv paros.csv
```

### Modo Sheets (lee directo del Google Sheet)
Requiere `service_account.json` en esta carpeta y la variable de entorno:
```bash
export SPREADSHEET_KEY="..."
python analisis_paros.py --sheets
```

### Parámetros opcionales
- `--min-fallas 8` — Mínimo de fallas por componente para marcar el modelo
  como **CONFIABLE** (default 8). Bajar a 5–6 si los datos son aún escasos.
- `--razon-costo 5.0` — Razón costo correctivo / costo preventivo. Afecta el
  intervalo óptimo recomendado.

## Salidas

Se escriben en `salidas_analisis/` (se crea sola; va en `.gitignore`):

| Archivo | Contenido |
|---|---|
| `auditoria_calidad.csv` | Estado de llenado de campos clave |
| `pareto_motivos.csv` | Horas perdidas por motivo (regla 80/20) |
| `pareto_componentes.csv` | Horas perdidas por componente |
| `mtbf_mttr.csv` | MTBF / MTTR por equipo-componente |
| `historial_fallas.csv` | Insumo de Weibull (tiempo entre fallas) |
| `weibull_resultados.csv` | β, η, intervalo óptimo, R(t) |
| `eventos_reparacion.csv` | Reparaciones (sistema reparable, análisis aparte) |
| `resumen.txt` | Lectura ejecutiva de la corrida |

## Notas

- El **TBF operativo** que produce el script es un proxy: horas calendario
  menos downtime de la línea. El dato definitivo serán las horas reales del
  sistema OEE del Ing. Barba — el script está preparado para incorporarlo.
- Eventos con `tipo_intervencion = Reemplazo` cuentan como renovaciones del
  reloj de vida (Weibull). Las `Reparaciones` salen aparte. Los `Ajustes` se
  excluyen del conteo de fallas.