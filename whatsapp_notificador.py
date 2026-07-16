"""
whatsapp_notificador.py
========================
Envio de mensajes de WhatsApp usando CallMeBot
(https://www.callmebot.com/blog/free-api-whatsapp-messages/).

CallMeBot expone un endpoint HTTP muy simple:
    https://api.callmebot.com/whatsapp.php?phone=<numero>&text=<mensaje>&apikey=<apikey>

Cada encargado que quiera recibir avisos por WhatsApp debe:
  1. Agregar el numero de CallMeBot a sus contactos.
  2. Enviarle desde su propio WhatsApp el mensaje: "I allow callmebot to send me messages"
  3. CallMeBot le responde con una "apikey" personal.

En este sistema, esa apikey se puede guardar por defecto en la
configuracion (ASISTENCIA_WHATSAPP_APIKEY) o quedar asociada al
telefono del estudiante si en el futuro se requiere una por encargado.
"""

from __future__ import annotations

import logging
import re
import urllib.parse

import requests

logger = logging.getLogger("island.whatsapp")

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def normalizar_telefono(telefono: str) -> str:
    """Deja solo digitos y el '+' inicial (formato que espera CallMeBot,
    ej. +50370000000)."""
    telefono = (telefono or "").strip()
    if not telefono:
        return ""
    solo_digitos = re.sub(r"[^0-9+]", "", telefono)
    if not solo_digitos.startswith("+"):
        solo_digitos = "+" + solo_digitos.lstrip("+")
    return solo_digitos


def enviar_whatsapp(telefono: str, mensaje: str, apikey: str) -> tuple[bool, str]:
    """Envia un mensaje de WhatsApp via CallMeBot.

    Devuelve (exito, detalle) para que la interfaz pueda mostrar el
    resultado, igual que se hace con el envio de correo.
    """
    numero = normalizar_telefono(telefono)
    if not numero:
        return False, "El estudiante no tiene un numero de WhatsApp registrado."
    if not apikey:
        return False, "Falta configurar la apikey de CallMeBot."

    params = {
        "phone": numero,
        "text": mensaje,
        "apikey": apikey,
    }
    url = f"{CALLMEBOT_URL}?{urllib.parse.urlencode(params)}"

    try:
        respuesta = requests.get(url, timeout=15)
        cuerpo = (respuesta.text or "").strip()
        if respuesta.status_code == 200 and "Message queued" in cuerpo:
            logger.info("WhatsApp enviado a %s via CallMeBot.", numero)
            return True, "Mensaje enviado."
        logger.warning("CallMeBot respondio %s: %s", respuesta.status_code, cuerpo)
        return False, cuerpo or f"CallMeBot respondio con estado {respuesta.status_code}."
    except requests.RequestException as exc:
        logger.error("Error al enviar WhatsApp via CallMeBot: %s", exc)
        return False, str(exc)
