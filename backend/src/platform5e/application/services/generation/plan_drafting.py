"""
GEN-P1 (T006, T007): cómo se arma el plan (specs/006-plan-de-generacion/research.md R4).

- `RuleBasedPlanner`: determinista y sin IA. Toma los conceptos candidatos del tema y del material, los reparte por
  turnos entre los bloques de los ítems (un bloque por recurso) y le da a cada ítem los fragmentos donde aparecen sus
  conceptos. Las mismas entradas y la misma evidencia dan el mismo plan.
- Con Gemini, una sola llamada (`PlanDrafterPort.draft_plan`) con esquema de respuesta propio y el tiempo límite de
  QA-06. Si la llamada falla, vence o el plan no es válido, `GenerationPlanner` lo arma con reglas y guarda el motivo
  público en `fallbackReason`.

Corrección tras P4 (research R4): los conceptos son frases nominales cortas, de 2 a 4 palabras útiles tomadas del
material, o siglas. El planificador por reglas ya no propone palabras sueltas comunes; a la IA se le pide en el prompt
y en el esquema, y los conceptos largos que devuelva se descartan (si el ítem se queda corto, el plan va a reglas).

Segunda corrida de P4 (research R4): si el plan de la IA no es válido (problemas de validación o tipos que faltan), se le
pide una vez más con los problemas (código, ítem y tipo); si vuelve a fallar, se arma con reglas. Un error del
proveedor, un tiempo vencido o un JSON inválido no se reintentan aquí. `generator.attempts` cuenta las llamadas a la IA.
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
    PlanProblem,
    Referent,
    SessionContext,
    order_items,
)
from platform5e.domain.generation.plan_validation import short_concept_problem, validate_items
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
# Siglas del material que cuentan como concepto («UDP», «TCP», «IPv4»): al menos dos apariciones.
_ACRONYM_IN_TEXT = re.compile(r"(?<![\w-])([A-Z]{2,6}(?:v\d)?)(?![\w-])")
MIN_ACRONYM_COUNT: int = 2
SHORT_CONCEPT_INSTRUCTION: str = (
    "Cada concepto es una frase nominal corta de 2 a 4 palabras tomadas tal cual de los fragmentos (por ejemplo "
    "«control de flujo» o «saludo de tres vías»), o una sigla del material: nunca una oración, una lista, una pregunta "
    "ni una palabra suelta común."
)
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
        # Las palabras sueltas solo cuentan si son siglas del material («UDP»); una palabra común no es un concepto.
        acronym_counts: dict[str, int] = {}
        for text in texts:
            for acronym in _ACRONYM_IN_TEXT.findall(text):
                acronym_counts[acronym] = acronym_counts.get(acronym, 0) + 1
        key_terms = [acronym for acronym, count in acronym_counts.items() if count >= MIN_ACRONYM_COUNT]

        chosen: list[str] = []
        seen_keys: set[str] = set()
        seen_words: set[str] = set()
        for group in (topic, material_phrases, key_terms, rare_phrases):
            ranked = []
            for concept in group:
                if short_concept_problem(concept) is not None:
                    continue
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


def candidate_concepts(instructions: str, texts: Sequence[str], limit: int = MAX_CANDIDATES) -> list[str]:
    """Los conceptos candidatos del planificador por reglas para unos textos: frases cortas del tema y del material, y
    siglas. La medición de P4 los usa para comparar los dos modos con los mismos conceptos."""
    token_sets = [_tokens(text) for text in texts]
    return RuleBasedPlanner._candidates(instructions, list(texts), token_sets)[:limit]


# Con Gemini (T007)


MAX_PLAN_ATTEMPTS: int = 2
RETRY_HEADER: str = "TU PLAN ANTERIOR NO ERA VÁLIDO. Corrige estos problemas y devuelve el plan completo otra vez:"


class InvalidPlanResponse(ValueError):
    """La IA respondió, pero su plan no sirve. `public_reason` es el motivo genérico; `feedback`, lo que se le devuelve
    a la IA en el reintento (por cada problema: código, ítem y tipo)."""

    def __init__(self, detail: str, feedback: str | None = None) -> None:
        super().__init__(detail)
        self.public_reason = detail
        self.feedback = feedback or detail


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
                        "covers": {
                            "type": "ARRAY",
                            "items": {"type": "STRING", "description": "Frase nominal de 2 a 4 palabras tomadas del "
                                      "material, o una sigla; nunca una oración ni una lista."},
                            "minItems": "1",
                        },
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
    retry_feedback: str | None = None,
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
        ' "covers": ["frase corta del material que este recurso desarrolla"], "fragmentos": ["F1"]}]}',
        SHORT_CONCEPT_INSTRUCTION,
        "Ningún concepto puede aparecer en dos ítems. Cada ítem tiene al menos tantos conceptos como su cantidad y "
        "cita en «fragmentos» las etiquetas de los fragmentos donde están sus conceptos.",
        "",
        "FRAGMENTOS DEL MATERIAL:",
    ]
    for number, fragment in enumerate(evidence.fragments, 1):
        origin = ", ".join(x for x in (fragment.document_name, fragment.location) if x)
        lines += [f"[F{number}] ({origin})", fragment.text, ""]
    if retry_feedback:
        lines += ["", RETRY_HEADER, retry_feedback]
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
            if short_concept_problem(text) is not None:
                continue  # una oración o una lista no es un concepto; si el ítem se queda corto, el plan va a reglas
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
        missing = ", ".join(t for t in requested if t not in items)
        raise InvalidPlanResponse(f"faltan tipos pedidos: {missing}",
                                  f"- Falta un ítem para cada uno de estos tipos pedidos: {missing}.")
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
            return self._rules.draft(inputs, evidence), self._generator(None, 0)
        description = self._drafter.description
        known = {entry_id: entry.stage for entry_id, entry in self._catalog.items()}
        feedback: str | None = None
        attempts = 0
        reason = ""
        while attempts < MAX_PLAN_ATTEMPTS:
            attempts += 1
            try:
                prompt = build_plan_prompt(inputs, evidence, self._catalog, referents, session_context, unit_title,
                                           retry_feedback=feedback)
                items = items_from_model(self._drafter.draft_plan(prompt), inputs, evidence, self._catalog)
                problems = validate_items(items, evidence.fragment_ids, inputs.modality, known)
                if problems:
                    raise InvalidPlanResponse(", ".join(sorted({problem.code for problem in problems})),
                                              problems_feedback(problems, items))
            except InvalidPlanResponse as invalid:
                logger.warning("%s devolvió un plan no válido (intento %s): %s", description, attempts, invalid)
                reason = f"{description} devolvió un plan no válido ({invalid.public_reason})."
                feedback = invalid.feedback  # se le devuelve en el reintento
            except Exception as error:  # error del proveedor, tiempo vencido o JSON inválido: sin reintento aquí
                logger.warning("%s no armó el plan: %s", description, redact_secrets(str(error))[:500])
                reason = f"{description} no respondió ({public_reason(error)})."
                break
            else:
                return items, {"description": description, "usesAi": True, "fallback": False, "fallbackReason": None,
                               "attempts": attempts}
        return self._rules.draft(inputs, evidence), self._generator(f"{reason} Se armó el plan con reglas.", attempts)

    @staticmethod
    def _generator(fallback_reason: str | None, attempts: int) -> dict[str, Any]:
        return {"description": RULES_PLANNER_DESCRIPTION, "usesAi": False, "fallback": fallback_reason is not None,
                "fallbackReason": fallback_reason, "attempts": attempts}


def problems_feedback(problems: Sequence[PlanProblem], items: Sequence[PlanItem]) -> str:
    """Los problemas del plan para el reintento de la IA: código, ítem (posición y tipo) y mensaje."""
    types = {item.position: item.resource_type for item in items}
    lines = []
    for problem in problems:
        where = (f" en el ítem {problem.item_position} ({types.get(problem.item_position, '?')})"
                 if problem.item_position is not None else " en el plan")
        lines.append(f"- {problem.code}{where}: {problem.message}")
    return "\n".join(lines)
