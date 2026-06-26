"""
Notificaciones a Telegram al registrar un paro.
Enruta al grupo correcto según quién fue solicitado:
  RSI   -> grupo RSI
  STEO  -> grupo STEO
  AMBOS -> ambos grupos
"""
import requests
import streamlit as st


def _token() -> str:
    return st.secrets["telegram"]["token"]

def _destinos(acr: str) -> list[str]:
    """Devuelve lista de chat_ids según el valor de necesita_acr."""
    ids = []
    if acr in ("RSI", "AMBOS"):
        ids.append(st.secrets["telegram"]["chat_id_rsi"])
    if acr in ("STEO", "AMBOS"):
        ids.append(st.secrets["telegram"]["chat_id_steo"])
    return ids


def _construir_mensaje(registro: dict) -> str:
    ini_noprog = registro.get("ini_noprog", "")
    tipo = "NO PROGRAMADO" if ini_noprog else "PROGRAMADO"
    motivo  = registro.get("motivo", "")
    linea   = registro.get("linea", "")
    area    = registro.get("area", "")
    equipo  = registro.get("equipo", "")
    turno   = registro.get("turno", "")
    acr     = registro.get("necesita_acr", "")
    hi      = registro.get("ini_noprog") or registro.get("ini_prog", "")
    hf      = registro.get("fin_noprog") or registro.get("fin_prog", "")
    dur     = registro.get("dur_noprog") or registro.get("dur_prog", "")
    desc    = registro.get("descripcion", "").strip()
    id_paro = registro.get("id_paro", "")
    icono   = "🔴" if tipo == "NO PROGRAMADO" else "🟡"

    lineas = [
        f"{icono} *Nuevo paro registrado*",
        f"",
        f"📍 *Línea:* {linea} | *Área:* {area}",
        f"⚙️ *Equipo:* {equipo}",
        f"🛑 *Motivo:* {motivo} \\({tipo}\\)",
        f"🕐 *Inicio:* {hi} | *Fin:* {hf} | *Duración:* {dur} h",
        f"👷 *Turno:* {turno} | *Apoyo:* {acr}",
    ]
    if desc:
        lineas.append(f"📝 *Nota:* {desc}")
    lineas.append(f"🆔 `{id_paro}`")

    return "\n".join(lineas)


def _enviar(chat_id: str, texto: str) -> None:
    url = f"https://api.telegram.org/bot{_token()}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "MarkdownV2",
    }
    requests.post(url, json=payload, timeout=5)
def notificar_paro(registro: dict) -> None:
    acr = str(registro.get("necesita_acr", "NO")).upper()
    destinos = _destinos(acr)
    if not destinos:
        return

    texto = _construir_mensaje(registro)

    for chat_id in destinos:
        url = f"https://api.telegram.org/bot{_token()}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": texto,
            "parse_mode": "MarkdownV2",
        }
        r = requests.post(url, json=payload, timeout=5)
        st.write(r.json())  # ← muestra el error en pantalla temporalmente