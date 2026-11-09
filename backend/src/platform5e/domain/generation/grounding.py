"""
Verificación de anclaje (HU-016): cada afirmación que cita el material se contrasta con la evidencia recuperada, y lo
que no tiene respaldo se rechaza con su motivo. Alimenta el indicador I21 (tasa de alucinación).

El respaldo de una afirmación es la proporción de sus palabras útiles (sin vacías, con su raíz) que aparecen en los
fragmentos que cita. Dos palabras coinciden si tienen la misma raíz o comparten sus seis primeras letras
(«confirma» y «confirmación», pero no «confirma» y «confiable»). Es una regla por palabras y explicable: no entiende
sinónimos, y la búsqueda por significado (EN-013) podrá reforzarla.

HU-049: en la explicación y el glosario también se contrasta el contenido, párrafo por párrafo o entrada por entrada
(`verify_statements`), y cada párrafo queda enlazado con los fragmentos que lo respaldan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from platform5e.domain.materials.text_analysis import extract_terms

DEFAULT_THRESHOLD: float = 0.6
# REV-01: versión de la regla de verificación que se guarda con cada resultado. Se incrementa en 1 cuando cambia algún
# umbral o mínimo de este archivo (afirmaciones, párrafos, pasos, predicciones o criterios). Un recurso que no se edita
# conserva su resultado aunque cambie la versión; al editarlo se verifica con la regla vigente.
VERIFICATION_RULE_VERSION: int = 1
SHARED_PREFIX: int = 6
# Un recurso se rechaza si menos de esta proporción de sus afirmaciones tiene respaldo.
MIN_SUPPORTED_SHARE: float = 0.5
# Una afirmación con menos palabras útiles no se puede contrastar: se rechaza.
MIN_CLAIM_TERMS: int = 2


def _matches(term: str, evidence_terms: set[str], evidence_prefixes: set[str]) -> bool:
    return term in evidence_terms or (len(term) >= SHARED_PREFIX and term[:SHARED_PREFIX] in evidence_prefixes)


def terms_support(terms: set[str], evidence_texts: list[str]) -> float:
    """Proporción (0 a 1) de los términos (ya extraídos con `extract_terms`) que aparecen en los textos de evidencia."""
    if not terms:
        return 0.0
    evidence_terms = {term for text in evidence_texts for term in extract_terms(text)}
    evidence_prefixes = {term[:SHARED_PREFIX] for term in evidence_terms if len(term) >= SHARED_PREFIX}
    found = sum(1 for term in terms if _matches(term, evidence_terms, evidence_prefixes))
    return found / len(terms)


def claim_support(claim: str, evidence_texts: list[str]) -> float:
    """Proporción (0 a 1) de las palabras útiles de la afirmación que aparecen en los textos de evidencia."""
    return terms_support(set(extract_terms(claim)), evidence_texts)


@dataclass
class ClaimCheck:
    """Resultado de contrastar una afirmación con la evidencia."""

    claim: str
    fragment_ids: list[str]
    support: float
    supported: bool
    reason: str | None = None
    corrected: bool = False  # la respaldaba otro fragmento recuperado, no el que citó

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"claim": self.claim, "support": round(self.support, 2), "supported": self.supported}
        if self.reason:
            data["reason"] = self.reason
        if self.corrected:
            data["corrected"] = True
        return data


@dataclass
class GroundingResult:
    """Verificación de todas las afirmaciones de un recurso."""

    checks: list[ClaimCheck] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD

    @property
    def supported(self) -> list[ClaimCheck]:
        return [check for check in self.checks if check.supported]

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [check for check in self.checks if not check.supported]

    @property
    def accepted(self) -> bool:
        """El recurso se conserva si tiene afirmaciones respaldadas y son al menos la mitad."""
        return bool(self.supported) and len(self.supported) / len(self.checks) >= MIN_SUPPORTED_SHARE

    def rejection_reason(self, title: str) -> str:
        if not self.checks:
            return f"«{title}» no cita ninguna afirmación del material."
        return (
            f"«{title}»: {len(self.unsupported)} de {len(self.checks)} afirmaciones sin respaldo en el material "
            f"(p. ej. «{_short(self.unsupported[0].claim)}»)."
        )

    def summary(self) -> dict[str, Any]:
        """Lo que se guarda en el recurso para la revisión y para calcular I21."""
        return {
            "threshold": self.threshold,
            "checkedClaims": len(self.checks),
            "supportedClaims": len(self.supported),
            "correctedClaims": sum(1 for check in self.supported if check.corrected),
            "removedClaims": [check.as_dict() for check in self.unsupported],
        }


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def check_claim(
    claim: str,
    cited_ids: list[str],
    fragments_by_id: dict[str, str],
    threshold: float = DEFAULT_THRESHOLD,
) -> ClaimCheck:
    """Contrasta una afirmación con los fragmentos que cita y, si no la respaldan, con el resto de lo recuperado."""
    if len(set(extract_terms(claim))) < MIN_CLAIM_TERMS:
        return ClaimCheck(claim, cited_ids, 0.0, False, "La afirmación es demasiado breve para contrastarla.")

    support = claim_support(claim, [fragments_by_id[f_id] for f_id in cited_ids if f_id in fragments_by_id])
    if support >= threshold:
        return ClaimCheck(claim, cited_ids, support, True)

    # El modelo pudo citar la etiqueta equivocada: se busca el fragmento recuperado que mejor la respalda.
    best_id, best_support = None, support
    for fragment_id, text in fragments_by_id.items():
        candidate = claim_support(claim, [text])
        if candidate > best_support:
            best_id, best_support = fragment_id, candidate
    if best_id is not None and best_support >= threshold:
        return ClaimCheck(claim, [best_id], best_support, True, corrected=True)

    return ClaimCheck(
        claim,
        cited_ids,
        support,
        False,
        f"Solo el {round(support * 100)} % de sus palabras aparece en los fragmentos citados "
        f"(mínimo {round(threshold * 100)} %).",
    )


def verify_citations(
    citations: list[dict[str, Any]],
    fragments_by_id: dict[str, str],
    threshold: float = DEFAULT_THRESHOLD,
) -> GroundingResult:
    """Verifica cada cita `{"claim", "fragmentIds"}` de un recurso contra la evidencia recuperada."""
    result = GroundingResult(threshold=threshold)
    for citation in citations:
        result.checks.append(
            check_claim(citation["claim"], list(citation["fragmentIds"]), fragments_by_id, threshold)
        )
    return result


def hallucination_rate(checked: int, unsupported: int) -> float | None:
    """I21: afirmaciones sin respaldo / afirmaciones verificadas (None si no se verificó ninguna)."""
    return round(unsupported / checked, 4) if checked else None


# --- HU-049 C02: el texto de la explicación también se contrasta con el material ---------------------------------
#
# La verificación de arriba revisa las citas que el modelo declara, pero no el contenido: un párrafo de la explicación
# podía no corresponder a ninguna cita. Para la explicación y el glosario, cada párrafo (o entrada del glosario) se
# contrasta con los fragmentos recuperados y se enlaza con los que lo respaldan.

# Tipos cuyo contenido se verifica párrafo por párrafo y cómo se separa cada uno.
STATEMENT_CHECKED_TYPES: dict[str, str] = {"explicacion": "paragraph", "glosario": "line"}
# Un párrafo usa palabras de enlace propias de la explicación («por eso», «es decir»…): se le exige este margen menos
# que a una afirmación citada.
PARAGRAPH_MARGIN: float = 0.1
# Un párrafo con menos palabras útiles es un subtítulo o una transición: no se contrasta y se conserva.
MIN_STATEMENT_TERMS: int = 4
# Un párrafo puede resumir dos fragmentos: se contrasta con los dos que más lo respaldan.
MAX_STATEMENT_SOURCES: int = 2


def split_statements(body: str, mode: str) -> list[str]:
    """Separa el contenido en párrafos (líneas en blanco) o en entradas (una por línea, como el glosario)."""
    if mode == "line" or "\n\n" not in body:
        parts = body.split("\n")
    else:
        parts = body.split("\n\n")
    return [part.strip() for part in parts if part.strip()]


@dataclass
class StatementCheck:
    """Resultado de contrastar un párrafo del contenido con los fragmentos recuperados."""

    text: str
    fragment_ids: list[str]
    support: float
    supported: bool
    checked: bool = True
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"text": self.text, "support": round(self.support, 2), "supported": self.supported}
        if self.reason:
            data["reason"] = self.reason
        return data


def check_statement(statement: str, fragments_by_id: dict[str, str], threshold: float) -> StatementCheck:
    """Busca los fragmentos recuperados que mejor respaldan el párrafo y mide su respaldo conjunto."""
    terms = set(extract_terms(statement))
    if len(terms) < MIN_STATEMENT_TERMS:
        return StatementCheck(statement, [], 1.0, True, checked=False)

    ranked = sorted(
        ((terms_support(terms, [text]), fragment_id) for fragment_id, text in fragments_by_id.items()),
        key=lambda pair: -pair[0],
    )
    sources: list[str] = []
    support = 0.0
    # Se agrega el siguiente fragmento solo si aporta palabras que el anterior no tenía.
    for _, fragment_id in ranked[:MAX_STATEMENT_SOURCES]:
        candidate = terms_support(terms, [fragments_by_id[f_id] for f_id in [*sources, fragment_id]])
        if candidate > support:
            sources.append(fragment_id)
            support = candidate
    if support >= threshold:
        return StatementCheck(statement, sources, support, True)
    return StatementCheck(
        statement,
        sources,
        support,
        False,
        reason=(
            f"Solo el {round(support * 100)} % de sus palabras aparece en el material "
            f"(mínimo {round(threshold * 100)} %)."
        ),
    )


@dataclass
class StatementsResult:
    """Verificación del contenido de un recurso, párrafo por párrafo."""

    checks: list[StatementCheck] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD - PARAGRAPH_MARGIN
    separator: str = "\n\n"

    @property
    def checked(self) -> list[StatementCheck]:
        return [check for check in self.checks if check.checked]

    @property
    def unsupported(self) -> list[StatementCheck]:
        return [check for check in self.checks if not check.supported]

    @property
    def accepted(self) -> bool:
        """Se conserva si no hay párrafos que contrastar o si al menos la mitad tiene respaldo."""
        checked = self.checked
        if not checked:
            return True
        supported = sum(1 for check in checked if check.supported)
        return supported / len(checked) >= MIN_SUPPORTED_SHARE

    def kept_body(self) -> str:
        """El contenido sin los párrafos que no tienen respaldo."""
        return self.separator.join(check.text for check in self.checks if check.supported)

    def rejection_reason(self, title: str) -> str:
        first = self.unsupported[0].text if self.unsupported else ""
        return (
            f"«{title}»: {len(self.unsupported)} de {len(self.checked)} párrafos sin respaldo en el material "
            f"(p. ej. «{_short(first)}»)."
        )

    def summary(self) -> dict[str, Any]:
        """Lo que se guarda en el recurso: cuántos párrafos se contrastaron y de qué fragmentos sale cada uno."""
        return {
            "paragraphThreshold": round(self.threshold, 2),
            "checkedParagraphs": len(self.checked),
            "supportedParagraphs": sum(1 for check in self.checked if check.supported),
            "paragraphSources": [check.fragment_ids for check in self.checks if check.supported],
            "removedParagraphs": [check.as_dict() for check in self.unsupported],
        }


def verify_statements(
    body: str,
    resource_type: str,
    fragments_by_id: dict[str, str],
    threshold: float = DEFAULT_THRESHOLD,
) -> StatementsResult | None:
    """Contrasta cada párrafo del contenido con la evidencia. None si el tipo de recurso no se verifica así."""
    mode = STATEMENT_CHECKED_TYPES.get(resource_type)
    if mode is None:
        return None
    paragraph_threshold = max(threshold - PARAGRAPH_MARGIN, 0.0)
    statements = split_statements(body, mode)
    return StatementsResult(
        checks=[check_statement(statement, fragments_by_id, paragraph_threshold) for statement in statements],
        threshold=paragraph_threshold,
        separator="\n" if mode == "line" or "\n\n" not in body else "\n\n",
    )


# --- HU-048, HU-047 y HU-050: cada elemento de una actividad cita su fragmento -------------------------------------
#
# HU-048: un paso de la exploración guiada mezcla el contenido del material con verbos de consigna («observa»,
# «compara», «anota») y la forma de una pregunta, así que se le exige menos que a una afirmación: al menos el 30 % de
# sus palabras útiles en el fragmento.
#
# HU-047: en el reto de predicción se contrasta lo que el estudiante descubre (la opción correcta y lo que dice el
# material), no la pregunta ni las opciones equivocadas, que a propósito no están en el material. Como es una
# afirmación redactada por el modelo, con palabras de enlace propias, se le pide lo mismo que a un párrafo (ADR-016):
# al menos el 50 %.

STEP_MIN_SUPPORT: float = 0.3
PREDICTION_MIN_SUPPORT: float = 0.5
# HU-050: un criterio de logro mezcla el concepto que aplica con verbos de desempeño («justifica», «propone»), como un
# paso de la exploración guiada, así que se le pide lo mismo: 30 %. La situación y la consigna no se contrastan,
# porque a propósito plantean un contexto que no está en el material.
CRITERION_MIN_SUPPORT: float = 0.3


# Plurales que no se forman agregando «s» (para las llaves del resumen).
IRREGULAR_PLURALS: dict[str, str] = {"criterion": "Criteria"}


@dataclass
class LinkedSourcesResult:
    """Los elementos que quedaron enlazados a su fragmento y los que se quitaron por no apoyarse en el material.

    `noun` da nombre a las llaves del resumen: «step» → `stepThreshold`, `checkedSteps`…; «prediction» →
    `predictionThreshold`, `checkedPredictions`…
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    corrected: int = 0
    threshold: float = STEP_MIN_SUPPORT
    noun: str = "step"

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.items

    @property
    def predictions(self) -> list[dict[str, Any]]:
        return self.items

    @property
    def criteria(self) -> list[dict[str, Any]]:
        return self.items

    def summary(self) -> dict[str, Any]:
        plural = IRREGULAR_PLURALS.get(self.noun) or self.noun[:1].upper() + self.noun[1:] + "s"
        return {
            f"{self.noun}Threshold": self.threshold,
            f"checked{plural}": len(self.items) + len(self.removed),
            f"supported{plural}": len(self.items),
            f"corrected{plural}": self.corrected,
            f"removed{plural}": self.removed,
        }


