"""
Recuperación de evidencia: busca los fragmentos del material más relacionados con la solicitud.

Usa BM25, la búsqueda por palabras clásica de los motores de búsqueda: premia los fragmentos que
contienen las palabras de la consulta, sobre todo las poco frecuentes en el material.
La búsqueda por significado con vectores (pgvector, EN-013 y HU-011) la complementará.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

# Palabras vacías (stopwords) en español e inglés
STOPWORDS: frozenset[str] = frozenset(
    """
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales
cuando de del desde donde dos e el ella ellas ellos en entre era eran es esa esas ese eso esos esta
estaba estado estan estar estas este esto estos fue fueron ha hace hacen hacer han hasta hay la las le
les lo los mas me mi mientras muy ni no nos nosotros o otra otras otro otros para pero poco por porque
puede pueden que quien se sea segun ser si sido sin sino sobre son su sus tambien tan tanto te tiene
tienen todo todos tu un una uno unos usted y ya cuyo cuya donde mediante tras durante bien solo
the of and to in is for on with as by an be this that are from or it at
""".split()
)

_SUFFIXES: tuple[str, ...] = (
    "aciones",
    "iciones",
    "ciones",
    "acion",
    "icion",
    "cion",
    "mente",
    "idades",
    "idad",
    "es",
    "s",
)


def normalize_text(text: str) -> str:
    """Minúsculas y sin tildes, para comparar «información» con «informacion»."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def stem_word(word: str) -> str:
    """Raíz aproximada: «protocolos» y «protocolo» cuentan como la misma palabra."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def extract_terms(text: str) -> list[str]:
    """Palabras útiles de un texto (sin vacías ni muy cortas), normalizadas y reducidas a su raíz."""
    return [
        stem_word(word)
        for word in re.findall(r"[a-z0-9ñ]+", normalize_text(text))
        if len(word) >= 3 and word not in STOPWORDS
    ]


def score_bm25(
    query_terms: list[str],
    document_terms_list: list[list[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Calcula el puntaje BM25 de cada documento (lista de términos) frente a los términos de la consulta."""
    if not document_terms_list:
        return []
    total_docs = len(document_terms_list)
    avg_doc_len = sum(len(doc) for doc in document_terms_list) / total_docs or 1.0
    doc_freq = Counter(term for doc in document_terms_list for term in set(doc))
    unique_query_terms = set(query_terms)
    idf = {
        term: math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
        for term in unique_query_terms
    }
    scores: list[float] = []
    for doc in document_terms_list:
        term_freq = Counter(doc)
        doc_len = len(doc) or 1
        scores.append(
            sum(
                idf[term] * term_freq[term] * (k1 + 1) / (term_freq[term] + k1 * (1 - b + b * doc_len / avg_doc_len))
                for term in unique_query_terms
                if term_freq[term]
            )
        )
    return scores


def retrieve_relevant_chunks(query: str, chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Devuelve hasta `top_k` fragmentos ordenados por relevancia, cada uno con 'relevance' entre 0 y 1.

    Si ninguna palabra coincide, devuelve los primeros `top_k` del material: siguen siendo evidencia
    del docente, pero con relevancia 0 para notar que no hubo coincidencias exactas.
    """
    if not chunks or top_k <= 0:
        return []

    # Compatibilidad con llaves en inglés ('text') o español ('texto')
    docs_text = [chunk.get("text") or chunk.get("texto", "") for chunk in chunks]
    scores = score_bm25(extract_terms(query), [extract_terms(text) for text in docs_text])
    max_score = max(scores, default=0.0)

    if max_score <= 0:
        return [{**chunk, "relevance": 0.0, "relevancia": 0.0} for chunk in chunks[:top_k]]

    ranked = sorted((pair for pair in zip(scores, chunks) if pair[0] > 0), key=lambda pair: -pair[0])[:top_k]
    return [
        {**chunk, "relevance": round(score / max_score, 3), "relevancia": round(score / max_score, 3)}
        for score, chunk in ranked
    ]


def extract_key_terms(texts: list[str], count: int = 12) -> list[str]:
    """Palabras más representativas del material, en su forma original más usada."""
    term_counts: Counter[str] = Counter()
    surface_forms: dict[str, Counter[str]] = defaultdict(Counter)
    for text in texts:
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text):
            normalized = normalize_text(word)
            if len(normalized) < 5 or normalized in STOPWORDS:
                continue
            stem = stem_word(normalized)
            term_counts[stem] += 1
            surface_forms[stem][word.lower()] += 1
    return [surface_forms[stem].most_common(1)[0][0] for stem, _ in term_counts.most_common(count)]
