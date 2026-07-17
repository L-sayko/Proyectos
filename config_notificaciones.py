import os
import requests

def enviar_correo(destinatario, asunto, cuerpo_html):
    """
    Envía un correo electrónico utilizando la API HTTP de Brevo (Puerto 443).
    Evita bloqueos de puertos SMTP en entornos en la nube como Railway.
    """
    # 1. Obtener la API Key desde las variables de entorno de Railway
    api_key = os.getenv("BREVO_API_KEY")
    
    if not api_key:
        print("[ERROR] No se encontró la variable BREVO_API_KEY en el entorno.")
        return False

    # 2. Configurar el remitente (El Gmail que tienes registrado en Brevo)
    correo_remitente = "luismartin.mrz08@gmail.com"
    nombre_remitente = "Sistema Island"

    # 3. Construir la petición para la API de Brevo
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
    
    # 4. Realizar el envío de forma segura mediante HTTPS
    try:
        print(f"[INFO] Intentando enviar correo a {destinatario} vía API Brevo...")
        response = requests.post(url, json=payload, headers=headers)
        
        # El código 201 significa "Created" (Correo aceptado por Brevo)
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