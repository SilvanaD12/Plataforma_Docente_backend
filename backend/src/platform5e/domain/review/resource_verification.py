"""
REV-01 · Verificación local de un recurso contra su copia histórica (REV-R3, R4, R5, R6).

Aplica a la copia de evidencia guardada en el recurso (`evidence`) las mismas reglas que usa Generación en
`domain/generation/grounding.py`: afirmaciones citadas, párrafos de la explicación y del glosario, y elementos de las
actividades (pasos, predicciones y criterios). No consulta el índice del material ni servicios externos, así que
reprocesar el material no cambia el resultado (REV-C6).

El resultado queda ligado a la huella del contenido verificado (`content_fingerprint`): un resultado de otra versión
del contenido no habilita la aprobación (REV-C5).

Estados:
- `current` (vigente): el material respalda el contenido.
- `insufficient` (insuficiente): la regla no alcanza el mínimo; el docente corrige el texto o regenera el recurso.
- `pending` (pendiente): la comprobación no se pudo completar. Si la copia está completa se puede reintentar; si falta
  la copia o el texto de algún fragmento que el recurso referencia, solo queda regenerarlo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from platform5e.domain.generation.distractor_reliability import assess_distractor
from platform5e.domain.generation.grounding import (
    DEFAULT_THRESHOLD,
    link_criterion_sources,
    link_prediction_sources,
    link_step_sources,
    verify_citations,
    verify_statements,
)
from platform5e.domain.generation.resource_formats import MIN_ITEMS
from platform5e.domain.review.content_fingerprint import content_fingerprint

CURRENT = "current"
INSUFFICIENT = "insufficient"
PENDING = "pending"

# Tipo de actividad -> (lista de la estructura, función que enlaza cada elemento con su fragmento, nombre en singular
# y en plural para el motivo).
LINKED_ITEMS: dict[str, tuple[str, Any, str, str]] = {
    "exploracion_guiada": ("guidedSteps", link_step_sources, "paso", "pasos"),
    "reto_prediccion": ("predictions", link_prediction_sources, "predicción", "predicciones"),
    "caso_aplicado": ("criteria", link_criterion_sources, "criterio de logro", "criterios de logro"),
}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def stored_threshold(resource: dict[str, Any]) -> float:
    """El umbral registrado para el recurso: el de su verificación, el de la generación, el del pedido o el general."""
    for container, key in (("verification", "evidenceThreshold"), ("grounding", "threshold"), ("params", "evidenceThreshold")):
        value = _number((resource.get(container) or {}).get(key))
        if value is not None:
            return value
    return DEFAULT_THRESHOLD


def _structure_fragment_ids(value: Any) -> list[str]:
    """Los `fragmentIds` de los elementos de una estructura (pasos, predicciones, criterios…)."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "fragmentIds" and isinstance(item, list):
                found += [f for f in item if isinstance(f, str) and f]
            else:
                found += _structure_fragment_ids(item)
    elif isinstance(value, list):
        for item in value:
            found += _structure_fragment_ids(item)
    return found


def referenced_fragment_ids(resource: dict[str, Any]) -> list[str]:
    """Las fuentes vinculadas del recurso: los fragmentos que citan sus afirmaciones, alternativas y estructura."""
    ids = [f for citation in resource.get("citations") or [] for f in citation.get("fragmentIds") or []]
    ids += [f for option in resource.get("options") or [] for f in option.get("sourceFragmentIds") or []]
    ids += _structure_fragment_ids(resource.get("structure"))
    return list(dict.fromkeys(f for f in ids if isinstance(f, str) and f))


