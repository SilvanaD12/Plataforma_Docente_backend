"""Interpretación por reglas de un pedido editable (HU-038)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from platform5e.application.ports.outbound.unit_membership_port import UnitContext, UnitMembershipPort
from platform5e.application.use_cases.generation.start_generation_request import UNIT_NOT_FOUND_MESSAGE
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import MODALITIES, resource_stage, types_outside_modality
from platform5e.domain.generation.sequence import (
    MAX_QUANTITY_PER_TYPE,
    MAX_SEQUENCE_TYPES,
    MIN_QUANTITY_PER_TYPE,
    order_resource_types,
)
from platform5e.domain.materials.text_analysis import normalize_text


class InterpretationOption(TypedDict):
    value: str | int
    label: str


class InterpretationIssue(TypedDict):
    field: str
    kind: str
    message: str
    options: list[InterpretationOption]


class SuggestedUnit(TypedDict):
    unitId: str
    label: str


class InterpretedStage(TypedDict):
    resourceType: str
    stage: str


class GenerationInterpretation(TypedDict):
    draft: dict[str, object]
    stages: list[InterpretedStage]
    issues: list[InterpretationIssue]
    suggestedUnit: NotRequired[SuggestedUnit]


@dataclass(frozen=True)
class InterpretGenerationCommand:
    teacher_id: str
    unit_id: str
    message: str


_STAGE_NAMES = {
    "enganchar": "engage",
    "explorar": "explore",
    "explicar": "explain",
    "elaborar": "elaborate",
    "evaluar": "evaluate",
}
_NUMBER_WORDS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "cero": 0, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "veinte": 20,
}
_NUMBER = r"[+-]?[0-9]+(?:[.,][0-9]+)?|" + "|".join(_NUMBER_WORDS)
_LEADING_QUANTITY = re.compile(rf"(?<![\w.,+\-])({_NUMBER})\s+$")
_EXPLICIT_QUANTITY = re.compile(rf"\bcantidad\s*[:=]?\s*({_NUMBER})(?!\w|[.,][0-9])")
_REMOVE_OUTCOME = re.compile(
    r"\b(?:sin|quita(?:r)?(?: el)?|elimina(?:r)?(?: el)?|borra(?:r)?(?: el)?) "
    r"resultado(?: de aprendizaje)?\b"
)
_FIELD = re.compile(
    r"(?:^|[;,\n]|\s)\s*(audiencia|competencia|instrucciones|resultado(?: de aprendizaje)?|unidad)\s*:\s*",
    re.IGNORECASE,
)
_UNIT_PREFIX = re.compile(r"^\s*(?:para|en)\s+(?:la unidad\s+)?([^,;\n]+)\s*[,;\n]", re.IGNORECASE)
_QUOTED_UNIT = re.compile(
    r'\b(?:para|en)\s+la unidad\s+(?:«([^»]+)»|"([^"]+)")', re.IGNORECASE,
)
_OUTCOME_CODE = re.compile(r"\bRA\d+(?:[.-]\d+)*\b", re.IGNORECASE)
_FIELD_LIMITS = {"audience": 200, "competency": 200, "instructions": 500}
_FIELD_LABELS = {"audiencia": "audience", "competencia": "competency", "instrucciones": "instructions"}
_TYPE_NAMES = {entry.id: entry.name for entry in RESOURCE_TYPES}


def _alias_pattern() -> tuple[re.Pattern[str], dict[str, str]]:
    aliases = {
        normalize_text(label).replace("_", " "): entry.id
        for entry in RESOURCE_TYPES
        for label in (entry.id, entry.name, entry.singular, *entry.count)
    }
    alternatives = sorted(aliases, key=lambda alias: (-len(alias), alias))
    return re.compile(r"\b(?:" + "|".join(map(re.escape, alternatives)) + r")\b"), aliases


_TYPE_PATTERN, _TYPE_ALIASES = _alias_pattern()


def _issue(
    field: str, kind: str, message: str, options: list[InterpretationOption] | None = None,
) -> InterpretationIssue:
    return {"field": field, "kind": kind, "message": message, "options": options or []}


def _type_options(type_ids: Sequence[str]) -> list[InterpretationOption]:
    return [{"value": type_id, "label": _TYPE_NAMES[type_id]} for type_id in type_ids]


def _parts(message: str) -> tuple[str, dict[str, list[str]]]:
    """Separa los campos rotulados del texto que describe los recursos."""
    fields: dict[str, list[str]] = {}
    matches = list(_FIELD.finditer(message))
    request = message[:matches[0].start()] if matches else message
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(message)
        value = message[match.end():end].strip(" \t\r\n;,")
        fields.setdefault(normalize_text(match[1]), []).append(value)
    prefix = _UNIT_PREFIX.match(request)
    if prefix and normalize_text(prefix[1].strip()) not in _STAGE_NAMES:
        fields.setdefault("unidad", []).append(prefix[1].strip())
        request = request[prefix.end():]
    for mention in _QUOTED_UNIT.finditer(request):
        fields.setdefault("unidad", []).append(mention[1] or mention[2])
    request = _QUOTED_UNIT.sub(" ", request)
    return request, fields


def _read_quantity(
    request: str, mentions: list[re.Match[str]], issues: list[InterpretationIssue],
) -> int | None:
    numbers = [match[1] for match in _EXPLICIT_QUANTITY.finditer(request)]
    for mention in mentions:
        match = _LEADING_QUANTITY.search(request[:mention.start()])
        if match:
            numbers.append(match[1])
    if not numbers:
        return None
    if any("." in number or "," in number for number in numbers):
        issues.append(_issue("quantity", "not_allowed", "La cantidad por tipo debe ser un número entero."))
        return None
    values = {_NUMBER_WORDS[number] if number in _NUMBER_WORDS else int(number) for number in numbers}
    if len(values) > 1:
        options: list[InterpretationOption] = [
            {"value": value, "label": str(value)} for value in sorted(values)
            if MIN_QUANTITY_PER_TYPE <= value <= MAX_QUANTITY_PER_TYPE
        ]
        issues.append(_issue("quantity", "ambiguous", "Elige una sola cantidad común por tipo.", options))
        return None
    value = values.pop()
    if not MIN_QUANTITY_PER_TYPE <= value <= MAX_QUANTITY_PER_TYPE:
        issues.append(_issue(
            "quantity", "not_allowed",
            f"La cantidad por tipo debe estar entre {MIN_QUANTITY_PER_TYPE} y {MAX_QUANTITY_PER_TYPE}.",
        ))
        return None
    return value


def _read_modality(request: str, issues: list[InterpretationIssue]) -> str | None:
    mentions = [mode for mode in MODALITIES if re.search(rf"\b{normalize_text(mode)}\b", request)]
    if len(mentions) == 1:
        return mentions[0]
    if mentions or re.search(r"\bmodalidad\b", request):
        options: list[InterpretationOption] = [{"value": mode, "label": mode} for mode in mentions or MODALITIES]
        issues.append(_issue(
            "modalities", "ambiguous" if mentions else "not_allowed", "Elige una modalidad del catálogo.", options,
        ))
    return None


def _read_types(
    mentions: list[re.Match[str]], request: str, modality: str | None, issues: list[InterpretationIssue],
) -> list[str]:
    requested = list(dict.fromkeys(_TYPE_ALIASES[mention[0]] for mention in mentions))
    outside = types_outside_modality(modality, requested) if modality else []
    if outside:
        names = ", ".join(_TYPE_NAMES[type_id] for type_id in outside)
        issues.append(_issue("resourceTypes", "not_allowed", f"Tipos fuera de la modalidad {modality}: {names}."))
    resolved = [type_id for type_id in requested if type_id not in outside]
    if len(resolved) > MAX_SEQUENCE_TYPES:
        issues.append(_issue(
            "resourceTypes", "not_allowed", f"Elige hasta {MAX_SEQUENCE_TYPES} tipos.", _type_options(resolved),
        ))
        return []
    if requested:
        return order_resource_types(resolved) if resolved else []
    stages = {stage for name, stage in _STAGE_NAMES.items() if re.search(rf"\b{name}\b", request)}
    candidates = [entry.id for entry in RESOURCE_TYPES if entry.stage in stages]
    if modality:
        candidates = [type_id for type_id in candidates if not types_outside_modality(modality, [type_id])]
    issues.append(_issue(
        "resourceTypes", "ambiguous" if stages else "missing",
        "Elige un tipo de recurso para la etapa indicada." if stages else "Indica qué tipo de recurso necesitas.",
        _type_options(candidates),
    ))
    return []


def _apply_outcome(
    unit: UnitContext, fields: dict[str, list[str]], request: str, draft: dict[str, object],
    issues: list[InterpretationIssue],
) -> None:
    names = fields.get("resultado", []) + fields.get("resultado de aprendizaje", [])
    if not names:
        names = _OUTCOME_CODE.findall(request)
    names_normalized = {normalize_text(name) for name in names}
    removal_values = {"ninguno", "sin resultado"}
    remove = bool(_REMOVE_OUTCOME.search(request)) or bool(names_normalized & removal_values)
    if not names and not remove:
        return
    if remove and names_normalized <= removal_values:
        draft["outcomeId"] = None
        return
    matches = [
        outcome for outcome in unit.outcomes
        if names_normalized.intersection(map(normalize_text, (outcome.id, outcome.code, outcome.text)))
    ]
    if len(matches) == 1 and len(names_normalized) == 1 and not remove:
        draft["outcomeId"] = matches[0].id
        return
    options: list[InterpretationOption] = [
        {"value": outcome.id, "label": f"{outcome.code} {outcome.text}".strip()}
        for outcome in matches or unit.outcomes
    ]
    issues.append(_issue(
        "outcomeId", "ambiguous" if matches else "not_allowed",
        "Selecciona un resultado de aprendizaje de la unidad activa.", options,
    ))


def _apply_text(fields: dict[str, list[str]], draft: dict[str, object], issues: list[InterpretationIssue]) -> None:
    for label, key in _FIELD_LABELS.items():
        values = list(dict.fromkeys(fields.get(label, [])))
        if len(values) > 1:
            issues.append(_issue(key, "ambiguous", f"Indica un único valor para {label}."))
        elif values:
            value = values[0]
            if not value:
                issues.append(_issue(key, "missing", f"Indica el valor de {label}."))
            elif len(value) > _FIELD_LIMITS[key]:
                issues.append(_issue(key, "not_allowed", f"{label.capitalize()} admite hasta {_FIELD_LIMITS[key]} caracteres."))
            else:
                draft[key] = value


class InterpretGenerationRequest:
    """Usa únicamente consultas de pertenencia y de unidades propias del docente."""

    def __init__(
        self,
        membership: UnitMembershipPort,
        list_owned_units: Callable[[str], Sequence[SuggestedUnit]],
    ) -> None:
        self._membership = membership
        self._list_owned_units = list_owned_units

    def execute(self, command: InterpretGenerationCommand) -> GenerationInterpretation:
        unit = self._membership.get_unit_context(command.teacher_id, command.unit_id)
        if unit is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)

        request, fields = _parts(command.message)
        request = re.sub(r"\s+", " ", normalize_text(request)).strip()
        catalog_text = request.replace("_", " ")
        mentions = list(_TYPE_PATTERN.finditer(catalog_text))
        issues: list[InterpretationIssue] = []
        modality = _read_modality(request, issues)
        types = _read_types(mentions, request, modality, issues)
        quantity = _read_quantity(catalog_text, mentions, issues)
        draft: dict[str, object] = {"unitId": unit.unit_id, "resourceTypes": types}
        if types:
            draft["mode"] = "individual" if len(types) == 1 else "sequence"
        if modality is not None:
            draft["modalities"] = [modality]
        if quantity is not None:
            draft["quantity"] = quantity
        _apply_outcome(unit, fields, request, draft, issues)
        _apply_text(fields, draft, issues)

        result: GenerationInterpretation = {
            "draft": draft,
            "stages": [{"resourceType": type_id, "stage": resource_stage(type_id)} for type_id in types],
            "issues": issues,
        }
        references = {normalize_text(name.strip(" «»\"'")) for name in fields.get("unidad", [])}
        if references and references != {normalize_text(unit.unit_title)}:
            owned = self._list_owned_units(command.teacher_id)
            matches = {
                candidate["unitId"]: candidate for candidate in owned
                if normalize_text(candidate["label"]) in references
            }
            if len(references) == len(matches) == 1:
                candidate = next(iter(matches.values()))
                if candidate["unitId"] != unit.unit_id:
                    result["suggestedUnit"] = candidate
            else:
                issues.append(_issue("unitId", "ambiguous", "Revisa la unidad mencionada. Se mantiene la unidad activa."))
        return result
