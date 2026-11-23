"""
GEN-P1 (T006, T007): cómo se arma el plan (specs/006-plan-de-generacion/research.md R4).

- `RuleBasedPlanner`: determinista y sin IA. Toma los conceptos candidatos del tema y del material, los reparte por
  turnos entre los bloques de los ítems (un bloque por recurso) y le da a cada ítem los fragmentos donde aparecen sus
  conceptos. Las mismas entradas y la misma evidencia dan el mismo plan.
- Con Gemini, una sola llamada (`PlanDrafterPort.draft_plan`) con esquema de respuesta propio y el tiempo límite de
  QA-06. Si la llamada falla, vence o el plan no es válido, `GenerationPlanner` lo arma con reglas y guarda el motivo
  público en `fallbackReason`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from platform5e.application.ports.outbound.plan_drafter_port import PlanDrafterPort, PlanPrompt
from platform5e.application.ports.outbound.resource_catalog_port import CatalogEntry
from platform5e.application.services.generation.prompt_drafting import PHASES_5E
from platform5e.application.services.provider_errors import public_reason, redact_secrets
from platform5e.domain.generation.generation_plan import (
    MAX_CONCEPT_CHARS,
    MAX_ITEM_QUANTITY,
    MAX_PURPOSE_CHARS,
    MIN_ITEM_QUANTITY,
    PlanEvidence,
    PlanInputs,
    PlanItem,
    Referent,
    SessionContext,
    order_items,
)
from platform5e.domain.generation.plan_validation import validate_items
from platform5e.domain.generation.topic_coverage import (
    assess_topic_coverage,
    concept_key,
    normalize,
    topic_phrases,
    topic_terms,
)
from platform5e.domain.materials.text_analysis import extract_key_terms

logger = logging.getLogger("platform5e.generation")

RULES_PLANNER_DESCRIPTION: str = "Planificador por reglas (sin IA)"
MAX_CANDIDATES: int = 40
MAX_CONCEPTS_PER_BLOCK: int = 4
MAX_ITEM_FRAGMENTS: int = 12
AUTO_QUANTITY_MAX: int = 3
_TOKEN = re.compile(r"[a-z0-9ñ]+")
MIN_KEY_TERM_CHARS: int = 6
# Palabras frecuentes en cualquier texto que no nombran un concepto del tema.
_GENERIC_WORDS = frozenset(
    """
    conjunto debido diferente diferentes general generales manera mediante mismo mismos parte partes primer primera
    segundo segunda siguiente siguientes través ultimo ultima cualquier ejemplo forma formas final finales tambien
    """.split()
)
# Formas verbales y modales: «debe recordarse» o «poder alcanzar» no nombran un concepto (heurística léxica).
_VERB_WORDS = frozenset(
    """
    debe deben debera deberan puede pueden podra podran tiene tienen tendra tendran hace hacen hara haran siempre
    nunca capaz capaces permite permiten existe existen
    """.split()
)
_VERB_ENDING = re.compile(r"(ar|er|ir|rse|ra|ran|ria|rian|aba|aban|ian)$")


def _is_concept_phrase(first: str, second: str) -> bool:
    words = (first, second)
    return not any(word in _GENERIC_WORDS or word in _VERB_WORDS or _VERB_ENDING.search(word) for word in words)


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(normalize(text)))


def _variants(word: str) -> set[str]:
    """La palabra y su singular o plural regular, como en QA-05."""
    variants = {word, word + "s", word + "es"}
    if word.endswith("es") and len(word) > 4:
        variants.add(word[:-2])
    if word.endswith("s") and len(word) > 3:
        variants.add(word[:-1])
    return variants


def _appears(concept: str, tokens: set[str]) -> bool:
    words = concept_key(concept).split()
    return bool(words) and all(_variants(word) & tokens for word in words)


def _stage_name(stage: str) -> str:
    return PHASES_5E.get(stage, (stage, ""))[0]


class RuleBasedPlanner:
    """Planificador determinista (research R4)."""

    def __init__(self, catalog: Mapping[str, CatalogEntry]) -> None:
        self._catalog = catalog

    def draft(self, inputs: PlanInputs, evidence: PlanEvidence) -> tuple[PlanItem, ...]:
        token_sets = [_tokens(fragment.text) for fragment in evidence.fragments]
        candidates = self._candidates(inputs.instructions, [f.text for f in evidence.fragments], token_sets)
        requested = sorted(
            inputs.resource_types,
            key=lambda r: list(PHASES_5E).index(self._stage(r.type)) if self._stage(r.type) in PHASES_5E else 99,
        )
        quantities = self._quantities([r.quantity for r in requested], len(candidates))
        block_owner = [index for index, quantity in enumerate(quantities) for _ in range(quantity)]
        blocks: list[list[str]] = [[] for _ in block_owner]
        if block_owner:
            usable = candidates[: len(block_owner) * MAX_CONCEPTS_PER_BLOCK]
            for number, concept in enumerate(usable):
                blocks[number % len(blocks)].append(concept)

        items = []
        for index, wanted in enumerate(requested):
            covers = [concept for block, owner in zip(blocks, block_owner) if owner == index for concept in block]
            fragment_ids = [
                fragment.id
                for fragment, tokens in zip(evidence.fragments, token_sets)
                if any(_appears(concept, tokens) for concept in covers)
            ][:MAX_ITEM_FRAGMENTS]
            entry = self._catalog.get(wanted.type)
            items.append(PlanItem(
                position=index + 1,
                stage=self._stage(wanted.type),
                resource_type=wanted.type,
                quantity=quantities[index],
                purpose=self._purpose(entry.name if entry else wanted.type, covers),
                covers=tuple(covers),
                fragment_ids=tuple(fragment_ids),
            ))
        return order_items(items)

    def _stage(self, resource_type: str) -> str:
        entry = self._catalog.get(resource_type)
        return entry.stage if entry else "explain"

    @staticmethod
    def _candidates(instructions: str, texts: list[str], token_sets: list[set[str]]) -> list[str]:
        """Conceptos candidatos que aparecen en la evidencia: primero las frases y los términos del tema, después los
        términos clave del material; cada grupo por el primer fragmento donde aparece, las frases antes que las
        palabras sueltas y, en empate, alfabético."""

        def first_index(concept: str) -> int | None:
            return next((i for i, tokens in enumerate(token_sets) if _appears(concept, tokens)), None)

        coverage = assess_topic_coverage(instructions, texts)
        labels = dict(coverage.labels)
        phrases = [phrase.text for phrase in topic_phrases(instructions)]
        topic = phrases + [labels.get(term, term) for term in coverage.found]
        # Frases del material (dos términos seguidos o unidos por «de»), de la más frecuente a la menos; después, los
        # términos clave que nombran algo del tema (sin palabras vacías, de estilo, de formulación ni genéricas).
        counts: dict[str, int] = {}
        for text in texts:
            for phrase in topic_phrases(text):
                if _is_concept_phrase(phrase.first, phrase.second):
                    counts[phrase.text.lower()] = counts.get(phrase.text.lower(), 0) + 1
        by_frequency = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        material_phrases = [text for text, count in by_frequency if count > 1]
        rare_phrases = [text for text, count in by_frequency if count == 1]  # último recurso, con poco material
        key_terms = [
            term.lower() for term in extract_key_terms(texts, count=MAX_CANDIDATES)
            if len(normalize(term)) >= MIN_KEY_TERM_CHARS and normalize(term) not in _GENERIC_WORDS
            and topic_terms(term)
        ]

        chosen: list[str] = []
        seen_keys: set[str] = set()
        seen_words: set[str] = set()
        for group in (topic, material_phrases, key_terms, rare_phrases):
            ranked = []
            for concept in group:
                index = first_index(concept)
                if index is not None:
                    key = concept_key(concept)
                    # En el mismo fragmento, las frases antes que las palabras sueltas que contienen.
                    ranked.append((index, -len(key.split()), key, concept))
            for _, _, key, concept in sorted(ranked):
                words = key.split()
                # Una palabra suelta que ya está en un concepto elegido («modelo» en «modelo osi») no suma.
                if key in seen_keys or (len(words) == 1 and words[0] in seen_words):
                    continue
                seen_keys.add(key)
                seen_words.update(words)
                chosen.append(concept[:MAX_CONCEPT_CHARS])
        return chosen[:MAX_CANDIDATES]

    @staticmethod
    def _quantities(requested: list[int | None], available: int) -> list[int]:
        """La cantidad pedida, o una elegida según los conceptos (de 1 a 3). Si no alcanzan los conceptos, se baja la
        cantidad del último ítem que la tenga mayor que 1."""
        count = max(len(requested), 1)
        auto = min(AUTO_QUANTITY_MAX, max(1, available // (2 * count)))
        quantities = [q if q is not None else auto for q in requested]
        while sum(quantities) > available and any(q > 1 for q in quantities):
            last = max(i for i, q in enumerate(quantities) if q > 1)
            quantities[last] -= 1
        return quantities

    @staticmethod
    def _purpose(name: str, covers: list[str]) -> str:
        if not covers:
            return f"{name} sobre el tema pedido."
        shown = ", ".join(f"«{concept}»" for concept in covers[:3])
        more = f" y {len(covers) - 3} más" if len(covers) > 3 else ""
        return f"{name}: desarrolla {shown}{more}."[:MAX_PURPOSE_CHARS]


# Con Gemini (T007)


class InvalidPlanResponse(ValueError):
    """La IA respondió, pero su plan no sirve. `public_reason` es el motivo genérico."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.public_reason = detail


