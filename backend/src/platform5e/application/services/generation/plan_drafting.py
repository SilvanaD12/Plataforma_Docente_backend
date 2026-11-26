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
from dataclasses import replace
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
from platform5e.application.services.generation.concept_extraction import outcome_concepts, phrase_groups
from platform5e.domain.generation.plan_coverage import contains_term
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


def _same_concept(first_key: str, second_key: str) -> bool:
    """Dos conceptos normalizados con las mismas palabras, en el mismo orden, salvo el plural regular."""
    first, second = first_key.split(), second_key.split()
    return len(first) == len(second) and all(b in _variants(a) or a in _variants(b) for a, b in zip(first, second))


def _appears(concept: str, tokens: set[str]) -> bool:
    words = concept_key(concept).split()
    return bool(words) and all(_variants(word) & tokens for word in words)


def _stage_name(stage: str) -> str:
    return PHASES_5E.get(stage, (stage, ""))[0]


class RuleBasedPlanner:
    """Planificador determinista (research R4)."""

    def __init__(self, catalog: Mapping[str, CatalogEntry]) -> None:
        self._catalog = catalog

    def draft(self, inputs: PlanInputs, evidence: PlanEvidence, outcome: str = "") -> tuple[PlanItem, ...]:
        """`outcome`: el texto del resultado de aprendizaje elegido (T029); sus frases y siglas van primero."""
        token_sets = [_tokens(fragment.text) for fragment in evidence.fragments]
        # Lo mínimo que necesita el plan: un concepto por recurso (1 si la cantidad es libre).
        minimum = sum(requested.quantity or 1 for requested in inputs.resource_types)
        candidates = self._candidates(inputs.instructions, [f.text for f in evidence.fragments], token_sets, minimum,
                                      outcome)
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
            # T027 (b): los fragmentos que mencionan sus conceptos (el término completo), primero los que mencionan más;
            # en empate, en el orden de la evidencia. Un fragmento que no menciona ninguno no es del ítem.
            mentions = [(sum(contains_term(fragment.text, concept) for concept in covers), order, fragment.id)
                        for order, fragment in enumerate(evidence.fragments)]
            fragment_ids = [fid for count, _, fid in sorted(mentions, key=lambda m: (-m[0], m[1])) if count > 0][
                :MAX_ITEM_FRAGMENTS]
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
    def _candidates(
        instructions: str, texts: list[str], token_sets: list[set[str]], minimum: int = 0, outcome: str = ""
    ) -> list[str]:
        """Conceptos candidatos que aparecen en la evidencia (T027 (b), `concept_extraction`): primero las frases del
        tema, después las frases del material que se repiten, las siglas y los términos de varias palabras que aparecen
        una vez; cada grupo por el primer fragmento donde aparece cada concepto, las frases antes que las siglas en el
        mismo fragmento y, en empate, alfabético. Nunca frases pegadas entre signos ni de los encabezados de página.
        T029: con un resultado de aprendizaje elegido, su grupo (frases y siglas del resultado) va antes que todos."""

        def first_index(concept: str) -> int | None:
            return next((i for i, text in enumerate(texts) if contains_term(text, concept)), None)

        chosen: list[str] = []
        seen_keys: set[str] = set()
        preferred, last_resort = phrase_groups(instructions, texts)
        groups = ([outcome_concepts(outcome)] if outcome else []) + list(preferred)
        for group in groups:
            if group is last_resort and len(chosen) >= minimum:
                break  # los de último recurso solo entran si los preferidos no alcanzan para el plan
            ranked = []
            for concept in group:
                if short_concept_problem(concept) is not None:
                    continue
                index = first_index(concept)
                if index is not None:
                    key = concept_key(concept)
                    ranked.append((index, -len(key.split()), key, concept))
            for _, _, key, concept in sorted(ranked):
                # Singular y plural son el mismo concepto («bloque de bytes» y «bloques de bytes»).
                if key in seen_keys or any(_same_concept(key, seen) for seen in seen_keys):
                    continue
                seen_keys.add(key)
                chosen.append(concept[:MAX_CONCEPT_CHARS])
            if group is groups[-1] and group is not last_resort and len(chosen) < minimum:
                groups.append(last_resort)
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


