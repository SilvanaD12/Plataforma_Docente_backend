"""
T027 (b), spec 006 (research R4): conceptos candidatos del material, como frases nominales con sentido.

Antes, las frases salían de la lista de palabras de cada fragmento sin mirar los signos, así que se pegaban términos de
una lista o de dos oraciones («puerto de destino, longitud» → «destino longitud»; «FTP, SFTP» → «ftp sftp»), entraban
los encabezados de página («Ingeniería de redes  Página 1» → «redes página») y pedazos de oración («udp proporciona»).
Ahora:

- **Segmentos.** El texto se corta en signos de puntuación, paréntesis, barras, viñetas, guiones con espacios, saltos
  de línea y «Página N»; una frase nunca cruza un corte.
- **Encabezados.** Un segmento que está entre los primeros de dos o más fragmentos es un encabezado o un título de
  página («Ingeniería de redes») y no da conceptos.
- **Frases.** Una corrida de 2 a 4 términos seguidos, unidos a lo sumo por «de», «del» o un artículo («control de
  congestión», «bloqueo de cabeza de línea», «Transmission Control Protocol»). Una corrida más larga da sus pares.
  No entran verbos, adverbios ni palabras genéricas.
- **Siglas.** Una sigla («TCP», «UDP», «RTT», «IMAP») corta la corrida y es su propio concepto si aparece al menos dos
  veces.

La usan el planificador por reglas y la medición de P4 (`candidate_concepts`), así los dos ven los mismos conceptos.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from platform5e.domain.generation.outcome_alignment import split_outcome
from platform5e.domain.generation.topic_coverage import is_topic_term, normalize

# Cortes de segmento: signos, paréntesis, barras, viñetas, comillas, guiones con espacios, saltos y «Página N».
_BREAK = re.compile(
    r"[.,;:!?¿¡()\[\]{}•·|/\\\"«»“”\n\r\t]|\s[-–—]\s|\bp[aá]gina\s*\d+\b|\bpage\s*\d+\b", re.IGNORECASE
)
_TOKEN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+(?:-[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+)*")
_ACRONYM = re.compile(r"[A-Z]{2,6}(?:v\d)?\d?")
_CONNECTORS = frozenset({"de", "del", "la", "las", "el", "los"})
MAX_CONNECTORS = 2
MAX_PHRASE_TERMS = 4
MIN_ACRONYM_COUNT = 2
HEADER_POSITIONS = 3
MIN_HEADER_TEXTS = 2
# Palabras que no nombran un concepto: de página, genéricas, verbos y adverbios frecuentes en el material.
_NOT_CONCEPT = frozenset(
    """
    pagina paginas page figura tabla capitulo seccion fuente licencia wikipedia nota notas
    conjunto debido diferente diferentes general generales manera mediante mismo mismos parte partes primer primera
    segundo segunda siguiente siguientes traves ultimo ultima cualquier ejemplo forma formas final finales tambien
    debe deben debera deberan puede pueden podra podran tiene tienen tendra tendran hace hacen hara haran siempre
    nunca capaz capaces permite permiten existe existen solo sola solamente apenas proporciona proporcionan ofrece
    ofrecen contiene contienen anade anaden trabaja trabajan garantiza garantizan establece establecen envia envian
    recibe reciben incluye incluyen opera operan usa usan utiliza utilizan indica indican identifica identifican
    llamado llamada denominado denominada conocido conocida trae traen afecta afectan
    enviado enviada enviados enviadas recibido recibida recibidos recibidas transmitido transmitida usado usada
    utilizado utilizada
    """.split()
)
# Números escritos: «saludo de tres vías» toma la palabra que sigue al número.
_NUMBER_WORDS = frozenset("dos tres cuatro cinco seis siete ocho nueve diez".split())
_VERB_ENDING = re.compile(r"(ar|er|ir|rse|ran|ria|rian|aba|aban|ian)$")


def _is_word(token: str) -> bool:
    """Un término que puede formar un concepto. La terminación de verbo no se aplica a las palabras con mayúscula
    («User Datagram Protocol»)."""
    key = normalize(token)
    verb_like = _VERB_ENDING.search(key) and not token[:1].isupper()
    return is_topic_term(token) and key not in _NOT_CONCEPT and not verb_like


# Un título o encabezado: una línea corta que no termina como una oración («Unidad 1: Protocolos de transporte»).
MAX_HEADING_WORDS = 8
_SENTENCE_END = re.compile(r"[.!?…:;»”\")]\s*$")


def without_headings(text: str) -> str:
    """El texto sin sus líneas de título: no dan conceptos, porque ninguna oración los desarrolla."""
    lines = (text or "").split("\n")
    kept = [line for line in lines
            if not (line.strip() and len(line.split()) <= MAX_HEADING_WORDS and not _SENTENCE_END.search(line))]
    return "\n".join(kept)


def segments(text: str) -> list[str]:
    return [part.strip() for part in _BREAK.split(text or "") if part and part.strip()]


def header_segments(texts: Sequence[str]) -> set[str]:
    """Los segmentos que están entre los primeros de dos o más fragmentos: encabezados y títulos de página."""
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update({normalize(part) for part in segments(text)[:HEADER_POSITIONS]})
    return {segment for segment, count in counts.items() if count >= MIN_HEADER_TEXTS}


def _term_positions(tokens: list[str]) -> list[list[int]]:
    """Las corridas de términos del segmento: posiciones de términos separados solo por conectores. Una sigla o una
    palabra que no es término ni conector corta la corrida."""
    runs: list[list[int]] = [[]]
    for index, token in enumerate(tokens):
        if _ACRONYM.fullmatch(token) or not (_is_word(token) or normalize(token) in _CONNECTORS):
            runs.append([])
        elif normalize(token) not in _CONNECTORS:
            runs[-1].append(index)
    return [run for run in runs if len(run) >= 2]


def _joined_by_de(tokens: list[str], left: int, right: int) -> bool:
    """Entre dos términos hay «de» o «del», con o sin artículo («de la»): forma un término compuesto. Un artículo
    solo («cabecera trae el puerto») une un verbo con su objeto, no un concepto."""
    between = [normalize(token) for token in tokens[left + 1:right]]
    return 1 <= len(between) <= MAX_CONNECTORS and between[0] in ("de", "del")


def _is_name(token: str) -> bool:
    return token[:1].isupper()


def concept_phrases(text: str, headers: set[str] | None = None) -> list[str]:
    """Las frases con sentido de un texto, en minúsculas y en orden, sin las de sus encabezados:
    - términos unidos por «de» o «del» (2 a 4 términos): «puerto de destino», «bloqueo de cabeza de línea»;
    - dos términos seguidos: «entrega best-effort», «comunicación confiable»;
    - un nombre propio de 2 a 4 palabras con mayúscula: «Transmission Control Protocol»."""
    phrases: list[str] = []
    headers = {normalize(header) for header in headers or ()}

    def add(tokens: list[str], start: int, end: int) -> None:
        phrase = " ".join(tokens[start:end + 1]).lower()
        if phrase not in phrases:
            phrases.append(phrase)

    for segment in segments(without_headings(text)):
        if headers and normalize(segment) in headers:
            continue
        tokens = _TOKEN.findall(segment)
        # Un sustantivo seguido de una sigla en el mismo segmento: «modelo OSI», «protocolo TCP». Nunca dos siglas
        # («FTP, SFTP») ni una sigla seguida de otra palabra («HTTPS. Versiones» ya está cortado).
        for index in range(1, len(tokens)):
            if _ACRONYM.fullmatch(tokens[index]) and _is_word(tokens[index - 1]) and not _ACRONYM.fullmatch(
                    tokens[index - 1]):
                add(tokens, index - 1, index)
        for run in _term_positions(tokens):
            n = 0
            while n < len(run) - 1:
                left, right = run[n], run[n + 1]
                last = n
                if left > 0 and normalize(tokens[left - 1]) == "se":
                    n += 1  # «se encarga del direccionamiento»: un verbo, no un concepto
                    continue
                if _joined_by_de(tokens, left, right):
                    last = n + 1
                    while last + 1 < len(run) and last - n + 1 < MAX_PHRASE_TERMS and _joined_by_de(
                            tokens, run[last], run[last + 1]):
                        last += 1
                    # «saludo de tres vías»: si la cadena termina en un número, toma la palabra que lo sigue.
                    if (last + 1 < len(run) and last - n + 1 < MAX_PHRASE_TERMS and run[last + 1] == run[last] + 1
                            and normalize(tokens[run[last]]) in _NUMBER_WORDS):
                        last += 1
                elif right == left + 1:
                    last = n + 1
                    if _is_name(tokens[left]) and _is_name(tokens[right]):
                        while (last + 1 < len(run) and last - n + 1 < MAX_PHRASE_TERMS
                               and run[last + 1] == run[last] + 1 and _is_name(tokens[run[last + 1]])):
                            last += 1
                if last > n:
                    add(tokens, run[n], run[last])
                    # La frase siguiente empieza después de esta: sin sus pedazos («control protocol» dentro de
                    # «Transmission Control Protocol») ni frases que empiecen en su último término («confiable de los
                    # datos» después de «entrega confiable»).
                    n = last + 1
                else:
                    n += 1
    return phrases


def acronym_counts(texts: Iterable[str], headers: set[str] | None = None) -> Counter[str]:
    """Cuántas veces aparece cada sigla fuera de los encabezados."""
    counts: Counter[str] = Counter()
    for text in texts:
        for segment in segments(text):
            if headers and normalize(segment) in headers:
                continue
            counts.update(token for token in _TOKEN.findall(segment) if _ACRONYM.fullmatch(token))
    return counts


def phrase_groups(instructions: str, texts: Sequence[str]) -> tuple[list[list[str]], list[str]]:
    """Los grupos de candidatos en orden de preferencia y, aparte, los de último recurso.

    Preferidos: frases del tema, frases del material que se repiten, siglas que aparecen dos veces o más y términos de
    varias palabras unidos por «de» que aparecen una vez. De último recurso (solo si los preferidos no alcanzan para el
    plan, con poco material): las demás frases y siglas que aparecen una vez («bloques desordenados» no entra con el
    corpus de T067, donde alcanzan los preferidos)."""
    headers = header_segments(texts)
    topic = concept_phrases(instructions)
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(set(concept_phrases(text, headers)))
    by_frequency = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    repeated = [phrase for phrase, count in by_frequency if count > 1]
    joined = [phrase for phrase, count in by_frequency
              if count == 1 and any(word in ("de", "del") for word in normalize(phrase).split())]
    once = [phrase for phrase, count in by_frequency if count == 1 and phrase not in joined]
    acronyms = acronym_counts(texts, headers)
    frequent = [acronym for acronym, count in acronyms.items() if count >= MIN_ACRONYM_COUNT]
    single = [acronym for acronym, count in acronyms.items() if count < MIN_ACRONYM_COUNT]
    return [topic, repeated, frequent, joined], once + single


def outcome_concepts(outcome_text: str) -> list[str]:
    """T029 (spec 006) y GEN-C14 (spec 002, research R14): las frases y siglas del resultado de aprendizaje elegido, sin
    su código ni su verbo («RA1.1: Reconoce las capas del modelo OSI» → «modelo osi», «capas del modelo»). Una sigla
    entra sola si ninguna frase del resultado la contiene («Distingue TCP y UDP» → «TCP», «UDP»)."""
    _, body = split_outcome(outcome_text)
    # Con punto final: una línea corta sin punto es un título para `without_headings` y no daría frases.
    phrases = concept_phrases(f"{body}." if body else "")
    acronyms = [token for token in _TOKEN.findall(body) if _ACRONYM.fullmatch(token)
                and not any(normalize(token) in normalize(phrase).split() for phrase in phrases)]
    return list(dict.fromkeys([*phrases, *acronyms]))


def evidence_concepts_from(instructions: str, texts: Sequence[str], limit: int) -> list[str]:
    """Los conceptos candidatos que usa el planificador por reglas (ver `plan_drafting.candidate_concepts`)."""
    from platform5e.application.services.generation.plan_drafting import candidate_concepts

    return candidate_concepts(instructions, texts, limit)
