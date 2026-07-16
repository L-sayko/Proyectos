"""
correo_notificador.py
======================
Envio de alertas por correo SMTP. Misma logica que la version original
en Tkinter (soporta puerto 465 con SSL directo y 587 con STARTTLS).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("island.correo")

NOMBRE_SISTEMA = "Island"


def enviar_correo_smtp(config: dict, mensaje: EmailMessage):
    """Envia un mensaje ya construido usando la configuracion SMTP dada."""
    contexto = ssl.create_default_context()
    if int(config.get("port") or 0) == 465:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=contexto) as servidor:
            if config["username"]:
                servidor.login(config["username"], config["password"])
            servidor.send_message(mensaje)
        return

    with smtplib.SMTP(config["host"], config["port"], timeout=15) as servidor:
        servidor.ehlo()
        if config["tls"]:
            servidor.starttls(context=contexto)
            servidor.ehlo()
        if config["username"]:
            servidor.login(config["username"], config["password"])
        servidor.send_message(mensaje)


def construir_mensaje_alerta(estudiante: dict, registro: dict, correo_origen: str, correo_destino: str) -> EmailMessage:
    mensaje = EmailMessage()
    nombre = f"{estudiante.get('nombre', '')} {estudiante.get('apellido', '')}".strip()
    mensaje["Subject"] = f"{NOMBRE_SISTEMA} - Alerta de asistencia"
    mensaje["From"] = f"{NOMBRE_SISTEMA} <{correo_origen}>"
    mensaje["To"] = correo_destino
    mensaje.set_content(
        "\n".join(
            [
                f"{NOMBRE_SISTEMA}",
                "Alerta de asistencia",
                "",
                f"Estudiante: {nombre}",
                f"Codigo: {estudiante.get('id_estudiante', '')}",
                f"Seccion: {estudiante.get('codigo_seccion', '')}",
                f"Fecha: {registro.get('fecha', '')}",
                f"Hora: {registro.get('hora', '')}",
                f"Movimiento: {registro.get('tipo_evento', '')}",
                f"Alerta: {registro.get('estado_alerta', '')}",
                f"Detalle: {registro.get('detalle_alerta', '')}",
            ]
        )
    )
    return mensaje


def enviar_alerta_correo(estudiante: dict, registro: dict, config: dict) -> tuple[bool, str]:
    correo_destino = str(estudiante.get("correo_encargado", "")).strip()
    if not correo_destino:
        return False, "El estudiante no tiene correo de encargado registrado."

    if not config["host"] or not config["username"] or not config["password"]:
        return False, "El correo SMTP no esta configurado (host/usuario/contraseña)."

    mensaje = construir_mensaje_alerta(estudiante, registro, config.get("from") or config["username"], correo_destino)
    try:
        enviar_correo_smtp(config, mensaje)
        logger.info("Correo de alerta enviado a %s (estudiante %s).", correo_destino, estudiante.get("id_estudiante"))
        return True, f"Se notificó a {correo_destino}."
    except Exception as exc:  # noqa: BLE001
        error = str(exc) or exc.__class__.__name__
        logger.error("No se pudo enviar el correo a %s: %s", correo_destino, error, exc_info=True)
        return False, error


def construir_mensaje_texto_alerta(estudiante: dict, registro: dict) -> str:
    """Texto plano de la alerta, usado tanto para WhatsApp como para
    mostrar avisos en la interfaz."""
    nombre = f"{estudiante.get('nombre', '')} {estudiante.get('apellido', '')}".strip()
    icono = "🟢" if registro.get("tipo_evento") == "INGRESO" else "🔴"
    return (
        f"{icono} {NOMBRE_SISTEMA} - Alerta de asistencia\n"
        f"Estudiante: {nombre}\n"
        f"Sección: {estudiante.get('codigo_seccion', '')}\n"
        f"Movimiento: {registro.get('tipo_evento', '')}  •  {registro.get('hora', '')}\n"
        f"Turno: {registro.get('turno', '')}\n"
        f"Alerta: {registro.get('estado_alerta', '')}\n"
        f"Detalle: {registro.get('detalle_alerta', '')}"
    )
