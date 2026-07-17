"""
correo_notificador.py
=====================
Módulo para el envío de alertas automáticas por correo electrónico.
Maneja de forma dinámica conexiones estándar (puerto 587 con STARTTLS)
y conexiones seguras en la nube (puerto 465 con SSL directo).
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "correo_island.env"


def _leer_config_archivo() -> dict:
    """Lee el archivo .env local si existe."""
    if not CONFIG_PATH.exists():
        return {}
    valores: dict[str, str] = {}
    try:
        for linea in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            limpia = linea.strip()
            if not limpia or limpia.startswith("#") or "=" not in limpia:
                continue
            clave, valor = limpia.split("=", 1)
            valores[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        return {}
    return valores


def obtener_config_smtp() -> dict:
    """Carga las variables desde Render o desde el archivo .env local."""
    archivo = _leer_config_archivo()

    def _valor(clave: str, defecto: str = "") -> str:
        return os.getenv(clave, archivo.get(clave, defecto)).strip()

    return {
        "host": _valor("ASISTENCIA_SMTP_HOST", "smtp.gmail.com"),
        "port": _valor("ASISTENCIA_SMTP_PORT", "587"),
        "tls": _valor("ASISTENCIA_SMTP_TLS", "1"),
        "user": _valor("ASISTENCIA_SMTP_USER", ""),
        "password": _valor("ASISTENCIA_SMTP_PASSWORD", ""),
        "from": _valor("ASISTENCIA_SMTP_FROM", ""),
    }


def enviar_correo_smtp(config: dict, mensaje: EmailMessage):
    """Gestiona la conexión con el servidor SMTP según el puerto configurado con autorecuperación."""
    contexto_ssl = ssl.create_default_context()
    
    host = config.get("host", "smtp.gmail.com")
    puerto = str(config.get("port", "587")).strip()
    usuario = config.get("user", "")
    password = config.get("password", "")
    use_tls = str(config.get("tls", "1"))

    try:
        # SI ES PUERTO 465: Conexión SSL implícita desde el inicio (Requerido en Render)
        if puerto == "465":
            logger.info("Iniciando conexión segura mediante SMTP_SSL (Puerto 465)...")
            with smtplib.SMTP_SSL(host, int(puerto), context=contexto_ssl, timeout=15) as servidor:
                servidor.login(usuario, password)
                servidor.send_message(mensaje)
                
        # SI ES OTRO PUERTO (Como el 587): Conexión estándar + STARTTLS
        else:
            logger.info(f"Iniciando conexión estándar mediante SMTP (Puerto {puerto})...")
            with smtplib.SMTP(host, int(puerto), timeout=15) as servidor:
                if use_tls == "1" or use_tls == "True":
                    servidor.starttls(context=contexto_ssl)
                servidor.login(usuario, password)
                servidor.send_message(mensaje)
                
    except OSError as exc:
        # SALVAVIDAS AUTOMÁTICO: Si el puerto configurado falla por bloqueo de red en la nube, se auto-repara usando 465 SSL
        if puerto != "465":
            logger.warning(f"Error de red detectado en puerto {puerto} ({exc}). Aplicando auto-fallback al Puerto 465 SSL...")
            with smtplib.SMTP_SSL(host, 465, context=contexto_ssl, timeout=15) as servidor:
                servidor.login(usuario, password)
                servidor.send_message(mensaje)
        else:
            raise exc


def enviar_alerta_correo(estudiante: dict, registro: dict, config_correo: dict) -> tuple[bool, str]:
    """
    Función principal llamada por la lógica de negocio para despachar las alertas.
    Adapta los diccionarios de entrada para compilar dinámicamente el correo.
    Retorna una tupla (éxito, detalle) requerida por la interfaz de NiceGUI.
    """
    # 1. Unificar configuración base con los datos pasados desde la UI de NiceGUI
    config = obtener_config_smtp()
    if config_correo:
        if "host" in config_correo: config["host"] = config_correo["host"]
        if "port" in config_correo: config["port"] = config_correo["port"]
        if "password" in config_correo: config["password"] = config_correo["password"]
        if "from" in config_correo: config["from"] = config_correo["from"]
        if "username" in config_correo: config["user"] = config_correo["username"]
        if "user" in config_correo: config["user"] = config_correo["user"]
        if "tls" in config_correo: config["tls"] = "1" if config_correo["tls"] else "0"
    
    # 2. Validaciones iniciales críticas
    destinatario = str(estudiante.get("correo_encargado", "")).strip()
    if not destinatario:
        return False, "El estudiante no posee un correo electrónico de encargado registrado."
        
    if not config.get("user") or not config.get("password"):
        logger.error("No se pudo enviar el correo: Credenciales SMTP ausentes o incompletas.")
        return False, "Credenciales SMTP incompletas en la configuración del sistema."

    # 3. Procesamiento y formateo de los datos del estudiante
    nombre_alumno = f"{estudiante.get('nombre', '')} {estudiante.get('apellido', '')}".strip()
    tipo_evento = registro.get("tipo_evento", "MOVIMIENTO").upper()
    hora = registro.get("hora", "")
    seccion = estudiante.get("codigo_seccion", "")
    turno = registro.get("turno", "")
    alerta = registro.get("estado_alerta", "NORMAL")
    detalle_alerta = registro.get("detalle_alerta", "")

    # Diseñar el asunto según el tipo de movimiento
    icono = "🟢" if tipo_evento == "INGRESO" else "🔴"
    asunto = f"{icono} Island - Alerta de {tipo_evento.capitalize()}: {nombre_alumno}"

    # Construcción limpia y legible del cuerpo en texto plano
    cuerpo = (
        f"SISTEMA DE CONTROL DE ASISTENCIA 'ISLAND'\n"
        f"{'='*45}\n\n"
        f"Estimado encargado, se le notifica que se ha registrado un nuevo movimiento:\n\n"
        f"  • Estudiante: {nombre_alumno}\n"
        f"  • Sección: {seccion}\n"
        f"  • Movimiento: {tipo_evento}\n"
        f"  • Hora de registro: {hora}\n"
        f"  • Turno: {turno}\n"
        f"  • Estado: {alerta}\n"
        f"  • Detalle: {detalle_alerta}\n\n"
        f"{'='*45}\n"
        f"Este es un mensaje automatizado generado por el sistema Island. Por favor, no responda a este correo."
    )

    # 4. Construcción física del objeto EmailMessage
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = config["from"] or config["user"]
    mensaje["To"] = destinatario
    mensaje.set_content(cuerpo)

    # 5. Ejecución del despacho seguro
    try:
        enviar_correo_smtp(config, mensaje)
        logger.info(f"¡Alerta de correo enviada con éxito a {destinatario}!")
        return True, f"Correo enviado exitosamente a {destinatario}"
    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"No se pudo enviar el correo a {destinatario}: {error_msg}")
        return False, f"Error del servidor SMTP: {error_msg}"