def plan_response_schema(inputs: PlanInputs) -> dict[str, Any]:
    """Esquema de respuesta del plan (como el de T073): `items` obligatorio, un ítem por tipo pedido, y cada ítem con
    tipo, cantidad, propósito, conceptos y fragmentos obligatorios. `minItems` y `maxItems` van como texto (int64)."""
    types = [requested.type for requested in inputs.resource_types]
    string = {"type": "STRING"}
    return {
        "type": "OBJECT",
        "properties": {
            "items": {
                "type": "ARRAY",
                "minItems": "1",
                "maxItems": str(len(types)),
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "resourceType": {"type": "STRING", "enum": types},
                        "quantity": {"type": "INTEGER"},
                        "purpose": string,
                        "covers": {"type": "ARRAY", "items": string, "minItems": "1"},
                        "fragmentos": {"type": "ARRAY", "items": string, "minItems": "1"},
                    },
                    "required": ["resourceType", "quantity", "purpose", "covers", "fragmentos"],
                },
            }
        },
        "required": ["items"],
    }


def build_plan_prompt(
    inputs: PlanInputs,
    evidence: PlanEvidence,
    catalog: Mapping[str, CatalogEntry],
    referents: Sequence[Referent] = (),
    session_context: SessionContext = SessionContext(),
    unit_title: str = "",
) -> PlanPrompt:
    system = (
        "Eres un asistente pedagógico que planifica los recursos de una clase universitaria antes de redactarlos. "
        "Usa SOLO la información de los FRAGMENTOS del material. Cada recurso tiene un propósito propio y desarrolla "
        "conceptos que ningún otro recurso desarrolla, para que no se repitan. No menciones el modelo 5E ni la "
        "metodología en los propósitos. Responde únicamente con JSON válido, sin delimitadores adicionales."
    )
    lines = [
        f"UNIDAD: {unit_title or 'sin título'}",
        f"TEMA PEDIDO: {inputs.instructions or 'el tema de la unidad'}",
    ]
    if inputs.audience:
        lines.append(f"PÚBLICO: {inputs.audience}")
    if inputs.competency:
        lines.append(f"COMPETENCIA: {inputs.competency}")
    lines += ["", "RECURSOS PEDIDOS (un ítem por cada uno):"]
    for requested in inputs.resource_types:
        entry = catalog.get(requested.type)
        name = entry.name if entry else requested.type
        stage = _stage_name(entry.stage) if entry else ""
        description = entry.description if entry else ""
        quantity = (f"cantidad {requested.quantity}" if requested.quantity is not None
                    else f"cantidad de {MIN_ITEM_QUANTITY} a {MAX_ITEM_QUANTITY}, según los conceptos")
        lines.append(f"- {requested.type} ({name}, etapa {stage}): {description} {quantity}.")
    if referents:
        lines += ["", "REFERENTES DEL TEMA: " + "; ".join(r.name for r in referents)]
    if session_context.previous_typologies:
        previous = session_context.previous_typologies[0]
        lines += ["", "TIPOS USADOS EN LA SESIÓN ANTERIOR (varía los enfoques): " + ", ".join(previous.resource_types)]
    lines += [
        "",
        "FORMATO DE RESPUESTA (JSON):",
        '{"items": [{"resourceType": "...", "quantity": 1, "purpose": "para qué sirve en la clase",',
        ' "covers": ["concepto o pregunta corta que este recurso desarrolla"], "fragmentos": ["F1"]}]}',
        "Ningún concepto puede aparecer en dos ítems. Cada ítem tiene al menos tantos conceptos como su cantidad y "
        "cita en «fragmentos» las etiquetas de los fragmentos donde están sus conceptos.",
        "",
        "FRAGMENTOS DEL MATERIAL:",
    ]
    for number, fragment in enumerate(evidence.fragments, 1):
        origin = ", ".join(x for x in (fragment.document_name, fragment.location) if x)
        lines += [f"[F{number}] ({origin})", fragment.text, ""]
    return PlanPrompt(system=system, user="\n".join(lines).strip(), schema=plan_response_schema(inputs))


