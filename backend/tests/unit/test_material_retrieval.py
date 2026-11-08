"""
Pruebas unitarias de las reglas puras de fragmentación y recuperación BM25.
"""

from __future__ import annotations

from platform5e.domain.materials.chunking import (
    MaterialError,
    clean_text,
    chunk_pages,
    extract_paragraphs,
    extract_sentences,
)
from platform5e.domain.materials.text_analysis import (
    extract_key_terms,
    normalize_text,
    retrieve_relevant_chunks,
    score_bm25,
    stem_word,
    extract_terms,
)

SAMPLE_TEXT = (
    "Unidad 2: Protocolos de red\n\n"
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable. "
    "El protocolo UDP no establece conexión y por eso es más rápido.\n\n"
    "El enrutador es el dispositivo que decide el camino de cada paquete."
)


def test_clean_text_joins_split_words_and_spaces():
    assert clean_text("comuni-\ncación   de datos\r\n\n\n\nfin") == "comunicación de datos\n\nfin"
    assert clean_text(None) == ""


def test_paragraphs_split_short_pdf_headings():
    pdf_sample = (
        "Unidad 2: Protocolos\nEl protocolo TCP es orientado a la conexión y garantiza una entrega con\nfiabilidad en la red."
    )
    extracted = extract_paragraphs(pdf_sample)
    assert extracted[0] == "Unidad 2: Protocolos"
    assert extracted[1].startswith("El protocolo TCP")


def test_sentences_respect_headings_and_periods():
    sentences_list = extract_sentences(SAMPLE_TEXT)
    assert sentences_list[0] == "Unidad 2: Protocolos de red"
    assert sentences_list[1].startswith("El protocolo TCP") and sentences_list[2].startswith("El protocolo UDP")


def test_chunking_keeps_location_order_and_paragraphs():
    chunks = chunk_pages([("p. 1", SAMPLE_TEXT), ("p. 2", "   "), ("p. 3", "Solo un título")])
    assert [c.get("location") or c.get("ubicacion") for c in chunks] == ["p. 1"]
    assert (chunks[0].get("order") if "order" in chunks[0] else chunks[0]["orden"]) == 0
    assert "\n\n" in (chunks[0].get("text") or chunks[0]["texto"])


def test_chunking_splits_long_texts_with_short_overlap():
    sentence = "La capa de red mueve los paquetes entre redes distintas. "
    chunks = chunk_pages([("sección 1", sentence * 60)], target_words=50)
    assert len(chunks) > 5
    assert all(len((c.get("text") or c.get("texto", "")).split()) <= 60 for c in chunks)
    assert (chunks[1].get("text") or chunks[1]["texto"]).startswith("La capa de red")


def test_chunking_a_sentence_longer_than_a_chunk():
    long_sentence = " ".join(f"palabra{i}" for i in range(130)) + "."
    chunks = chunk_pages([("p. 1", long_sentence)], target_words=50)
    assert len(chunks) == 3


def test_material_error_carries_code_and_status():
    error = MaterialError("X", "mensaje", 404)
    assert (error.code, error.message, error.status_code, str(error)) == ("X", "mensaje", 404, "mensaje")


def test_terms_normalize_drop_stopwords_and_stem():
    assert normalize_text("Información") == "informacion"
    assert stem_word("protocolos") == stem_word("protocolo")
    assert extract_terms("Los protocolos de la red") == [stem_word("protocolos"), "red"]


def test_bm25_rewards_rare_matches():
    docs = [
        extract_terms("el protocolo TCP confiable"),
        extract_terms("el protocolo UDP rapido"),
        extract_terms("el enrutador decide"),
    ]
    scores = score_bm25(extract_terms("TCP confiable"), docs)
    assert scores[0] > 0 and scores[1] == 0 and scores[2] == 0
    assert score_bm25(["x"], []) == []


def test_retrieval_sorts_by_relevance_and_has_fallback():
    chunks = [
        {"id": "a", "texto": "El enrutador decide el camino"},
        {"id": "b", "texto": "TCP garantiza la entrega confiable de TCP"},
        {"id": "c", "texto": "UDP es rápido"},
    ]
    selected = retrieve_relevant_chunks("entrega confiable TCP", chunks, 2)
    assert [c["id"] for c in selected] == ["b"]
    assert (selected[0].get("relevance") or selected[0].get("relevancia")) == 1.0

    fallback = retrieve_relevant_chunks("astronomía", chunks, 2)
    assert [c["id"] for c in fallback] == ["a", "b"]
    assert (fallback[0].get("relevance") or fallback[0].get("relevancia")) == 0.0

    assert retrieve_relevant_chunks("TCP", [], 3) == []
    assert retrieve_relevant_chunks("TCP", chunks, 0) == []


def test_key_terms_returns_frequent_forms():
    key_terms = extract_key_terms(
        ["El protocolo TCP y el protocolo UDP son protocolos de transporte."], 3
    )
    assert key_terms[0] == "protocolo"