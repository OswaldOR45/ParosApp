"""
Notificaciones a Telegram al registrar un paro.
Enruta al grupo correcto según quién fue solicitado:
  RSI   -> grupo RSI
  STEO  -> grupo STEO
  AMBOS -> ambos grupos

FALLA SILENCIOSA: esta función se llama DESPUÉS de que el paro ya quedó
guardado en Sheets. Si algo falla aquí (sin internet, token mal, secrets
incompletos, timeout), NO debe propagar la excepción: si lo hiciera, el
operador vería "No se pudo guardar", volvería a dar clic y duplicaría el paro.
"""
import logging

import requests
import streamlit as st

log = logging.getLogger(__name__)

# Los tramos de continuación (paros multi-turno) no se notifican: el grupo ya
# recibió el aviso cuando se abrió el paro. Cambia a True si sí los quieren.
NOTIFICAR_CONTINUACIONES = False


def _destinos(acr: str) -> list[str]:
    """Devuelve lista de chat_ids según el valor de necesita_acr."""
    tg = st.secrets.get("telegram", {})
    ids = []
    if acr in ("RSI", "AMBOS") and tg.get("chat_id_rsi"):
        ids.append(str(tg["chat_id_rsi"]))
    if acr in ("STEO", "AMBOS") and tg.get("chat_id_steo"):
        ids.append(str(tg["chat_id_steo"]))
    return ids


def _construir_mensaje(registro: dict) -> str:
    tipo = "NO PROGRAMADO" if registro.get("ini_noprog") else "PROGRAMADO"
    hi = registro.get("ini_noprog") or registro.get("ini_prog", "")
    hf = registro.get("fin_noprog") or registro.get("fin_prog", "")
    dur = registro.get("dur_noprog") or registro.get("dur_prog", "")
    desc = str(registro.get("descripcion", "") or "").strip()
    icono = "🔴" if tipo == "NO PROGRAMADO" else "🟡"
    en_curso = str(registro.get("paro_en_curso", "")).upper() in ("SÍ", "SI")

    lineas = [
        f"{icono} Nuevo paro registrado" + ("  ⏳ (CONTINÚA EN CURSO)" if en_curso else ""),
        "",
        f"📍 Línea: {registro.get('linea', '')}  |  Área: {registro.get('area', '')}",
        f"⚙️ Equipo: {registro.get('equipo', '')}",
        f"🛑 Motivo: {registro.get('motivo', '')} ({tipo})",
        f"🕐 Inicio: {hi}  |  Fin: {hf}  |  Duración: {dur} h",
        f"👷 Turno: {registro.get('turno', '')}  |  Apoyo: {registro.get('necesita_acr', '')}",
    ]
    if desc:
        lineas.append(f"📝 Nota: {desc}")
    lineas.append(f"🆔 {registro.get('id_paro', '')}")
    return "\n".join(lineas)


def notificar_paro(registro: dict) -> None:
    """Envía el aviso. Nunca lanza excepción."""
    try:
        if (not NOTIFICAR_CONTINUACIONES
                and str(registro.get("es_continuacion", "")).upper() in ("SÍ", "SI")):
            return

        acr = str(registro.get("necesita_acr", "NO")).strip().upper()
        destinos = _destinos(acr)
        if not destinos:
            return

        token = st.secrets["telegram"]["token"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        texto = _construir_mensaje(registro)  # texto plano, sin parse_mode

        for chat_id in destinos:
            try:
                r = requests.post(url, json={"chat_id": chat_id, "text": texto},
                                  timeout=5)
                if not r.ok:
                    log.warning("Telegram %s respondió %s: %s",
                                chat_id, r.status_code, r.text[:200])
            except requests.RequestException as e:
                log.warning("Telegram %s no disponible: %s", chat_id, e)
    except Exception as e:  # secrets incompletos, etc.
        log.warning("Notificación Telegram omitida: %s", e)