def _resolve_tags(value: Any, tag_mapping: Mapping[str, str]) -> list[str]:
    values = value if isinstance(value, list) else [value]
    resolved: list[str] = []
    for item in values:
        for digits in re.findall(r"\d+", str(item)):
            fragment_id = tag_mapping.get(f"F{int(digits)}")
            if fragment_id and fragment_id not in resolved:
                resolved.append(fragment_id)
    return resolved


def items_from_model(
    raw: Any, inputs: PlanInputs, evidence: PlanEvidence, catalog: Mapping[str, CatalogEntry]
) -> tuple[PlanItem, ...]:
    """Traduce el plan de la IA: un ítem por tipo pedido, la cantidad pedida si la hay, conceptos limpios y sin
    repetir dentro del ítem, y las etiquetas F1…Fn traducidas a los ids de la evidencia."""
    raw_items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(raw_items, list):
        raise InvalidPlanResponse("sin la lista items")
    tag_mapping = {f"F{number}": fragment.id for number, fragment in enumerate(evidence.fragments, 1)}
    requested = {r.type: r.quantity for r in inputs.resource_types}
    items: dict[str, PlanItem] = {}
    for data in raw_items:
        if not isinstance(data, dict) or data.get("resourceType") not in requested:
            continue
        resource_type = data["resourceType"]
        if resource_type in items:
            continue
        try:
            model_quantity = int(data.get("quantity") or 1)
        except (TypeError, ValueError):
            model_quantity = 1
        quantity = requested[resource_type] or min(MAX_ITEM_QUANTITY, max(MIN_ITEM_QUANTITY, model_quantity))
        covers: list[str] = []
        keys: set[str] = set()
        for concept in data.get("covers") or []:
            text = " ".join(str(concept).split())[:MAX_CONCEPT_CHARS]
            if text and concept_key(text) not in keys:
                keys.add(concept_key(text))
                covers.append(text)
        entry = catalog.get(resource_type)
        items[resource_type] = PlanItem(
            position=len(items) + 1,
            stage=entry.stage if entry else "explain",
            resource_type=resource_type,
            quantity=quantity,
            purpose=" ".join(str(data.get("purpose") or "").split())[:MAX_PURPOSE_CHARS],
            covers=tuple(covers),
            fragment_ids=tuple(_resolve_tags(data.get("fragmentos") or [], tag_mapping)[:MAX_ITEM_FRAGMENTS]),
        )
    if set(items) != set(requested):
        raise InvalidPlanResponse("faltan tipos pedidos")
    return order_items(items.values())


