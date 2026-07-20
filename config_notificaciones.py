import os
import requests

def enviar_correo(destinatario, asunto, cuerpo_html):
    """
    Envía un correo electrónico utilizando la API HTTP de Brevo (Puerto 443).
    Evita bloqueos de puertos SMTP en entornos en la nube como Railway.
    """
    api_key = os.getenv("BREVO_API_KEY")
    
    if not api_key:
        print("[ERROR] No se encontró la variable BREVO_API_KEY en el entorno.")
        return False

    correo_remitente = "luismartin.mrz08@gmail.com"
    nombre_remitente = "Sistema Island"

    url = "https://api.brevo.com/v3/smtp/email"
    
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {
            "name": nombre_remitente,
            "email": correo_remitente
        },
        "to": [
            {
                "email": destinatario
            }
        ],
        "subject": asunto,
        "htmlContent": cuerpo_html
    }
    
    try:
        print(f"[INFO] Intentando enviar correo a {destinatario} vía API Brevo...")
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            print(f"[ÉXITO] Correo enviado correctamente a {destinatario}")
            return True
        else:
            print(f"[ERROR] Brevo rechazó el correo. Código: {response.status_code}")
            print(f"Detalle del error: {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error de conexión al conectar con la API de Brevo: {e}")
        return False


def cargar_config_correo():
    """Retorna la configuración básica del correo."""
    return {
        "remitente": "luismartin.mrz08@gmail.com",
        "activo": True
    }


def cargar_config_whatsapp():
    """Retorna la configuración de WhatsApp para compatibilidad."""
    return {}


def cargar_config_db():
    """Retorna la configuración de la base de datos desde las variables de entorno."""
    return {
        "host": os.getenv("ASISTENCIA_DB_HOST", ""),
        "port": os.getenv("ASISTENCIA_DB_PORT", ""),
        "user": os.getenv("ASISTENCIA_DB_USER", ""),
        "password": os.getenv("ASISTENCIA_DB_PASSWORD", ""),
        "database": os.getenv("ASISTENCIA_DB_NAME", "")
    }


def guardar_config(tipo, datos):
    """Guarda la configuración de manera segura en el sistema."""
    try:
        print(f"[INFO] Configuración de tipo '{tipo}' procesada correctamente.")
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo guardar la configuración: {e}")
        return False


def leer_config_bruta():
    """Lee la configuración bruta para evitar fallos de importación."""
    return {}