def _evidence_texts(resource: dict[str, Any]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for fragment in resource.get("evidence") or []:
        if isinstance(fragment, dict) and isinstance(fragment.get("id"), str):
            text = fragment.get("text")
            texts[fragment["id"]] = text.strip() if isinstance(text, str) else ""
    return texts


def incomplete_copy_reason(resource: dict[str, Any]) -> str | None:
    """Motivo por el que la copia histórica no alcanza para verificar, o None si está completa (REV-R6)."""
    texts = _evidence_texts(resource)
    if not texts:
        return "El recurso no tiene copia histórica de sus fuentes: regenera el recurso para verificarlo."
    missing = [fragment_id for fragment_id in referenced_fragment_ids(resource) if not texts.get(fragment_id)]
    if missing:
        return (
            f"Falta en la copia histórica el texto del fragmento {missing[0]}"
            + (f" y de {len(missing) - 1} más" if len(missing) > 1 else "")
            + ": regenera el recurso para verificarlo."
        )
    return None


def _check(resource: dict[str, Any], fragments: dict[str, str], threshold: float) -> tuple[str, str | None, dict[str, Any]]:
    """Aplica las reglas de `grounding.py` y devuelve el estado, el motivo y el resumen de lo verificado."""
    title = str(resource.get("title") or "El recurso")
    citations = [c for c in resource.get("citations") or [] if isinstance(c, dict) and c.get("claim")]
    grounding = verify_citations(citations, fragments, threshold)
    summary = grounding.summary()
    if not grounding.accepted:
        return INSUFFICIENT, grounding.rejection_reason(title), summary

    resource_type = str(resource.get("type") or "")
    statements = verify_statements(str(resource.get("body") or ""), resource_type, fragments, threshold)
    if statements is not None:
        summary.update(statements.summary())
        if not statements.accepted:
            return INSUFFICIENT, statements.rejection_reason(title), summary

    if resource_type in LINKED_ITEMS:
        key, link, singular, plural = LINKED_ITEMS[resource_type]
        items = [item for item in ((resource.get("structure") or {}).get(key) or []) if isinstance(item, dict)]
        linked = link(items, fragments)
        summary.update(linked.summary())
        minimum = MIN_ITEMS.get(resource_type, 1)
        if len(linked.items) < minimum:
            return (
                INSUFFICIENT,
                f"«{title}»: solo {len(linked.items)} {singular if len(linked.items) == 1 else plural} se apoyan en el "
                f"material; se necesitan al menos {minimum} {plural}.",
                summary,
            )
    return CURRENT, None, summary


def verify_resource(
    resource: dict[str, Any],
    threshold: float,
    rule_version: int,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verifica el contenido actual del recurso contra su copia histórica. No modifica el recurso.

    `previous` es el resultado guardado antes de la edición: si se obtuvo con otra versión de la regla y el estado
    cambia, el motivo lo indica (REV-C10).
    """
    status, reason, summary, retry_available = PENDING, incomplete_copy_reason(resource), {}, False
    if reason is None:
        try:
            status, reason, summary = _check(resource, _evidence_texts(resource), threshold)
        except Exception as error:  # la comprobación no se completó: se puede reintentar con la misma copia
            status, summary, retry_available = PENDING, {}, True
            reason = f"La comprobación no pudo completarse ({type(error).__name__}). Reintenta la comprobación."
    if isinstance(previous, dict):
        previous_rule = previous.get("ruleVersion")
        if previous_rule is not None and previous_rule != rule_version and previous.get("status") != status:
            note = f"La regla de verificación cambió (v{previous_rule} → v{rule_version})."
            reason = f"{reason} {note}" if reason else note
    return {
        "status": status,
        "reason": reason,
        "fingerprint": content_fingerprint(resource),
        "verifiedVersion": resource.get("version", 1),
        "evidenceThreshold": threshold,
        "ruleVersion": rule_version,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "retryAvailable": retry_available,
        "summary": summary,
    }


def assess_edited_distractors(resource: dict[str, Any], edited_option_ids: set[str]) -> dict[str, str | None]:
    """REV-C4: aviso de fiabilidad de cada distractor editado (None si la evidencia no lo muestra como correcto)."""
    options = [o for o in resource.get("options") or [] if isinstance(o, dict)]
    key = next((o for o in options if o.get("isCorrect")), None)
    if key is None:
        return {}
    fragments = _evidence_texts(resource)
    warnings: dict[str, str | None] = {}
    for option in options:
        if option.get("isCorrect") or option.get("id") not in edited_option_ids:
            continue
        issue = assess_distractor(str(resource.get("body") or ""), str(key.get("text") or ""), str(option.get("text") or ""), fragments)
        warnings[option["id"]] = issue.reason if issue else None
    return warnings
