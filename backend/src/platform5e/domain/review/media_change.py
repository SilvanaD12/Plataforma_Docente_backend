"""
REV-01 · ¿Cambió el texto con que se generó el archivo multimedia? (REV-R8 · REV-C8).

Un archivo de imagen se generó con su `prompt` y uno de audio con su `script`. Solo un cambio de ese campo,
normalizado con `normalize_structure`, deja el archivo sin uso. Cambiar el texto alternativo (`alt`) o el pie
(`caption`) de una imagen no lo invalida.
"""

from __future__ import annotations

from typing import Any

from platform5e.domain.generation.resource_formats import AUDIO, IMAGE, normalize_structure, resource_format

# Formato del recurso -> campo de la estructura con que se generó el archivo.
SOURCE_FIELDS: dict[str, str] = {IMAGE: "prompt", AUDIO: "script"}


def _source_text(resource_type: str, structure: Any) -> str:
    field = SOURCE_FIELDS[resource_format(resource_type)]
    normalized = normalize_structure(resource_type, structure)
    if normalized is not None:
        return str(normalized.get(field) or "")
    raw = (structure or {}).get(field) if isinstance(structure, dict) else None
    return " ".join(raw.split()) if isinstance(raw, str) else ""


def media_source_changed(resource_type: str, old_structure: Any, new_structure: Any) -> bool:
    """True si cambió el `prompt` (imagen) o el `script` (audio) normalizado. False para otros tipos de recurso."""
    if resource_format(resource_type) not in SOURCE_FIELDS:
        return False
    return _source_text(resource_type, old_structure) != _source_text(resource_type, new_structure)
