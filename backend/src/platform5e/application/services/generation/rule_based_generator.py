"""
Generador basado en reglas deterministas: extrae oraciones y términos del material
para componer propuestas sin requerir dependencias de modelos LLM externos.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from platform5e.domain.materials.chunking import extract_sentences
from platform5e.domain.materials.text_analysis import (
    STOPWORDS,
    extract_key_terms,
    normalize_text,
    stem_word,
)

_URL_PATTERN: re.Pattern[str] = re.compile(r"https?://|^(Fuente|Licencia):", re.IGNORECASE)
_WORD_REGEX: str = r"[\wáéíóúñÁÉÍÓÚÑ/-]+"
_SUBJECT_REGEX: re.Pattern[str] = re.compile(
    rf"(?:^|[,;:]\s+)(?:[Ee]l|[Ll]a|[Ll]os|[Ll]as|[Uu]n|[Uu]na)\s+((?:{_WORD_REGEX}\s+){{0,2}}?{_WORD_REGEX})\s+"
    r"(?:no\s+|también\s+|solo\s+)?(?:es|son|fue|se\s+encarga|se\s+usa|se\s+utiliza|se\s+define|trabaja|trabajan|"
    r"permite|permiten|consiste|establece|garantiza|divide|tiene|tienen|ofrece|decide|traduce|agrega)\b"
)
_ACRONYM_REGEX: re.Pattern[str] = re.compile(r"(?<![\w/])([A-Z]{2,6}(?:/[A-Z]{2,6})?)(?![\w/])")
_ROMAN_NUMERALS: set[str] = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII"}


def _extract_domain_terms(
    sentence_pairs: list[tuple[str, str]], fallback_terms: list[str]
) -> list[str]:
    """Identifica sujetos gramaticales de definiciones, siglas y términos frecuentes."""
    identified_subjects: list[str] = []
    for _, sentence in sentence_pairs:
        for match in _SUBJECT_REGEX.finditer(sentence):
            words = match.group(1).split()
            while words and normalize_text(words[-1]) in STOPWORDS:
                words.pop()
            if words and normalize_text(words[0]) not in STOPWORDS:
                identified_subjects.append(" ".join(words))

    acronym_counts = Counter(
        match
        for _, sentence in sentence_pairs
        for match in _ACRONYM_REGEX.findall(sentence)
        if match not in _ROMAN_NUMERALS
    )

    seen_stems: set[str] = set()
    ordered_terms: list[str] = []
    candidates = [
        *identified_subjects,
        *(acronym for acronym, _ in acronym_counts.most_common()),
        *fallback_terms,
    ]

    for candidate in candidates:
        normalized_candidate = normalize_text(candidate)
        if normalized_candidate not in seen_stems and len(normalized_candidate) >= 2:
            seen_stems.add(normalized_candidate)
            ordered_terms.append(candidate)

    return ordered_terms


def _are_related_terms(term_a: str, term_b: str) -> bool:
    """Verifica si dos términos comparten la raíz morfológica o subcadenas completas."""
    norm_a, norm_b = normalize_text(term_a), normalize_text(term_b)
    if norm_a in norm_b or norm_b in norm_a:
        return True
    if " " not in norm_a or " " not in norm_b:
        return stem_word(norm_a.split()[0]) == stem_word(norm_b.split()[0])
    return False


def _share_head_word(term_a: str, term_b: str) -> bool:
    """Determina si ambos términos inician con el mismo sustantivo o palabra principal."""
    return normalize_text(term_a.split()[0]) == normalize_text(term_b.split()[0])


def _contains_word(text: str, word: str) -> bool:
    """Busca coincidencia exacta de palabra evitando falsos positivos de subcadena."""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def _mask_target_word(sentence: str, target: str) -> str:
    """Oculta el término central para crear el ítem de completación."""
    return re.sub(rf"(?<!\w){re.escape(target)}(?!\w)", "________", sentence, count=1, flags=re.IGNORECASE)


def _capitalize_first(text: str) -> str:
    """Pone en mayúscula únicamente el primer carácter del texto."""
    return text[:1].upper() + text[1:]



# Tipo de recurso (valor guardado en la base) -> método que lo redacta.
_BUILDERS_BY_TYPE: dict[str, str] = {
    "item_opcion_multiple": "_multiple_choice_item",
    "pregunta_detonante": "_trigger_question",
    "sondeo_diagnostico": "_diagnostic_survey",
    "guia_exploracion": "_exploration_guide",
    "caso_indagacion": "_inquiry_case",
    "explicacion": "_explanation",
    "glosario": "_glossary",
    "ejercicio_aplicacion": "_application_exercise",
    "caso_aplicado": "_applied_case",
    "audio_detonante": "_audio_trigger",
    "reto_prediccion": "_prediction_challenge",
    "podcast_resumen": "_podcast_summary",
    "imagen_ilustrativa": "_illustration",
    "diagrama_proceso": "_process_diagram",
    "exploracion_guiada": "_guided_exploration",
    "actividad_kinestesica": "_kinesthetic_activity",
    "mapa_conceptual": "_concept_map",
    "infografia": "_infographic",
    "emparejamiento": "_matching_activity",
    "ordenar_pasos": "_ordering_activity",
    "verdadero_falso": "_true_false_activity",
    "completar_espacios": "_fill_in_activity",
}


def _shorten(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _term_in(sentence: str, terms: list[str]) -> str | None:
    return next((term for term in terms if _contains_word(sentence, term)), None)


def _definitions(sentence_pairs: list[tuple[str, str]], terms: list[str], offset: int, limit: int) -> list[tuple[str, str, str]]:
    """(término, etiqueta, oración que lo define), un término por oración."""
    found: list[tuple[str, str, str]] = []
    used: set[str] = set()
    for term in terms[offset:]:
        match = next(
            (
                (tag, sentence)
                for tag, sentence in sentence_pairs
                if sentence not in used
                and _contains_word(sentence, term)
                and re.search(r"\b(es|son|se define|consiste|significa|permite)\b", sentence, re.IGNORECASE)
            ),
            None,
        ) or next(
            ((tag, sentence) for tag, sentence in sentence_pairs if sentence not in used and _contains_word(sentence, term)),
            None,
        )
        if match:
            used.add(match[1])
            found.append((term, match[0], match[1]))
        if len(found) == limit:
            break
    return found

class RuleBasedGenerator:
    """Generador determinista de recursos pedagógicos para respaldo ante caídas de red."""

    description: str = "Generador por reglas (sin IA)"
    uses_ai: bool = False

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        """Procesa los fragmentos de entrada y genera propuestas según el tipo solicitado."""
        sentence_pairs: list[tuple[str, str]] = []
        seen_sentences: set[str] = set()

        for frag in context["fragmentos"]:
            for sentence in extract_sentences(frag["texto"]):
                sentence_key = normalize_text(sentence)
                if (
                    8 <= len(sentence.split()) <= 45
                    and not _URL_PATTERN.search(sentence)
                    and re.search(r'[.!?…»”")]$', sentence)
                    and sentence_key not in seen_sentences
                ):
                    seen_sentences.add(sentence_key)
                    sentence_pairs.append((frag["etiqueta"], sentence))

        fragment_texts = [f["texto"] for f in context["fragmentos"]]
        frequent_terms = [
            term
            for term in extract_key_terms(fragment_texts, 24)
            if normalize_text(term) not in {"fuente", "licencia", "wikipedia"}
        ]
        key_terms = _extract_domain_terms(sentence_pairs, frequent_terms)

        request_info = context["solicitud"]
        builder_name = _BUILDERS_BY_TYPE.get(request_info["tipo"])
        builder_method = getattr(self, builder_name) if builder_name else None
        if builder_method is None:
            return {"recursos": []}

        built_resources: list[dict[str, Any]] = []
        for index in range(request_info["cantidad"]):
            resource = builder_method(index, sentence_pairs, key_terms, context)
            if resource and all(
                (resource["contenido"], resource.get("estructura")) != (item["contenido"], item.get("estructura"))
                for item in built_resources
            ):
                built_resources.append(resource)

        return {"recursos": built_resources}

    @staticmethod
    def _find_matching_pair(
        sentence_pairs: list[tuple[str, str]], terms: list[str], index: int
    ) -> tuple[str, str, str] | None:
        """Selecciona de forma determinista una oración que contenga uno de los términos."""
        matches = [
            (tag, sentence, term)
            for term in terms
            for tag, sentence in sentence_pairs
            if _contains_word(sentence, term)
        ]
        return matches[(index * 3) % len(matches)] if matches else None

    def _multiple_choice_item(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Construye un ítem de opción múltiple ocultando la palabra clave."""
        options_count = context["solicitud"]["alternativas"]
        matches = [
            (tag, sentence, term)
            for term in terms
            for tag, sentence in sentence_pairs
            if _contains_word(sentence, term)
        ]

        for offset in range(len(matches)):
            tag, sentence, key_term = matches[(index * 3 + offset) % len(matches)]
            candidates = [
                term
                for term in terms
                if not _are_related_terms(key_term, term) and not _contains_word(sentence, term)
            ]
            head_word = normalize_text(key_term.split()[0])
            candidates.sort(key=lambda term: normalize_text(term.split()[0]) != head_word)

            distractors: list[str] = []
            for candidate in candidates:
                if not any(_are_related_terms(candidate, dist) for dist in distractors):
                    distractors.append(candidate)

            distractors = distractors[: options_count - 1]
            if len(distractors) < options_count - 1:
                continue

            origins = {
                dist: next((t for t, s in sentence_pairs if _contains_word(s, dist)), tag)
                for dist in distractors
            }

            alternatives: list[dict[str, Any]] = [
                {
                    "texto": key_term,
                    "correcta": True,
                    "fragmentos": [tag],
                    "retroalimentacion": f"Correcto. El material lo afirma así: «{sentence}»",
                }
            ]
            alternatives += [
                {
                    "texto": dist,
                    "correcta": False,
                    "fragmentos": [origins[dist]],
                    "retroalimentacion": (
                        f"Incorrecto. «{dist}» aparece en el material, pero con otro sentido. "
                        f"La afirmación original es: «{sentence}»"
                    ),
                    "error_conceptual": (
                        f"Confunde «{dist}» con «{key_term}»: ambos son conceptos de la unidad, pero la afirmación "
                        f"se refiere a «{key_term}»."
                    ),
                }
                for dist in distractors
            ]

            return {
                "titulo": f"Concepto clave {index + 1}: {context['unidad']['titulo']}",
                "contenido": (
                    "Según el material de la unidad, ¿qué término completa correctamente la siguiente afirmación?\n\n"
                    f"«{_mask_target_word(sentence, key_term)}»"
                ),
                "citas": [{"afirmacion": sentence, "fragmentos": [tag]}],
                "alternativas": alternatives,
            }
        return None

    def _trigger_question(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        matched = self._find_matching_pair(sentence_pairs, terms, index)
        if not matched:
            return None
        tag, sentence, term = matched
        return {
            "titulo": f"¿Qué sabes sobre {term}?",
            "contenido": (
                f"Situación para iniciar la clase:\n«{sentence}»\n\n"
                f"Pregunta detonante: ¿Dónde has visto {term} en tu vida diaria y qué pasaría si no existiera? "
                "Comparte una respuesta breve antes de revisar el tema."
            ),
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]}],
            "alternativas": [],
        }

    def _diagnostic_survey(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        selected_pairs = sentence_pairs[index * 4 : index * 4 + 4] or sentence_pairs[:4]
        if len(selected_pairs) < 2:
            return None

        statements: list[str] = []
        answers_key: list[str] = []
        citations: list[dict[str, Any]] = []

        for num, (tag, sentence) in enumerate(selected_pairs, start=1):
            replacement = next(
                (
                    (p, q)
                    for p in terms
                    if _contains_word(sentence, p)
                    for q in terms
                    if q != p
                    and _share_head_word(p, q)
                    and not _are_related_terms(p, q)
                    and not _contains_word(sentence, q)
                ),
                None,
            )

            if num % 2 == 0 and replacement:
                false_statement = re.sub(
                    rf"(?<!\w){re.escape(replacement[0])}(?!\w)",
                    replacement[1],
                    sentence,
                    count=1,
                    flags=re.IGNORECASE,
                )
                statements.append(f"{num}. {false_statement} (V / F)")
                answers_key.append(f"{num}. Falso: el material dice «{sentence}»")
            else:
                statements.append(f"{num}. {sentence} (V / F)")
                answers_key.append(f"{num}. Verdadero")

            citations.append({"afirmacion": sentence, "fragmentos": [tag]})

        body_content = (
            "Marca verdadero (V) o falso (F) antes de empezar el tema:\n"
            + "\n".join(statements)
            + "\n\nClave para el docente:\n"
            + "\n".join(answers_key)
        )
        return {
            "titulo": f"Sondeo de ideas previas: {context['unidad']['titulo']}",
            "contenido": body_content,
            "citas": citations,
            "alternativas": [],
        }

    def _exploration_guide(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if len(sentence_pairs) < 2 or len(terms) < 2:
            return None
        tag_1, sent_1 = sentence_pairs[(index * 2) % len(sentence_pairs)]
        tag_2, sent_2 = sentence_pairs[(index * 2 + 1) % len(sentence_pairs)]
        term_1, term_2 = terms[index % len(terms)], terms[(index + 1) % len(terms)]

        content = (
            f"Objetivo: explorar {term_1} y su relación con {term_2}.\n\nPasos:\n"
            f"1. Lee este fragmento del material: «{sent_1}»\n"
            f"2. Subraya las palabras clave y escribe con tus palabras qué es {term_1}.\n"
            f"3. Lee este otro fragmento: «{sent_2}»\n"
            f"4. Compara ambos fragmentos: ¿qué tienen en común {term_1} y {term_2}? Anótalo en una tabla.\n"
            "5. Escribe una pregunta que te gustaría investigar sobre el tema.\n\n"
            "Registro: anota tus observaciones y compártelas con tu grupo."
        )
        return {
            "titulo": f"Guía de exploración: {term_1}",
            "contenido": content,
            "citas": [
                {"afirmacion": sent_1, "fragmentos": [tag_1]},
                {"afirmacion": sent_2, "fragmentos": [tag_2]},
            ],
            "alternativas": [],
        }

    def _inquiry_case(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if len(sentence_pairs) < 2 or not terms:
            return None
        tag_1, sent_1 = sentence_pairs[(index * 2) % len(sentence_pairs)]
        tag_2, sent_2 = sentence_pairs[(index * 2 + 1) % len(sentence_pairs)]
        term_1 = terms[index % len(terms)]
        term_2 = terms[(index + 1) % len(terms)] if len(terms) > 1 else term_1

        content = (
            f"Caso: {sent_1} {sent_2}\n\nPreguntas de indagación:\n"
            f"1. ¿Qué papel cumple {term_1} en este caso?\n"
            f"2. ¿Qué pasaría si cambiara {term_2}?\n"
            "3. ¿Qué evidencia del material respalda tu respuesta?\n"
            "4. ¿En qué otra situación de tu entorno ocurre algo parecido?"
        )
        return {
            "titulo": f"Caso para indagar: {term_1}",
            "contenido": content,
            "citas": [
                {"afirmacion": sent_1, "fragmentos": [tag_1]},
                {"afirmacion": sent_2, "fragmentos": [tag_2]},
            ],
            "alternativas": [],
        }

    def _explanation(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        order_index = {pair: n for n, pair in enumerate(sentence_pairs)}
        scored_pairs = sorted(
            sentence_pairs, key=lambda pair: -sum(_contains_word(pair[1], term) for term in terms[:10])
        )
        selected = sorted(
            scored_pairs[index * 4 : index * 4 + 4] or scored_pairs[:4],
            key=lambda item: order_index.get(item, 0),
        )
        if not selected:
            return None

        topic = terms[0] if terms else context["unidad"]["titulo"]
        return {
            "titulo": f"{_capitalize_first(topic)}: explicación del material",
            "contenido": "\n\n".join(sentence for _, sentence in selected),
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
        }

    def _glossary(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        glossary_entries: list[str] = []
        citations: list[dict[str, Any]] = []
        chosen_terms: list[str] = []
        used_sentences: set[str] = set()

        for term in terms[index * 8 :]:
            # Un término contenido en otro ya elegido («TCP» en «Protocolo TCP»), o al revés, no se repite.
            if any(_contains_word(chosen, term) or _contains_word(term, chosen) for chosen in chosen_terms):
                continue
            # Cada oración del material define a un solo término.
            candidates = [
                (tag, sentence)
                for tag, sentence in sentence_pairs
                if _contains_word(sentence, term) and normalize_text(sentence) not in used_sentences
            ]
            matched_definition = next(
                (
                    (tag, sentence)
                    for tag, sentence in candidates
                    if re.search(r"\b(es|son|se define|consiste|significa|permite)\b", sentence, re.IGNORECASE)
                ),
                None,
            ) or next(iter(candidates), None)

            if matched_definition:
                chosen_terms.append(term)
                used_sentences.add(normalize_text(matched_definition[1]))
                glossary_entries.append(f"{_capitalize_first(term)}: {matched_definition[1]}")
                citations.append(
                    {"afirmacion": matched_definition[1], "fragmentos": [matched_definition[0]]}
                )

            if len(glossary_entries) == 8:
                break

        if len(glossary_entries) < 3:
            return None

        return {
            "titulo": f"Glosario: {context['unidad']['titulo']}",
            "contenido": "\n".join(glossary_entries),
            "citas": citations,
            "alternativas": [],
        }

    def _application_exercise(
        self,
        index: int,
        sentence_pairs: list[tuple[str, str]],
        terms: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        matched = self._find_matching_pair(sentence_pairs, terms, index)
        if not matched:
            return None
        tag, sentence, term = matched
        content = (
            f"Idea del material: «{sentence}»\n\n"
            f"Consigna: aplica {term} a una situación nueva de tu entorno (tu institución o comunidad). "
            "Describe la situación, explica paso a paso cómo intervendría y qué resultado esperas.\n\n"
            f"Criterios de logro:\n- Usa correctamente el concepto de {term}.\n"
            "- Justifica cada paso con ideas del material.\n- Presenta una conclusión clara."
        )
        return {
            "titulo": f"Ejercicio de aplicación: {term}",
            "contenido": content,
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]}],
            "alternativas": [],
        }
    # HU-050: situaciones nuevas, fuera del material, donde se aplica lo aprendido (una por caso generado).
    _APPLIED_SETTINGS: tuple[str, ...] = (
        "La institución educativa de tu barrio quiere mejorar un servicio que hoy le da problemas y te pide ayuda. "
        "El equipo directivo necesita una propuesta que puedan entender y poner en marcha esta semana.",
        "Una pequeña empresa de tu ciudad está creciendo y debe decidir cómo organizar su trabajo diario. "
        "La dueña te pide una recomendación justificada antes de invertir.",
        "Una organización de tu comunidad prepara un proyecto para atender a más personas. "
        "Te piden revisar el plan y proponer los cambios necesarios.",
    )

    def _applied_case(self, index, sentence_pairs, terms, context):
        """HU-050: un caso en una situación nueva, con una consigna y de 3 a 4 criterios de logro; cada criterio
        aplica una oración del material, así que siempre pasa la verificación."""
        selected, used = [], set()
        matches = [(tag, sentence, term) for term in terms for tag, sentence in sentence_pairs if _contains_word(sentence, term)]
        for tag, sentence, term in matches[index * 4 :] + matches[: index * 4]:
            if sentence in used or any(term == chosen[2] for chosen in selected):
                continue
            used.add(sentence)
            selected.append((tag, sentence, term))
            if len(selected) == 4:
                break
        if len(selected) < 3:
            return None
        concepts = [term for _, _, term in selected]
        listed = ", ".join(concepts[:-1]) + f" y {concepts[-1]}"
        unit_title = context["unidad"]["titulo"]
        setting = self._APPLIED_SETTINGS[index % len(self._APPLIED_SETTINGS)]
        return {
            "titulo": f"Caso aplicado: {unit_title}",
            "contenido": "Lee la situación, resuelve la consigna y revisa tu solución con los criterios de logro antes "
            "de entregarla.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence, _ in selected],
            "alternativas": [],
            "estructura": {
                "situacion": f"{setting} Para resolverlo necesitas lo que aprendiste sobre {unit_title.lower()}.",
                "consigna": f"Propón una solución para esta situación aplicando {listed}. Explica paso a paso qué "
                "harías y por qué, con tus palabras.",
                "criterios": [
                    {"criterio": f"Aplica {term} según el material: «{_shorten(sentence, 300)}»", "fragmentos": [tag]}
                    for tag, sentence, term in selected
                ],
            },
        }

    # ——— Recursos multimodales e interactivos (respaldo sin IA) ———

    def _audio_trigger(self, index, sentence_pairs, terms, context):
        matched = self._find_matching_pair(sentence_pairs, terms, index)
        if not matched:
            return None
        tag, sentence, term = matched
        script = (
            f"Escucha esta idea del material de la unidad. {sentence} "
            f"Ahora piensa: ¿dónde has visto {term} en tu vida diaria y qué pasaría si no existiera? "
            "Anota tu respuesta en una frase; la compartiremos al empezar la clase."
        )
        return {
            "titulo": f"Para escuchar: {term}",
            "contenido": "Escucha la cápsula y anota tu respuesta antes de empezar el tema.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]}],
            "alternativas": [],
            "estructura": {"guion": script},
        }

    def _podcast_summary(self, index, sentence_pairs, terms, context):
        scored = sorted(sentence_pairs, key=lambda pair: -sum(_contains_word(pair[1], t) for t in terms[:10]))
        selected = scored[index * 4 : index * 4 + 4] or scored[:4]
        if len(selected) < 2:
            return None
        title = context["unidad"]["titulo"]
        key_ideas = ", ".join(terms[:3]) if terms else title
        script = (
            f"Hola. En este resumen repasamos la unidad «{title}». "
            + " ".join(sentence for _, sentence in selected)
            + f" Para cerrar, recuerda estas ideas clave: {key_ideas}. Nos vemos en la próxima clase."
        )
        return {
            "titulo": f"Resumen para escuchar: {title}",
            "contenido": "Escucha el resumen de la unidad y anota una idea que quieras preguntar en clase.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {"guion": script},
        }

    def _illustration(self, index, sentence_pairs, terms, context):
        matched = self._find_matching_pair(sentence_pairs, terms, index)
        if not matched:
            return None
        tag, sentence, term = matched
        return {
            "titulo": f"Imagen para observar: {term}",
            "contenido": (
                f"Observa la imagen y responde: ¿qué elementos se relacionan con {term}? "
                f"Compara lo que ves con esta idea del material: «{sentence}»"
            ),
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]}],
            "alternativas": [],
            "estructura": {
                "descripcion_imagen": (
                    f"Ilustración didáctica, clara y sin texto escrito, que represente esta idea: {sentence} "
                    "Estilo de libro escolar, colores suaves y fondo limpio."
                ),
                "texto_alternativo": f"Ilustración sobre {term}",
                "leyenda": sentence,
            },
        }

    def _process_diagram(self, index, sentence_pairs, terms, context):
        start = (index * 4) % max(1, len(sentence_pairs))
        selected = sentence_pairs[start : start + 5]
        if len(selected) < 3:
            selected = sentence_pairs[:5]
        if len(selected) < 3:
            return None
        steps = [
            {"titulo": _capitalize_first(_term_in(sentence, terms) or f"Paso {n}"), "texto": _shorten(sentence)}
            for n, (_, sentence) in enumerate(selected, start=1)
        ]
        return {
            "titulo": f"Diagrama del proceso: {context['unidad']['titulo']}",
            "contenido": "Recorre el diagrama paso a paso y explica con tus palabras cómo se relaciona cada paso con el siguiente.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {"pasos": steps},
        }

    def _guided_exploration(self, index, sentence_pairs, terms, context):
        """HU-048: de 3 a 4 pasos; cada uno lleva a leer una parte del material y deja una pregunta guía."""
        start = (index * 4) % max(1, len(sentence_pairs))
        selected = sentence_pairs[start : start + 4]
        if len(selected) < 3:
            selected = sentence_pairs[:4]
        if len(selected) < 3:
            return None
        steps = []
        for n, (tag, sentence) in enumerate(selected, start=1):
            term = _term_in(sentence, terms)
            question = (
                f"¿Qué dice el material sobre {term}? Anótalo con tus palabras."
                if term
                else "¿Qué idea principal encuentras en esta parte del material? Anótala con tus palabras."
            )
            steps.append(
                {
                    "titulo": _capitalize_first(term or f"Paso {n}"),
                    "consigna": f"Lee esta parte del material: «{_shorten(sentence, 300)}»",
                    "pregunta": question,
                    "fragmentos": [tag],
                }
            )
        return {
            "titulo": f"Exploración guiada: {context['unidad']['titulo']}",
            "contenido": "Recorre los pasos en orden: lee cada parte del material, responde la pregunta guía y "
            "anota lo que descubriste.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {"pasos_guiados": steps},
        }

    def _kinesthetic_activity(self, index, sentence_pairs, terms, context):
        """HU-024: de 3 a 4 pasos para hacer con el cuerpo en el aula. Cada paso representa una idea del material y
        cita su fragmento; los materiales, el tiempo y el espacio son los de una actividad corta en el aula."""
        start = (index * 4) % max(1, len(sentence_pairs))
        selected = sentence_pairs[start : start + 4]
        if len(selected) < 3:
            selected = sentence_pairs[:4]
        if len(selected) < 3:
            return None
        steps = []
        for n, (tag, sentence) in enumerate(selected, start=1):
            term = _term_in(sentence, terms)
            steps.append(
                {
                    "titulo": f"Estación {n}: {_capitalize_first(term)}" if term else f"Estación {n}",
                    "consigna": "En grupos, representen con el cuerpo o con objetos del aula esta idea del material: "
                    f"«{_shorten(sentence, 300)}»",
                    "pregunta": f"¿Qué observaron al representar {term}?" if term else "¿Qué observaron?",
                    "fragmentos": [tag],
                }
            )
        return {
            "titulo": f"Actividad kinestésica: {context['unidad']['titulo']}",
            "contenido": "Formen grupos y recorran las estaciones en orden: representen cada idea, comenten lo que "
            "observaron y vuelvan a su lugar al terminar.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {
                "pasos_guiados": steps,
                "materiales": ["Tarjetas con las ideas del material", "Plumones", "Cinta adhesiva"],
                "minutos_estimados": 10 + 5 * len(steps),
                "espacio": "Aula con espacio libre para moverse (mesas a un lado)",
            },
        }

    def _prediction_challenge(self, index, sentence_pairs, terms, context):
        """HU-047: de 3 a 4 predicciones. Cada una oculta un término de una oración del material y da a elegir entre
        ese término y otros de la unidad que no aparecen en la oración; al responder se revela la oración."""
        predictions, citations, used = [], [], set()
        matches = [(tag, sentence, term) for term in terms for tag, sentence in sentence_pairs if _contains_word(sentence, term)]
        for tag, sentence, term in matches[index * 4 :] + matches[: index * 4]:
            if sentence in used:
                continue
            others = [
                other
                for other in terms
                if other != term and not _are_related_terms(term, other) and not _contains_word(sentence, other)
            ]
            masked = _mask_target_word(sentence, term)
            if not others or masked == sentence:
                continue
            used.add(sentence)
            n = len(predictions)
            predictions.append(
                {
                    "pregunta": f"¿Qué crees que completa esta idea? «{_shorten(masked, 300)}»",
                    "correcta": _capitalize_first(term),
                    "otra": _capitalize_first(others[n % len(others)]),
                    "extra": _capitalize_first(others[(n + 1) % len(others)]) if len(others) > 1 else "",
                    "revelacion": f"El material dice: «{_shorten(sentence, 300)}»",
                    "fragmentos": [tag],
                }
            )
            citations.append({"afirmacion": sentence, "fragmentos": [tag]})
            if len(predictions) == 4:
                break
        if len(predictions) < 3:
            return None
        return {
            "titulo": f"Reto de predicción: {context['unidad']['titulo']}",
            "contenido": "Antes de empezar la clase, elige lo que crees en cada pregunta. No importa acertar: al "
            "responder verás lo que dice el material y sumarás puntos por cada predicción acertada.",
            "citas": citations,
            "alternativas": [],
            "estructura": {"predicciones": predictions},
        }

    def _concept_map(self, index, sentence_pairs, terms, context):
        found = _definitions(sentence_pairs, terms, index * 6, 6)
        if len(found) < 3:
            return None
        return {
            "titulo": f"Mapa conceptual: {context['unidad']['titulo']}",
            "contenido": "Lee el mapa desde el concepto central y explica cómo se relaciona con cada concepto.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for _, tag, sentence in found],
            "alternativas": [],
            "estructura": {
                "central": context["unidad"]["titulo"],
                "nodos": [{"etiqueta": _capitalize_first(term), "detalle": _shorten(sentence, 140)} for term, _, sentence in found],
            },
        }

    def _infographic(self, index, sentence_pairs, terms, context):
        scored = sorted(sentence_pairs, key=lambda pair: -sum(_contains_word(pair[1], t) for t in terms[:10]))
        selected = scored[index * 4 : index * 4 + 4] or scored[:4]
        if len(selected) < 3:
            return None
        points = [
            {"titulo": _capitalize_first(_term_in(sentence, terms) or f"Idea {n}"), "texto": _shorten(sentence)}
            for n, (_, sentence) in enumerate(selected, start=1)
        ]
        return {
            "titulo": f"Infografía: {context['unidad']['titulo']}",
            "contenido": "Las ideas clave de la unidad en una sola vista, para repasar o proyectar en clase.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {"central": context["unidad"]["titulo"], "puntos": points},
        }

    def _matching_activity(self, index, sentence_pairs, terms, context):
        found = [
            (term, tag, sentence, _mask_target_word(sentence, term))
            for term, tag, sentence in _definitions(sentence_pairs, terms, index * 6, 6)
        ]
        found = [item for item in found if item[3] != item[2]]
        if len(found) < 3:
            return None
        return {
            "titulo": f"Relaciona los conceptos: {context['unidad']['titulo']}",
            "contenido": "Relaciona cada término con la descripción que le corresponde según el material.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for _, tag, sentence, _ in found],
            "alternativas": [],
            "estructura": {"pares": [{"termino": _capitalize_first(term), "definicion": masked} for term, _, _, masked in found]},
        }

    def _ordering_activity(self, index, sentence_pairs, terms, context):
        start = (index * 5) % max(1, len(sentence_pairs))
        selected = sentence_pairs[start : start + 5]
        if len(selected) < 3:
            selected = sentence_pairs[:5]
        if len(selected) < 3:
            return None
        return {
            "titulo": f"Ordena las ideas: {context['unidad']['titulo']}",
            "contenido": "Ordena las ideas en la secuencia en que el material las presenta y explica por qué van en ese orden.",
            "citas": [{"afirmacion": sentence, "fragmentos": [tag]} for tag, sentence in selected],
            "alternativas": [],
            "estructura": {"secuencia": [sentence for _, sentence in selected]},
        }

    def _true_false_activity(self, index, sentence_pairs, terms, context):
        selected = sentence_pairs[index * 5 : index * 5 + 5] or sentence_pairs[:5]
        if len(selected) < 3:
            return None
        statements, citations = [], []
        for num, (tag, sentence) in enumerate(selected, start=1):
            swap = next(
                (
                    (p, q)
                    for p in terms
                    if _contains_word(sentence, p)
                    for q in terms
                    if q != p and not _are_related_terms(p, q) and not _contains_word(sentence, q)
                ),
                None,
            )
            if num % 2 == 0 and swap:
                false_text = _capitalize_first(
                    re.sub(rf"(?<!\w){re.escape(swap[0])}(?!\w)", swap[1], sentence, count=1, flags=re.IGNORECASE)
                )
                statements.append({"texto": false_text, "verdadera": False, "retroalimentacion": f"Falso. El material dice: «{sentence}»"})
            else:
                statements.append({"texto": sentence, "verdadera": True, "retroalimentacion": "Verdadero. Así lo afirma el material."})
            citations.append({"afirmacion": sentence, "fragmentos": [tag]})
        if all(s["verdadera"] for s in statements):
            return None
        return {
            "titulo": f"Verdadero o falso: {context['unidad']['titulo']}",
            "contenido": "Marca si cada afirmación es verdadera o falsa según el material de la unidad.",
            "citas": citations,
            "alternativas": [],
            "estructura": {"afirmaciones": statements},
        }

    def _fill_in_activity(self, index, sentence_pairs, terms, context):
        items, citations, used = [], [], set()
        matches = [(tag, sentence, term) for term in terms for tag, sentence in sentence_pairs if _contains_word(sentence, term)]
        for tag, sentence, term in matches[index * 4 :] + matches[: index * 4]:
            if sentence in used:
                continue
            used.add(sentence)
            items.append({"oracion": _mask_target_word(sentence, term), "respuesta": term})
            citations.append({"afirmacion": sentence, "fragmentos": [tag]})
            if len(items) == 4:
                break
        if len(items) < 2:
            return None
        return {
            "titulo": f"Completa las ideas: {context['unidad']['titulo']}",
            "contenido": "Escribe el término que completa cada oración según el material.",
            "citas": citations,
            "alternativas": [],
            "estructura": {"espacios": items},
        }