def _concepts_needed(quantity: int | None) -> int:
    """Conceptos mínimos de un ítem: uno por recurso; con cantidad libre, al menos uno."""
    return quantity if quantity is not None else MIN_ITEM_QUANTITY


def plan_response_schema(inputs: PlanInputs) -> dict[str, Any]:
    """Esquema de respuesta del plan (como el de T073). T027 (b): `items` es un objeto con una propiedad por tipo
    pedido, todas obligatorias, y cada una dice su mínimo exacto de conceptos (`covers.minItems` = la cantidad pedida)
    y su máximo. La cantidad solo se pide si el docente la dejó libre. `minItems` y `maxItems` van como texto (int64)."""
    string = {"type": "STRING"}
    concept = {"type": "STRING", "description": "Frase nominal de 2 a 4 palabras tomadas del material, o una sigla; "
               "nunca una oración ni una lista. Distinta de los conceptos de los demás ítems."}
    by_type: dict[str, Any] = {}
    for requested in inputs.resource_types:
        needed = _concepts_needed(requested.quantity)
        most = MAX_CONCEPTS_PER_BLOCK * (requested.quantity or MAX_ITEM_QUANTITY)
        required = ["purpose", "covers", "fragmentos"] + (["quantity"] if requested.quantity is None else [])
        by_type[requested.type] = {
            "type": "OBJECT",
            "properties": {
                "quantity": {"type": "INTEGER"},
                "purpose": string,
                "covers": {"type": "ARRAY", "items": concept, "minItems": str(needed), "maxItems": str(most)},
                "fragmentos": {"type": "ARRAY", "items": string, "minItems": "1"},
            },
            "required": required,
        }
    return {
        "type": "OBJECT",
        "properties": {"items": {"type": "OBJECT", "properties": by_type, "required": list(by_type)}},
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
    outcome: str = "",
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
    if outcome:
        # T029: el resultado elegido; sus conceptos van primero en los ítems.
        lines.append(f"RESULTADO DE APRENDIZAJE ELEGIDO: {outcome}. Los conceptos del plan empiezan por los de este "
                     "resultado que estén en los fragmentos.")
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
        if requested.quantity is not None:
            quantity = (f"cantidad {requested.quantity}: al menos {requested.quantity} conceptos distintos "
                        f"(como máximo {MAX_CONCEPTS_PER_BLOCK * requested.quantity})")
        else:
            quantity = (f"cantidad de {MIN_ITEM_QUANTITY} a {MAX_ITEM_QUANTITY}, según los conceptos: al menos tantos "
                        "conceptos como la cantidad que elijas")
        lines.append(f"- {requested.type} ({name}, etapa {stage}): {description} {quantity}.")
    if referents:
        lines += ["", "REFERENTES DEL TEMA: " + "; ".join(r.name for r in referents)]
    if session_context.previous_typologies:
        previous = session_context.previous_typologies[0]
        lines += ["", "TIPOS USADOS EN LA SESIÓN ANTERIOR (varía los enfoques): " + ", ".join(previous.resource_types)]
    lines += [
        "",
        "FORMATO DE RESPUESTA (JSON):",
        '{"items": {"<tipo pedido>": {"quantity": 1, "purpose": "para qué sirve en la clase",',
        ' "covers": ["frase corta del material que este recurso desarrolla"], "fragmentos": ["F1"]}}}',
        "Una clave por cada tipo pedido, con el tipo tal cual.",
        SHORT_CONCEPT_INSTRUCTION,
        f"En total hacen falta al menos {sum(_concepts_needed(r.quantity) for r in inputs.resource_types)} conceptos "
        "distintos. Ningún concepto puede aparecer en dos ítems, tampoco con otra forma (singular o plural, con o sin "
        "tildes, otro orden). Cada ítem cita en «fragmentos» las etiquetas de los fragmentos donde están sus conceptos.",
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
    raw: Any,
    inputs: PlanInputs,
    evidence: PlanEvidence,
    catalog: Mapping[str, CatalogEntry],
    dropped: dict[str, list[str]] | None = None,
) -> tuple[PlanItem, ...]:
    """Traduce el plan de la IA: un ítem por tipo pedido, la cantidad pedida si la hay, conceptos limpios y sin
    repetir dentro del ítem, y las etiquetas F1…Fn traducidas a los ids de la evidencia. Acepta `items` como objeto
    por tipo (el esquema de T027 (b)) o como lista. En `dropped` deja, por tipo, los conceptos descartados por no ser
    frases cortas, para decírselo a la IA en el reintento."""
    raw_items = raw.get("items") if isinstance(raw, dict) else None
    if isinstance(raw_items, dict):
        raw_items = [{**data, "resourceType": key} for key, data in raw_items.items() if isinstance(data, dict)]
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
                # Una oración o una lista no es un concepto; si el ítem se queda corto, el reintento lo dice.
                if dropped is not None and text:
                    dropped.setdefault(resource_type, []).append(text)
                continue
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
        outcome: str = "",
    ) -> tuple[tuple[PlanItem, ...], dict[str, Any]]:
        """`outcome`: el texto del resultado de aprendizaje elegido, o vacío (T029)."""
        if self._drafter is None:
            return self._rules.draft(inputs, evidence, outcome), self._generator(None, 0)
        description = self._drafter.description
        known = {entry_id: entry.stage for entry_id, entry in self._catalog.items()}
        feedback: str | None = None
        attempts = 0
        reason = ""
        while attempts < MAX_PLAN_ATTEMPTS:
            attempts += 1
            try:
                prompt = build_plan_prompt(inputs, evidence, self._catalog, referents, session_context, unit_title,
                                           retry_feedback=feedback, outcome=outcome)
                dropped: dict[str, list[str]] = {}
                items = items_from_model(self._drafter.draft_plan(prompt), inputs, evidence, self._catalog, dropped)
                items, repairs = repair_items(items, inputs)
                problems = validate_items(items, evidence.fragment_ids, inputs.modality, known)
                if problems:
                    raise InvalidPlanResponse(", ".join(sorted({problem.code for problem in problems})),
                                              problems_feedback(problems, items, dropped))
            except InvalidPlanResponse as invalid:
                logger.warning("%s devolvió un plan no válido (intento %s): %s", description, attempts, invalid)
                reason = f"{description} devolvió un plan no válido ({invalid.public_reason})."
                feedback = invalid.feedback  # se le devuelve en el reintento
            except Exception as error:  # error del proveedor, tiempo vencido o JSON inválido: sin reintento aquí
                logger.warning("%s no armó el plan: %s", description, redact_secrets(str(error))[:500])
                reason = f"{description} no respondió ({public_reason(error)})."
                break
            else:
                if repairs:
                    logger.info("%s: plan arreglado sin otra llamada: %s", description, repairs)
                return items, {"description": description, "usesAi": True, "fallback": False, "fallbackReason": None,
                               "attempts": attempts, "repairs": repairs}
        return self._rules.draft(inputs, evidence, outcome), self._generator(f"{reason} Se armó el plan con reglas.",
                                                                              attempts)

    @staticmethod
    def _generator(fallback_reason: str | None, attempts: int) -> dict[str, Any]:
        return {"description": RULES_PLANNER_DESCRIPTION, "usesAi": False, "fallback": fallback_reason is not None,
                "fallbackReason": fallback_reason, "attempts": attempts, "repairs": []}


