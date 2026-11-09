"""
Imagen o audio de un recurso: se genera con el puerto de medios y, si el servicio no responde, el recurso queda con su
respaldo (tarjeta con la descripción o voz del navegador). Lo usan la generación y «Generar de nuevo» en la revisión.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PendingMedia:
    """Archivo ya generado que todavía no se guardó: `media` es su descripción (la que queda en el recurso)."""

    media: dict[str, Any]
    content: bytes


def generate_media(resource: dict[str, Any], generator: MediaGeneratorPort | None) -> PendingMedia | None:
    """Genera la imagen o el audio del recurso sin guardarlo. Deja en `resource["media"]` la descripción del archivo o
    el respaldo, y devuelve el archivo pendiente de guardar (None si no hay archivo)."""
    kind = resource.get("format")
    if kind not in (IMAGE, AUDIO):
        return None
    resource["media"] = fallback_media(kind)
    if generator is None:
        return None
    structure = resource.get("structure") or {}
    try:
        generated = (
            generator.generate_image(structure["prompt"]) if kind == IMAGE else generator.synthesize_speech(structure["script"])
        )
    except Exception as exc:  # el recurso se conserva con su respaldo
        logger.warning("Medio no generado para %s: %s", resource.get("id"), str(exc)[:200])
        resource["media"]["note"] += f" ({str(exc)[:120]})"
        return None
    media = {
        "id": f"media-{uuid4()}",
        "resourceId": resource["id"],
        "status": "ready",
        "mimeType": generated.mime_type,
        "fileName": f"{resource['id']}.{generated.extension}",
        "sizeBytes": len(generated.content),
        "generator": generator.description,
    }
    resource["media"] = media
    return PendingMedia(media=media, content=generated.content)


def attach_generated_media(
    teacher_id: str,
    resource: dict[str, Any],
    generator: MediaGeneratorPort | None,
    repository: MediaRepositoryPort | None,
) -> bool:
    """Deja en `resource["media"]` el archivo generado o el respaldo. Devuelve True si se generó el archivo."""
    pending = generate_media(resource, generator if repository is not None else None)
    if pending is None or repository is None:
        return False
    repository.save_media(teacher_id, pending.media, pending.content)
    return True
