"""
Material del docente: limpieza del texto y fragmentación (primer paso del RAG).

Reglas puras, sin dependencias externas. Un fragmento (chunk) es un trozo corto del material
(unas 220 palabras) que conserva su ubicación (página, diapositiva o sección) para que
cada recurso generado pueda citar de dónde sale cada afirmación.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from platform5e.domain.shared.errors import DomainError

# Parámetros y constantes de fragmentación
WORDS_PER_CHUNK: int = 220  # ~300 tokens: cabe en los modelos de embeddings de SP-001 (máx. 512).
MAX_OVERLAP: int = 40       # La última oración se repite al inicio del siguiente fragmento si es corta.
MAX_CHUNKS: int = 3000      # Tope por documento (un libro de ~400 páginas da unos 800).

_CONTROL_CHARS: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENTENCE_END: re.Pattern[str] = re.compile(r'(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9«"“(])')


class MaterialError(DomainError):
    """Error de negocio de la ingesta de material. Lleva código, mensaje para el docente y estado HTTP."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code: str = code
        self.message: str = message
        self.status_code: int = status_code
        super().__init__(message)


def clean_text(text: str | None) -> str:
    """Normaliza espacios y saltos de línea, y une las palabras cortadas con guion al final de línea."""
    normalized_text = unicodedata.normalize("NFC", text or "")
    normalized_text = _CONTROL_CHARS.sub(" ", normalized_text).replace("\r\n", "\n").replace("\r", "\n")
    normalized_text = re.sub(r"(\w)-\n(\w)", r"\1\2", normalized_text)
    normalized_text = re.sub(r"[ \t ]+", " ", normalized_text)
    normalized_text = re.sub(r" *\n *", "\n", normalized_text)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    return normalized_text.strip()


def extract_paragraphs(text: str) -> list[str]:
    """Párrafos del texto. Une las líneas cortadas por el ancho de página (típico del PDF), pero

    separa los títulos: una línea corta, sin punto final, seguida de otra que empieza con mayúscula.
    """
    result: list[str] = []
    for block in re.split(r"\n\s*\n", clean_text(text)):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        max_width = max(len(line) for line in lines)
        current: list[str] = []
        for i, line in enumerate(lines):
            current.append(line)
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            is_title = (
                len(lines) > 1
                and len(line) < 0.6 * max_width
                and not re.search(r"[.!?…:;,]$", line)
                and re.match(r'[A-ZÁÉÍÓÚÑ¿¡0-9«"“(]', next_line or "a") is not None
            )
            if is_title:
                result.append(" ".join(current))
                current = []
        if current:
            result.append(" ".join(current))
    return result


def extract_sentences(text: str) -> list[str]:
    """Divide un texto en oraciones, respetando párrafos y títulos."""
    return [
        sentence.strip()
        for paragraph in extract_paragraphs(text)
        for sentence in _SENTENCE_END.split(paragraph)
        if sentence.strip()
    ]


def _split_long_sentence(sentence: str, max_words: int) -> list[str]:
    """Una oración más larga que un fragmento se parte por cantidad de palabras."""
    words = sentence.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _join_chunk_parts(parts: list[tuple[str, int]]) -> str:
    """Une las partes de un fragmento separando párrafos distintos con salto de línea doble."""
    joined_text = ""
    for i, (part, paragraph_index) in enumerate(parts):
        if i:
            joined_text += "\n\n" if paragraph_index != parts[i - 1][1] else " "
        joined_text += part
    return joined_text


def chunk_pages(pages: list[tuple[str, str]], target_words: int | None = None) -> list[dict[str, Any]]:
    """Divide las páginas en fragmentos de texto respetando oraciones y párrafos."""
    chunk_size = target_words or WORDS_PER_CHUNK
    words_per_chunk_effective = chunk_size
    max_overlap = MAX_OVERLAP

    raw_chunks: list[dict[str, Any]] = []
    for location, text in pages:
        parts = [
            (sub_sentence, paragraph_idx)
            for paragraph_idx, paragraph in enumerate(extract_paragraphs(text))
            for raw_sentence in _SENTENCE_END.split(paragraph)
            if raw_sentence.strip()
            for sub_sentence in _split_long_sentence(raw_sentence.strip(), words_per_chunk_effective)
        ]
        if sum(len(part_text.split()) for part_text, _ in parts) < 5:
            continue

        current: list[tuple[str, int]] = []
        new_parts_count = 0
        for part in parts:
            part_len = len(part[0].split())
            if current and sum(len(existing_part[0].split()) for existing_part in current) + part_len > words_per_chunk_effective:
                raw_chunks.append({"location": location, "text": _join_chunk_parts(current)})
                last_part = current[-1]
                current = [last_part] if len(last_part[0].split()) <= max_overlap else []
                new_parts_count = 0
            current.append(part)
            new_parts_count += 1

        if current and new_parts_count:
            raw_chunks.append({"location": location, "text": _join_chunk_parts(current)})

    result: list[dict[str, Any]] = []
    for index, chunk in enumerate(raw_chunks[:MAX_CHUNKS]):
        result.append({
            "order": index,
            "location": chunk["location"],
            "text": chunk["text"],
            "order": index,
            "ubicacion": chunk["location"],
            "texto": chunk["text"],
        })
    return result
