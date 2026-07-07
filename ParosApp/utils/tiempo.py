"""Cálculos de tiempo (duración de paros) en formato Horas y Minutos."""
from datetime import datetime, timedelta, date, time

from config import settings

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


def fin_de_turno_actual(ahora: datetime) -> time:
    """
    Dado un datetime, devuelve la hora de fin del intervalo de turno en que cae.
    Maneja el turno nocturno que cruza medianoche (21:00-05:00).

    Ejemplos:
        08:30 → 13:00   (turno 05-13)
        14:00 → 21:00   (turno 13-21)
        22:00 → 05:00   (turno 21-05)
        03:00 → 05:00   (turno 21-05, madrugada)
    """
    t = ahora.time()
    for ini_str, fin_str in settings.INTERVALOS_TURNO:
        h_ini, m_ini = map(int, ini_str.split(":"))
        h_fin, m_fin = map(int, fin_str.split(":"))
        t_ini = time(h_ini, m_ini)
        t_fin = time(h_fin, m_fin)

        if t_ini < t_fin:
            # Turno normal (no cruza medianoche)
            if t_ini <= t < t_fin:
                return t_fin
        else:
            # Turno nocturno: 21:00 → 05:00 (cruza medianoche)
            if t >= t_ini or t < t_fin:
                return t_fin

    # Fallback de seguridad (no debería ocurrir si los intervalos cubren 24h)
    return time(5, 0)


def inicio_de_turno_siguiente(ahora: datetime) -> time:
    """
    Devuelve la hora de inicio del siguiente intervalo de turno.
    Es siempre igual al fin del turno actual.
    """
    return fin_de_turno_actual(ahora)


def sumar_duraciones_hhmm(duraciones: list) -> str:
    """
    Suma una lista de duraciones en formato 'H:MM' y devuelve el total en 'H:MM'.
    Ignora valores vacíos o inválidos.
    """
    total_min = 0
    for d in duraciones:
        s = str(d).strip()
        if not s or ":" not in s:
            continue
        try:
            h, m = s.split(":")[:2]
            total_min += int(h) * 60 + int(m)
        except ValueError:
            continue
    return f"{total_min // 60}:{total_min % 60:02d}"


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