# Nombre anterior, usado por HU-048.
StepSourcesResult = LinkedSourcesResult


def _link_sources(
    items: list[dict[str, Any]],
    fragments_by_id: dict[str, str],
    threshold: float,
    text_keys: tuple[str, ...],
    label_key: str,
    noun: str,
) -> LinkedSourcesResult:
    """Contrasta cada elemento con el fragmento que cita. Si la cita no lo respalda, lo enlaza con el fragmento
    recuperado que más lo respalda; si ninguno llega al mínimo, el elemento se quita con su motivo."""
    result = LinkedSourcesResult(threshold=threshold, noun=noun)
    for item in items:
        text = " ".join(str(item.get(key, "")) for key in text_keys)
        terms = set(extract_terms(text))
        cited = [f_id for f_id in item.get("fragmentIds") or [] if f_id in fragments_by_id]
        support = terms_support(terms, [fragments_by_id[f_id] for f_id in cited]) if cited else 0.0
        if cited and support >= threshold:
            result.items.append({**item, "fragmentIds": cited})
            continue
        best_id, best_support = None, support
        for fragment_id, fragment_text in fragments_by_id.items():
            candidate = terms_support(terms, [fragment_text])
            if candidate > best_support:
                best_id, best_support = fragment_id, candidate
        if best_id is not None and best_support >= threshold:
            result.items.append({**item, "fragmentIds": [best_id]})
            result.corrected += 1
            continue
        result.removed.append(
            {
                label_key: item.get(label_key, ""),
                "support": round(max(support, best_support), 2),
                "reason": (
                    f"Solo el {round(max(support, best_support) * 100)} % de sus palabras aparece en el material "
                    f"(mínimo {round(threshold * 100)} %)."
                ),
            }
        )
    return result


