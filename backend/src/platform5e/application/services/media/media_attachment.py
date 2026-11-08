"""
Imagen o audio de un recurso: se genera con el puerto de medios y, si el servicio no responde, el recurso queda con su
respaldo (tarjeta con la descripción o voz del navegador). Lo usan la generación y «Generar de nuevo» en la revisión.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.media_port import MediaGeneratorPort, MediaRepositoryPort
from platform5e.domain.generation.resource_formats import AUDIO, IMAGE

logger = logging.getLogger("platform5e.media")

FALLBACK_NOTES = {
    IMAGE: "Sin imagen generada: se muestra la descripción de la ilustración.",
    AUDIO: "Sin audio generado: el guion se escucha con la voz del navegador.",
}
EDITED_NOTES = {
    IMAGE: "Cambiaste la descripción: la imagen anterior ya no se usa. Se muestra la descripción hasta que la generes de nuevo.",
    AUDIO: "Cambiaste el guion: el audio anterior ya no se usa. Se escucha con la voz del navegador hasta que lo generes de nuevo.",
}


def has_media(resource: dict[str, Any]) -> bool:
    return resource.get("format") in (IMAGE, AUDIO)


def fallback_media(kind: str, note: str | None = None) -> dict[str, Any]:
    return {"status": "fallback", "note": note or FALLBACK_NOTES[kind]}


def attach_generated_media(
    teacher_id: str,
    resource: dict[str, Any],
    generator: MediaGeneratorPort | None,
    repository: MediaRepositoryPort | None,
) -> bool:
    """Deja en `resource["media"]` el archivo generado o el respaldo. Devuelve True si se generó el archivo."""
    kind = resource.get("format")
    if kind not in (IMAGE, AUDIO):
        return False
    resource["media"] = fallback_media(kind)
    if generator is None or repository is None:
        return False
    structure = resource.get("structure") or {}
    try:
        generated = (
            generator.generate_image(structure["prompt"]) if kind == IMAGE else generator.synthesize_speech(structure["script"])
        )
    except Exception as exc:  # el recurso se conserva con su respaldo
        logger.warning("Medio no generado para %s: %s", resource.get("id"), str(exc)[:200])
        resource["media"]["note"] += f" ({str(exc)[:120]})"
        return False
    media = {
        "id": f"media-{uuid4()}",
        "resourceId": resource["id"],
        "status": "ready",
        "mimeType": generated.mime_type,
        "fileName": f"{resource['id']}.{generated.extension}",
        "sizeBytes": len(generated.content),
        "generator": generator.description,
    }
    repository.save_media(teacher_id, media, generated.content)
    resource["media"] = media
    return True
