"""
Errores de los proveedores de IA: qué se guarda o se devuelve al docente y qué va solo al registro del servidor.

Revisión del PR #43 (seguridad): un error de Google puede traer «Consumer 'api_key:AIza…'» o datos del proyecto, y la
API devuelve `fallbackReason`, las notas de la multimedia y `embeddingError` a cualquier docente. Por eso lo que se
guarda o se devuelve es un motivo genérico (`public_reason`), y el detalle va solo al registro, con las claves ocultas
(`redact_secrets`).
"""

from __future__ import annotations

import re

REDACTED: str = "[clave oculta]"
# Claves de Google («AIza» y 35 caracteres) y cualquier «api_key:…» que traiga el mensaje del proveedor.
_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_-]{35}")
# El valor termina en un espacio, una comilla o un paréntesis (un mensaje recortado puede cerrar justo después).
_API_KEY_TOKEN = re.compile(r"(api_key:)(?!\[clave oculta\])[^\s'\"()]+", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """El texto con las claves de API ocultas. Se usa en todo mensaje de los adaptadores de IA que va al registro."""
    return _GOOGLE_KEY.sub(REDACTED, _API_KEY_TOKEN.sub(rf"\g<1>{REDACTED}", str(text)))


def public_reason(error: BaseException) -> str:
    """Motivo que se puede guardar y mostrar al docente. Los errores de los adaptadores de IA traen el suyo
    (`public_reason`, sin el texto del proveedor); de cualquier otro error solo se dice su tipo."""
    reason = getattr(error, "public_reason", None)
    if isinstance(reason, str) and reason:
        return redact_secrets(reason)
    return f"error del proveedor: {type(error).__name__}"


# «Gemini respondió 403: <mensaje de Google>» o «… respondió 403 en los embeddings: <mensaje>»: la redacción anterior
# guardaba el mensaje del proveedor después de los dos puntos, a veces recortado y sin cerrar el paréntesis.
_PROVIDER_MESSAGE = re.compile(r"(respondió \d{3}(?: en [^:()]{1,40})?):[^)]*")


def sanitize_stored_reason(text: str) -> str:
    """Un motivo ya guardado (nota de la multimedia, `embeddingError`), listo para devolverlo: con las claves ocultas
    y sin el mensaje del proveedor que sigue a «respondió NNN:». No cambia lo guardado: se aplica al leer."""
    return _PROVIDER_MESSAGE.sub(r"\1", redact_secrets(text))
