"""
REV-01 · Huella del contenido verificable de un recurso (REV-R1, REV-R2).

La huella cambia solo cuando cambia lo que la verificación contrasta con la evidencia: el cuerpo, las afirmaciones y
los fragmentos que citan, las alternativas (texto, clave correcta, retroalimentación y fragmentos) y los campos de la
estructura. Se conserva ante cambios de formato (`bodyHtml`), espacios equivalentes, metadatos de revisión, el título,
el texto alternativo de una imagen y el orden de las alternativas, que tienen identificadores estables.

Es una función de dominio compartida: Generación la usa al crear el recurso y Revisión al guardarlo. Contiene solo la
normalización y la huella; el umbral y los mínimos de verificación están en `domain/generation/grounding.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from platform5e.domain.generation.resource_formats import IMAGE, needs_structure, normalize_structure, resource_format

FINGERPRINT_PREFIX = "sha256:"
# Campos de la estructura que no se verifican: el texto alternativo de una imagen es de accesibilidad y no afirma nada.
UNVERIFIED_STRUCTURE_FIELDS: dict[str, frozenset[str]] = {IMAGE: frozenset({"alt"})}
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _text(value: Any) -> str:
    """Texto en Unicode NFC, con los espacios colapsados y sin espacios al inicio ni al final."""
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split())


def _paragraphs(value: Any) -> list[str]:
    """El cuerpo como lista de párrafos: la verificación por párrafos depende de dónde empieza cada uno."""
    if not isinstance(value, str):
        return []
    paragraphs = (_text(part) for part in _PARAGRAPH_BREAK.split(unicodedata.normalize("NFC", value)))
    return [paragraph for paragraph in paragraphs if paragraph]


def _fragment_ids(value: Any) -> list[str]:
    return sorted({fragment_id for fragment_id in value or [] if isinstance(fragment_id, str) and fragment_id})


def _deep_text(value: Any) -> Any:
    """Normaliza el texto de una estructura conservando el orden de sus listas."""
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return [_deep_text(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _deep_text(item) for key, item in value.items()}
    return value


def _citations(value: Any) -> list[dict[str, Any]]:
    citations = [
        {"claim": _text(citation.get("claim")), "fragmentIds": _fragment_ids(citation.get("fragmentIds"))}
        for citation in value or []
        if isinstance(citation, dict)
    ]
    return sorted(citations, key=lambda citation: (citation["claim"], citation["fragmentIds"]))


def _options(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    options = [
        {
            "id": str(option.get("id", "")),
            "text": _text(option.get("text")),
            "isCorrect": bool(option.get("isCorrect")),
            "feedback": _text(option.get("feedback")),
            "sourceFragmentIds": _fragment_ids(option.get("sourceFragmentIds")),
        }
        for option in value
        if isinstance(option, dict)
    ]
    return sorted(options, key=lambda option: option["id"])


def _structure(resource_type: str, value: Any) -> Any:
    if not needs_structure(resource_type) or value is None:
        return None
    # La misma limpieza que aplica la revisión al guardar. Si la estructura todavía no alcanza el mínimo del tipo,
    # se normaliza tal como llegó para que la huella siga siendo estable mientras el docente la completa.
    normalized = normalize_structure(resource_type, value)
    structure = _deep_text(normalized if normalized is not None else value)
    if isinstance(structure, dict):
        excluded = UNVERIFIED_STRUCTURE_FIELDS.get(resource_format(resource_type), frozenset())
        structure = {key: item for key, item in structure.items() if key not in excluded}
    return structure


def normalize_verifiable_content(resource: dict[str, Any]) -> dict[str, Any]:
    """Solo los campos verificables del recurso, normalizados para comparar versiones."""
    resource_type = str(resource.get("type") or "")
    return {
        "type": resource_type,
        "body": _paragraphs(resource.get("body")),
        "citations": _citations(resource.get("citations")),
        "options": _options(resource.get("options")),
        "structure": _structure(resource_type, resource.get("structure")),
    }


def content_fingerprint(resource: dict[str, Any]) -> str:
    """Huella `sha256:<hex>` del contenido verificable normalizado."""
    canonical = json.dumps(
        normalize_verifiable_content(resource), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return FINGERPRINT_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