class GenerationPlanner:
    """Arma los ítems del plan con la IA, si hay, y con reglas como respaldo. Devuelve (ítems, bloque `generator`)."""

    def __init__(self, drafter: PlanDrafterPort | None, catalog: Mapping[str, CatalogEntry]) -> None:
        self._drafter = drafter
        self._catalog = catalog
        self._rules = RuleBasedPlanner(catalog)

    def draft(
        self,
        inputs: PlanInputs,
        evidence: PlanEvidence,
        referents: Sequence[Referent] = (),
        session_context: SessionContext = SessionContext(),
        unit_title: str = "",
    ) -> tuple[tuple[PlanItem, ...], dict[str, Any]]:
        if self._drafter is None:
            return self._rules.draft(inputs, evidence), self._generator(None)
        description = self._drafter.description
        try:
            prompt = build_plan_prompt(inputs, evidence, self._catalog, referents, session_context, unit_title)
            items = items_from_model(self._drafter.draft_plan(prompt), inputs, evidence, self._catalog)
            known = {entry_id: entry.stage for entry_id, entry in self._catalog.items()}
            problems = validate_items(items, evidence.fragment_ids, inputs.modality, known)
            if problems:
                raise InvalidPlanResponse(", ".join(sorted({problem.code for problem in problems})))
        except InvalidPlanResponse as invalid:
            logger.warning("%s devolvió un plan no válido: %s", description, invalid)
            reason = f"{description} devolvió un plan no válido ({invalid.public_reason})."
        except Exception as error:  # el plan se arma igual, con reglas
            logger.warning("%s no armó el plan: %s", description, redact_secrets(str(error))[:500])
            reason = f"{description} no respondió ({public_reason(error)})."
        else:
            return items, {"description": description, "usesAi": True, "fallback": False, "fallbackReason": None}
        return self._rules.draft(inputs, evidence), self._generator(f"{reason} Se armó el plan con reglas.")

    @staticmethod
    def _generator(fallback_reason: str | None) -> dict[str, Any]:
        return {"description": RULES_PLANNER_DESCRIPTION, "usesAi": False, "fallback": fallback_reason is not None,
                "fallbackReason": fallback_reason}
