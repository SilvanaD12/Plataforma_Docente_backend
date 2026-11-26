"""
QA-05: comprobación de que la evidencia recuperada trata el tema que pidió el docente, antes de redactar.

La búsqueda siempre devuelve los fragmentos más parecidos de la unidad, aunque ninguno trate el tema: en T068 (caso
C-06), una pregunta sobre «tablas y llaves primarias en un modelo relacional» recuperó «tablas de enrutamiento» de una
unidad de redes, y se entregó un recurso citado sobre la capa de red. La relevancia de BM25 o de la fusión híbrida no
sirve para detectarlo, porque se normaliza y el primer fragmento siempre vale 1,0.

Las medidas son absolutas y no usan IA. El tema son las indicaciones del docente, sin palabras vacías ni palabras de
estilo, de tipo de recurso o de formulación de la pregunta («diferencia», «términos clave»). Sin indicaciones no hay
nada que comprobar: el resultado de aprendizaje siempre es de la unidad.

- Cobertura: qué parte de los términos del tema aparece en los fragmentos recuperados (igualdad sin tildes, con el
  singular y el plural).
- Frases del tema: dos términos seguidos, o unidos por «de», «del», «de la»…, como «protocolo de transporte» o «llaves
  primarias». Una frase aparece si los dos términos están seguidos (o con esos conectores) en un fragmento.

Se rechaza solo si la cobertura no llega al umbral y además no aparece ninguna frase del tema: las palabras de un
escenario («una empresa que transmite en vivo») no están en el material aunque el tema sí, y una palabra suelta puede
coincidir con otro sentido («tablas» de enrutamiento). Medición y umbral en specs/005-atributos-calidad/plan.md (QA-05).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Umbral por defecto (fracción de términos del tema presentes en la evidencia) y mínimo de términos para comprobar.
DEFAULT_COVERAGE_THRESHOLD: float = 0.5
MIN_TOPIC_TERMS: int = 2

# Palabras vacías del español (artículos, preposiciones, pronombres, conjunciones, interrogativos y verbos comunes).
_STOPWORDS = frozenset(
    """
    a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada cerca como con contra cual cuales
    cualquier cuando cuanta cuantas cuanto cuantos de del desde donde dos durante e el ella ellas ello ellos en entre
    era eran es esa esas ese eso esos esta estan estar estas este esto estos fue fueron ha han hace hacen hacer hasta
    hay la las le les lo los mas me menos mi mis mucho muchos muy ni no nos o otra otras otro otros para pero poco por
    porque puede pueden que quien quienes se sea sean segun ser si sin sino sobre son su sus tal tambien tan tanto te
    tiene tienen todo todos tras tu tus u un una uno unos usted ustedes y ya yo cuyo cuya entonces mismo misma
    existe existen
    """.split()
)
# Palabras de estilo, de pedagogía y de tipo de recurso: piden una forma, no un tema.
_STYLE_WORDS = frozenset(
    """
    actividad actividades alternativa alternativas alumno alumnos aplicacion aprendizaje basico basica breve breves
    caso casos clase clara claro claros concreto concretos corta cortas corto cotidiano cotidianos detonante
    diagnostico dificultad distractor distractores docente ejemplo ejemplos ejercicio ejercicios enfoque estudiante
    estudiantes exploracion explica explicacion explicar explique explore facil glosario guia idea ideas indagacion
    intermedia intermedio item lenguaje nivel opcion opciones parrafo parrafos pregunta preguntas previas recurso
    recursos respuesta respuestas sencilla sencillo simple sondeo tema temas texto usa usar usando incluye incluir
    agrega largo larga avanzado avanzada multiple
    """.split()
)
# Palabras con que se formula una pregunta sobre cualquier tema: no dicen de qué tema se trata.
_FRAMING_WORDS = frozenset(
    """
    caracteristica caracteristicas clave claves concepto conceptos conforma conforman conviene decidir diferencia
    diferencias elegir elige estructuran funcion funciones importancia principal principales sirve sirven termino
    terminos utiliza utilizan utilizar
    """.split()
)
_IGNORED = _STOPWORDS | _STYLE_WORDS | _FRAMING_WORDS
# Conectores que pueden unir los dos términos de una frase del tema («protocolo de transporte»).
_CONNECTORS = frozenset({"de", "del", "la", "las", "el", "los"})
_MAX_CONNECTORS = 2
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")


def normalize(text: str) -> str:
    """Minúsculas y sin tildes («Relación» → «relacion»)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def concept_key(text: str) -> str:
    """GEN-P1: forma comparable de un concepto del plan, con la misma normalización: minúsculas, sin tildes, sin
    espacios repetidos ni palabras vacías («Control  de Flújo» → «control flujo»). Si solo tiene palabras vacías, se
    conservan."""
    words = _WORD.findall(normalize(text or ""))
    meaningful = [word for word in words if word not in _STOPWORDS]
    return " ".join(meaningful or words)


def _is_term(word: str) -> bool:
    """Palabra del tema: 3 o más letras, o una sigla de 2 en mayúsculas (IP), que no sea vacía, de estilo ni de
    formulación."""
    key = normalize(word)
    if key in _IGNORED or key.isdigit():
        return False
    return len(key) >= 3 or (len(word) == 2 and word.isupper())


