"""
seguridad.py
=============
Utilidades para el manejo seguro de contraseñas de los usuarios del
sistema (administradores/profesores). Usa PBKDF2-HMAC-SHA256 con sal
aleatoria por usuario (no requiere librerías externas).

Formato guardado en la columna `password`:
    pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>

Las contraseñas creadas antes de esta versión (texto plano, ej. el
"admin123" / "profesor123" que trae el esquema de ejemplo) se siguen
reconociendo: `verificar_password` compara también en texto plano como
respaldo, y `repository.verificar_credenciales` aprovecha esto para migrar
la contraseña a formato cifrado automáticamente la primera vez que el
usuario inicia sesión con éxito.
"""

from __future__ import annotations

import hashlib
import hmac
import os

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 260_000


def hash_password(password: str) -> str:
    sal = os.urandom(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, ITERACIONES)
    return f"{ALGORITMO}${ITERACIONES}${sal.hex()}${derivado.hex()}"


def es_hash(password_guardado: str) -> bool:
    return password_guardado.startswith(f"{ALGORITMO}$")


def verificar_password(password_ingresado: str, password_guardado: str) -> bool:
    if not password_guardado:
        return False

    if es_hash(password_guardado):
        try:
            _, iteraciones_txt, sal_hex, hash_hex = password_guardado.split("$", 3)
            iteraciones = int(iteraciones_txt)
            sal = bytes.fromhex(sal_hex)
            esperado = bytes.fromhex(hash_hex)
        except (ValueError, TypeError):
            return False
        derivado = hashlib.pbkdf2_hmac("sha256", password_ingresado.encode("utf-8"), sal, iteraciones)
        return hmac.compare_digest(derivado, esperado)

    # Compatibilidad con contraseñas antiguas guardadas en texto plano.
    return hmac.compare_digest(password_ingresado, password_guardado)