def link_step_sources(
    steps: list[dict[str, Any]],
    fragments_by_id: dict[str, str],
    threshold: float = STEP_MIN_SUPPORT,
) -> LinkedSourcesResult:
    """HU-048: enlaza cada paso de la exploración guiada con el fragmento que lo respalda."""
    return _link_sources(steps, fragments_by_id, threshold, ("title", "instruction", "question"), "title", "step")


def link_prediction_sources(
    predictions: list[dict[str, Any]],
    fragments_by_id: dict[str, str],
    threshold: float = PREDICTION_MIN_SUPPORT,
) -> LinkedSourcesResult:
    """HU-047: enlaza cada predicción con el fragmento que respalda su respuesta (la opción correcta y lo que dice el
    material). Una predicción cuya respuesta no está en el material se quita."""
    return _link_sources(
        predictions, fragments_by_id, threshold, ("correctOption", "reveal"), "question", "prediction"
    )


def link_criterion_sources(
    criteria: list[dict[str, Any]],
    fragments_by_id: dict[str, str],
    threshold: float = CRITERION_MIN_SUPPORT,
) -> LinkedSourcesResult:
    """HU-050: enlaza cada criterio de logro del caso aplicado con el fragmento que tiene el concepto que aplica. Un
    criterio que no se apoya en el material se quita."""
    return _link_sources(criteria, fragments_by_id, threshold, ("criterion",), "criterion", "criterion")