def repair_items(
    items: Sequence[PlanItem], inputs: PlanInputs
) -> tuple[tuple[PlanItem, ...], list[dict[str, Any]]]:
    """T027 (b): arreglos seguros de un plan de la IA, sin perder lo que el docente pidió. Devuelve los ítems y la lista
    de arreglos (para `generator.repairs`).
    - Un concepto que ya tiene un ítem anterior se quita del posterior, si a este le siguen quedando los conceptos que
      necesita su cantidad.
    - Si el docente dejó la cantidad libre y la IA eligió más recursos que conceptos, la cantidad baja al número de
      conceptos. Una cantidad pedida por el docente nunca cambia."""
    requested = {r.type: r.quantity for r in inputs.resource_types}
    repairs: list[dict[str, Any]] = []
    owners: dict[str, str] = {}
    repaired: list[PlanItem] = []
    for item in items:
        covers = list(item.covers)
        needed = requested.get(item.resource_type) or 1
        for concept in list(covers):
            key = concept_key(concept)
            owner = owners.get(key)
            if owner is not None and owner != item.resource_type and len(covers) - 1 >= needed:
                covers.remove(concept)
                repairs.append({"code": "CONCEPT_OWNED_TWICE", "resourceType": item.resource_type,
                                "concept": concept, "action": "removed", "keptIn": owner})
        for concept in covers:
            owners.setdefault(concept_key(concept), item.resource_type)
        quantity = item.quantity
        if requested.get(item.resource_type) is None and covers and len(covers) < quantity:
            repairs.append({"code": "NOT_ENOUGH_CONCEPTS", "resourceType": item.resource_type,
                            "action": "quantity_lowered", "from": quantity, "to": len(covers)})
            quantity = len(covers)
        repaired.append(replace(item, covers=tuple(covers), quantity=quantity))
    return tuple(repaired), repairs


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def problems_feedback(
    problems: Sequence[PlanProblem], items: Sequence[PlanItem], dropped: Mapping[str, list[str]] | None = None
) -> str:
    """T027 (b): los problemas del plan para el reintento de la IA, por ítem (con su tipo), con los conceptos y lo que
    hay que hacer. Los demás problemas van con su código, su ítem y su mensaje."""
    by_position = {item.position: item for item in items}
    dropped = dropped or {}
    lines: list[str] = []
    for problem in problems:
        item = by_position.get(problem.item_position) if problem.item_position is not None else None
        if item is not None and problem.code == "NOT_ENOUGH_CONCEPTS":
            count = len(item.covers)
            shown = ", ".join(f"«{c}»" for c in item.covers) or "ninguno"
            missing = item.quantity - count
            line = (f"- NOT_ENOUGH_CONCEPTS: El ítem «{item.resource_type}» tiene {count} "
                    f"{_plural(count, 'concepto válido', 'conceptos válidos')} ({shown}) y necesita {item.quantity}: "
                    f"agrega {missing} {_plural(missing, 'concepto corto', 'conceptos cortos')} del material que ningún "
                    "otro ítem tenga.")
            if dropped.get(item.resource_type):
                line += (" Se descartaron por no ser frases cortas: "
                         + ", ".join(f"«{c}»" for c in dropped[item.resource_type])
                         + "; reemplázalos por frases de 2 a 4 palabras del material.")
            lines.append(line)
        elif item is not None and problem.code == "CONCEPT_OWNED_TWICE":
            earlier = {concept_key(c): other.resource_type for other in items if other.position < item.position
                       for c in other.covers}
            for concept in item.covers:
                owner = earlier.get(concept_key(concept))
                if owner is not None:
                    lines.append(f"- CONCEPT_OWNED_TWICE: «{concept}» está en «{owner}» y en «{item.resource_type}»: "
                                 f"déjalo solo en «{owner}» y pon en «{item.resource_type}» otro concepto del "
                                 "material.")
                    break
        else:
            where = f" en el ítem «{item.resource_type}»" if item is not None else " en el plan"
            lines.append(f"- {problem.code}{where}: {problem.message}")
    return "\n".join(dict.fromkeys(lines))


