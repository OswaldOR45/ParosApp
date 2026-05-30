"""Cálculos de tiempo (duración de paros) en formato Horas y Minutos."""
from datetime import datetime, timedelta, date, time


def _delta_min(fecha_inicio: date, hora_inicio: time, hora_fin: time) -> int:
    """Minutos totales entre inicio y fin. Maneja el cruce de medianoche."""
    inicio = datetime.combine(fecha_inicio, hora_inicio)
    fin = datetime.combine(fecha_inicio, hora_fin)
    if fin <= inicio:
        fin += timedelta(days=1)
    return int(round((fin - inicio).total_seconds() / 60))


def duracion_hhmm(fecha_inicio: date, hora_inicio: time, hora_fin: time) -> str:
    """
    Devuelve la duración como 'H:MM' (ej. '1:30' = 1 hora 30 min).
    Se escribe con USER_ENTERED para que Sheets lo guarde como valor de
    duración (sumable por Ricardo) y lo muestre en formato [h]:mm.
    """
    total = _delta_min(fecha_inicio, hora_inicio, hora_fin)
    return f"{total // 60}:{total % 60:02d}"


def total_minutos(fecha_inicio: date, hora_inicio: time, hora_fin: time) -> int:
    return _delta_min(fecha_inicio, hora_inicio, hora_fin)


def hhmm_a_horas(valor) -> float:
    """
    Convierte 'H:MM' (o número) a horas decimales para gráficos/sumas.
    Tolerante: acepta '1:30', '1.5', 1.5, '' -> 0.0
    """
    if valor is None or valor == "":
        return 0.0
    s = str(valor).strip()
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