def is_topic_term(word: str) -> bool:
    """T027 (b): la misma regla de término, para la extracción de conceptos del plan."""
    return _is_term(word)


@dataclass(frozen=True)
class TopicPhrase:
    """Dos términos del tema seguidos, o unidos por conectores, tal como los escribió el docente."""

    first: str
    second: str
    text: str


def _phrases(words: Sequence[str]) -> list[TopicPhrase]:
    phrases: list[TopicPhrase] = []
    for start, word in enumerate(words):
        if not _is_term(word):
            continue
        for offset in range(1, _MAX_CONNECTORS + 2):
            end = start + offset
            if end >= len(words):
                break
            if _is_term(words[end]):
                phrase = TopicPhrase(normalize(word), normalize(words[end]), " ".join(words[start:end + 1]).lower())
                if phrase.text not in {p.text for p in phrases}:
                    phrases.append(phrase)
                break
            if normalize(words[end]) not in _CONNECTORS:
                break
    return phrases


def topic_terms(instructions: str) -> list[str]:
    """Términos del tema de las indicaciones, normalizados, sin repetir y en orden."""
    terms: list[str] = []
    for word in _WORD.findall(instructions or ""):
        if _is_term(word) and normalize(word) not in terms:
            terms.append(normalize(word))
    return terms


def topic_phrases(instructions: str) -> list[TopicPhrase]:
    """Frases del tema: dos términos seguidos o unidos por «de», «del», «de la»…"""
    return _phrases(_WORD.findall(instructions or ""))


def _variants(term: str) -> set[str]:
    """El término y su singular o plural regular: «capa» y «capas», «red» y «redes»."""
    variants = {term, term + "s", term + "es"}
    if term.endswith("es") and len(term) > 4:
        variants.add(term[:-2])
    if term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    return variants


def _phrase_in(phrase: TopicPhrase, tokens: Sequence[str]) -> bool:
    first, second = _variants(phrase.first), _variants(phrase.second)
    for index, token in enumerate(tokens):
        if token not in first:
            continue
        for offset in range(1, _MAX_CONNECTORS + 2):
            if index + offset >= len(tokens):
                break
            following = tokens[index + offset]
            if following in second:
                return True
            if following not in _CONNECTORS:
                break
    return False


@dataclass(frozen=True)
class TopicCoverage:
    """Términos y frases del tema, cuáles aparecen en la evidencia y si alcanza para redactar."""

    terms: tuple[str, ...]
    found: tuple[str, ...]
    phrases: tuple[TopicPhrase, ...]
    found_phrases: tuple[TopicPhrase, ...]
    threshold: float
    # Cada término como lo escribió el docente (con tildes), para nombrarlo en el motivo.
    labels: tuple[tuple[str, str], ...] = ()

    @property
    def checked(self) -> bool:
        """False si las indicaciones tienen menos de `MIN_TOPIC_TERMS` términos, o si la comprobación está apagada
        (umbral 0): no hay tema que comprobar."""
        return self.threshold > 0 and len(self.terms) >= MIN_TOPIC_TERMS

    @property
    def coverage(self) -> float:
        return len(self.found) / len(self.terms) if self.terms else 1.0

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(term for term in self.terms if term not in self.found)

    @property
    def accepted(self) -> bool:
        return not self.checked or self.coverage >= self.threshold or bool(self.found_phrases)

    def missing_topic(self) -> list[str]:
        """Lo que falta, como lo escribió el docente: primero las frases que no aparecen y después los términos
        sueltos que no están en ninguna de ellas («llaves primarias, modelo relacional»)."""
        missing_phrases = [phrase for phrase in self.phrases if phrase not in self.found_phrases]
        in_phrases = {term for phrase in missing_phrases for term in (phrase.first, phrase.second)}
        named = [phrase.text for phrase in missing_phrases if phrase.first in self.missing or phrase.second in self.missing]
        labels = dict(self.labels)
        return named + [labels.get(term, term) for term in self.missing if term not in in_phrases]


def assess_topic_coverage(
    instructions: str, fragment_texts: Iterable[str], threshold: float = DEFAULT_COVERAGE_THRESHOLD
) -> TopicCoverage:
    """Qué parte del tema de las indicaciones aparece en los fragmentos recuperados."""
    fragments = [_WORD.findall(normalize(text)) for text in fragment_texts]
    vocabulary = {token for tokens in fragments for token in tokens}
    terms = topic_terms(instructions)
    phrases = topic_phrases(instructions)
    found = tuple(term for term in terms if _variants(term) & vocabulary)
    found_phrases = tuple(phrase for phrase in phrases if any(_phrase_in(phrase, tokens) for tokens in fragments))
    labels: dict[str, str] = {}
    for word in _WORD.findall(instructions or ""):
        labels.setdefault(normalize(word), word if word.isupper() else word.lower())
    return TopicCoverage(
        tuple(terms), found, tuple(phrases), found_phrases, threshold, tuple((t, labels.get(t, t)) for t in terms)
    )
