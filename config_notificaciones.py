"""
config_notificaciones.py
=========================
Lectura/escritura del archivo correo_island.env: ahora guarda tanto la
configuracion de correo SMTP (igual que antes) como la de WhatsApp via
CallMeBot y la de conexion a MySQL. Se mantiene el mismo formato de
archivo "CLAVE=valor" que ya usaba el sistema.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CORREO_CONFIG_PATH = BASE_DIR / "correo_island.env"


def _leer_config_local() -> dict:
    if not CORREO_CONFIG_PATH.exists():
        return {}
    valores: dict[str, str] = {}
    try:
        for linea in CORREO_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            limpia = linea.strip()
            if not limpia or limpia.startswith("#") or "=" not in limpia:
                continue
            clave, valor = limpia.split("=", 1)
            valores[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        return {}
    return valores


def cargar_config_correo() -> dict:
    archivo = _leer_config_local()
    host = os.getenv("ASISTENCIA_SMTP_HOST", archivo.get("ASISTENCIA_SMTP_HOST", "")).strip()
    usuario = os.getenv("ASISTENCIA_SMTP_USER", archivo.get("ASISTENCIA_SMTP_USER", "")).strip()
    contrasena = os.getenv("ASISTENCIA_SMTP_PASSWORD", archivo.get("ASISTENCIA_SMTP_PASSWORD", "")).strip()
    puerto = os.getenv("ASISTENCIA_SMTP_PORT", archivo.get("ASISTENCIA_SMTP_PORT", "587")).strip()
    correo_origen = os.getenv("ASISTENCIA_SMTP_FROM", archivo.get("ASISTENCIA_SMTP_FROM", usuario)).strip()
    tls = os.getenv("ASISTENCIA_SMTP_TLS", archivo.get("ASISTENCIA_SMTP_TLS", "1")).strip().lower() not in {"0", "false", "no"}

    try:
        puerto_num = int(puerto)
    except ValueError:
        puerto_num = 587

    return {
        "host": host,
        "port": puerto_num,
        "username": usuario,
        "password": contrasena,
        "from": correo_origen or usuario,
        "tls": tls,
    }


def cargar_config_whatsapp() -> dict:
    """Configuracion para enviar WhatsApp usando CallMeBot
    (https://www.callmebot.com/blog/free-api-whatsapp-messages/).

    Cada encargado que reciba avisos por WhatsApp debe activar su propio
    "apikey" de CallMeBot (se obtiene enviando un mensaje desde su propio
    numero al bot de CallMeBot). ASISTENCIA_WHATSAPP_APIKEY es la apikey
    por defecto que se usa si el estudiante no tiene una propia guardada.
    """
    archivo = _leer_config_local()

    def _valor(clave: str, defecto: str = "") -> str:
        return os.getenv(clave, archivo.get(clave, defecto)).strip()

    activo = _valor("ASISTENCIA_WHATSAPP_ACTIVO", "1").lower() not in {"0", "false", "no"}

    return {
        "activo": activo,
        "apikey": _valor("ASISTENCIA_WHATSAPP_APIKEY", ""),
    }


def cargar_config_db() -> dict:
    archivo = _leer_config_local()

    def _valor(clave: str, defecto: str = "") -> str:
        return os.getenv(clave, archivo.get(clave, defecto)).strip()

    return {
        "host": _valor("ASISTENCIA_DB_HOST", "127.0.0.1"),
        "port": _valor("ASISTENCIA_DB_PORT", "3306"),
        "user": _valor("ASISTENCIA_DB_USER", "root"),
        "password": _valor("ASISTENCIA_DB_PASSWORD", ""),
        "database": _valor("ASISTENCIA_DB_NAME", "control_asistencia"),
    }


def guardar_config(correo: dict | None = None, whatsapp: dict | None = None, db: dict | None = None) -> bool:
    """Regrava correo_island.env conservando los valores no editados."""
    actual_correo = cargar_config_correo()
    actual_whatsapp = cargar_config_whatsapp()
    actual_db = cargar_config_db()

    if correo:
        actual_correo.update(correo)
    if whatsapp:
        actual_whatsapp.update(whatsapp)
    if db:
        actual_db.update(db)

    lineas = [
        "# Configuracion de Island (generado desde la app).",
        "",
        "# ---- Base de datos MySQL / phpMyAdmin ----",
        f"ASISTENCIA_DB_HOST={actual_db.get('host', '127.0.0.1')}",
        f"ASISTENCIA_DB_PORT={actual_db.get('port', '3306')}",
        f"ASISTENCIA_DB_USER={actual_db.get('user', 'root')}",
        f"ASISTENCIA_DB_PASSWORD={actual_db.get('password', '')}",
        f"ASISTENCIA_DB_NAME={actual_db.get('database', 'control_asistencia')}",
        "",
        "# ---- Correo SMTP (alertas por correo) ----",
        f"ASISTENCIA_SMTP_HOST={actual_correo.get('host', '')}",
        f"ASISTENCIA_SMTP_PORT={actual_correo.get('port', 587)}",
        f"ASISTENCIA_SMTP_TLS={'1' if actual_correo.get('tls', True) else '0'}",
        f"ASISTENCIA_SMTP_USER={actual_correo.get('username', '')}",
        f"ASISTENCIA_SMTP_PASSWORD={actual_correo.get('password', '')}",
        f"ASISTENCIA_SMTP_FROM={actual_correo.get('from', actual_correo.get('username', ''))}",
        "",
        "# ---- WhatsApp via CallMeBot ----",
        f"ASISTENCIA_WHATSAPP_ACTIVO={'1' if actual_whatsapp.get('activo', True) else '0'}",
        f"ASISTENCIA_WHATSAPP_APIKEY={actual_whatsapp.get('apikey', '')}",
        "",
    ]
    try:
        CORREO_CONFIG_PATH.write_text("\n".join(lineas), encoding="utf-8")
        return True
    except OSError:
        return False
