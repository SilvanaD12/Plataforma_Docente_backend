"""REV-P3 · Pruebas unitarias de detección de duplicidad (REV-R15)."""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.domain.review.duplication import (
    SPANISH_STOPWORDS,
    find_duplicates,
    normalize,
    question_texts,
    resource_text,
    similarity,
)


def test_normalize_removes_accents_punctuation_and_stopwords():
    raw = "¡El protocolo TCP, en la capa de transporte, es el más confiable!"
    normalized = normalize(raw)
    assert "el" not in normalized.split()
    assert "la" not in normalized.split()
    assert "es" not in normalized.split()
    assert "tcp" in normalized
    assert "transporte" in normalized
    assert "confiable" in normalized
    assert "," not in normalized
    assert "!" not in normalized


def test_normalize_empty_and_none_returns_empty_string():
    assert normalize("") == ""
    assert normalize("   ") == ""
    assert normalize(None) == ""
    assert normalize("el la de y en") == ""


def test_similarity_identical_texts_return_one():
    text = "Los protocolos principales de la capa de transporte son TCP y UDP."
    assert similarity(text, text) == 1.0
    # Equivalente con diferente puntuación y mayúsculas
    text_variant = "¡LOS PROTOCOLOS PRINCIPALES DE LA CAPA DE TRANSPORTE SON TCP Y UDP!"
    assert similarity(text, text_variant) == 1.0


def test_similarity_empty_or_none_returns_zero():
    assert similarity("", "Algún texto") == 0.0
    assert similarity("Algún texto", "") == 0.0
    assert similarity(None, "Algún texto") == 0.0
    assert similarity(None, None) == 0.0
    assert similarity("", "") == 0.0


def test_similarity_network_example_pair_exceeds_threshold():
    pair_a = "Los dos protocolos principales de la capa de transporte en Internet son TCP y UDP."
    pair_b = "En la capa de transporte de Internet los dos protocolos principales son TCP y UDP."
    score = similarity(pair_a, pair_b)
    assert score >= 0.70, f"Expected similarity >= 0.70, got {score}"


def test_similarity_professor_example_exact_match():
    # B5: Ejemplo exacto del profesor (con tildes y signos)
    pair_a = "¿Cómo se gestionan los paquetes de redes?"
    pair_b = "¿Cómo se gestionaría los paquetes en una red?"
    score = similarity(pair_a, pair_b)
    assert score >= 0.70, f"Professor example failed threshold ({score})"
    assert score == 1.0, f"Expected 1.0 due to lightweight stemming, got {score}"


def test_similarity_fixed_cases_above_and_below_threshold():
    # B5: Casos fijos que DEBEN marcarse (score >= 0.70)
    udp_a = "El protocolo UDP no ofrece garantías sobre la entrega o el orden de los paquetes."
    udp_b = "UDP no ofrece garantías para la entrega o el orden de los paquetes en la red."
    assert similarity(udp_a, udp_b) >= 0.70

    # B5: Casos fijos que NO deben marcarse (score < 0.70)
    lifo = "Una pila es una estructura LIFO donde el último elemento en entrar es el primero en salir."
    fifo = "Una cola es una estructura FIFO donde el primer elemento en entrar es el primero en salir."
    assert similarity(lifo, fifo) < 0.70

    osi_routing = "¿Qué capa del modelo OSI enruta los paquetes?"
    osi_encrypt = "¿Qué capa del modelo OSI cifra los datos?"
    assert similarity(osi_routing, osi_encrypt) < 0.70

    assert similarity("¿Qué es una pila?", "¿Qué es una cola?") < 0.70


@pytest.mark.parametrize(
    ("text_a", "text_b"),
    [
        (
            "Los protocolos de la capa de transporte en Internet son TCP y UDP.",
            "En Internet, los dos protocolos principales de la capa de transporte son TCP y UDP.",
        ),
        (
            "Una pila es una estructura de datos lineal que sigue el principio LIFO.",
            "La pila es una estructura lineal de datos que sigue el principio LIFO.",
        ),
        (
            "El algoritmo de Dijkstra encuentra la ruta mas corta entre los nodos de un grafo.",
            "El algoritmo de Dijkstra halla la ruta mas corta entre los nodos de un grafo.",
        ),
        (
            "La memoria cache disminuye el tiempo de acceso a los datos de la memoria principal.",
            "El uso de memoria cache reduce el tiempo de acceso a los datos de la memoria principal.",
        ),
        (
            "El protocolo UDP no ofrece garantías sobre la entrega o el orden de los paquetes.",
            "UDP no ofrece garantías para la entrega o el orden de los paquetes en la red.",
        ),
    ],
)
def test_similarity_paraphrased_pairs_reach_threshold(text_a: str, text_b: str):
    score = similarity(text_a, text_b)
    assert score >= 0.70, f"Paraphrase pair failed threshold ({score}): '{text_a}' vs '{text_b}'"


@pytest.mark.parametrize(
    ("text_a", "text_b"),
    [
        (
            "La fotosintesis es el proceso mediante el cual las plantas convierten la luz solar en energia quimica.",
            "El algoritmo de Dijkstra calcula el camino mas corto entre dos nodos de un grafo ponderado.",
        ),
        (
            "El modelo cliente servidor distribuye las tareas entre los proveedores de recursos y los demandantes.",
            "La mitosis es un tipo de division celular en el que una celula madre produce dos celulas hijas identicas.",
        ),
        (
            "Los arreglos unidimensionales almacenan elementos contiguos del mismo tipo de datos en memoria.",
            "La revolucion industrial transformo radicalmente las estructuras economicas y sociales en Europa.",
        ),
        (
            "El cifrado asimetrico utiliza un par de claves publica y privada para proteger la informacion.",
            "El ciclo hidrologico describe el movimiento continuo del agua dentro de la atmosfera terrestre.",
        ),
        (
            "Una cola de prioridad atiende a los elementos de acuerdo con el nivel de prioridad asignado.",
            "La teoria de la relatividad general describe la gravedad como una curvatura del espacio tiempo.",
        ),
    ],
)
def test_similarity_distinct_pairs_stay_below_threshold(text_a: str, text_b: str):
    score = similarity(text_a, text_b)
    assert score < 0.50, f"Distinct pair exceeded threshold ({score}): '{text_a}' vs '{text_b}'"


def test_resource_text_extracts_nested_structure_and_options():
    resource: dict[str, Any] = {
        "title": "Actividad de ordenamiento",
        "body": "Ordena la secuencia siguiente.",
        "structure": {
            "steps": ["Paso uno: inicializar", "Paso dos: iterar"],
            "metadata": {"hint": "Comienza por el caso base"},
        },
        "options": [
            {"text": "Opcion 1", "feedback": "Retroalimentacion 1"},
            {"text": "Opcion 2", "feedback": "Retroalimentacion 2"},
        ],
    }
    extracted = resource_text(resource)
    assert "Actividad de ordenamiento" in extracted
    assert "Ordena la secuencia siguiente" in extracted
    assert "Paso uno: inicializar" in extracted
    assert "Paso dos: iterar" in extracted
    assert "Comienza por el caso base" in extracted
    assert "Opcion 1" in extracted
    assert "Retroalimentacion 2" in extracted


def test_resource_text_with_unknown_resource_type_does_not_fail():
    unknown_resource = {
        "type": "tipo_futuro_desconocido",
        "custom_field": "Contenido no estándar",
        "structure": {"nested": {"deep": [123, None, "Dato anidado"]}},
    }
    extracted = resource_text(unknown_resource)
    assert "Dato anidado" in extracted


def test_question_texts_extracts_from_item_and_structure():
    item_resource: dict[str, Any] = {
        "id": "rec-1",
        "type": "item_opcion_multiple",
        "body": "¿Cual es el puerto por defecto de HTTP?",
        "structure": None,
    }
    questions = question_texts(item_resource)
    assert questions == ["¿Cual es el puerto por defecto de HTTP?"]

    activity_resource: dict[str, Any] = {
        "id": "rec-2",
        "type": "cuestionario_diagnostico",
        "body": "Instrucciones generales",
        "structure": {
            "questions": [
                {"statement": "¿Que protocolo es no orientado a conexion?"},
                {"statement": "¿Cual es la funcion del protocolo ARP?"},
            ]
        },
    }
    questions_act = question_texts(activity_resource)
    assert len(questions_act) == 2
    assert "¿Que protocolo es no orientado a conexion?" in questions_act
    assert "¿Cual es la funcion del protocolo ARP?" in questions_act


def test_find_duplicates_detects_resource_and_question_duplication():
    res1: dict[str, Any] = {
        "id": "res-1",
        "type": "explicacion",
        "title": "Protocolos TCP y UDP",
        "body": "Los protocolos principales de la capa de transporte en Internet son TCP y UDP.",
    }
    res2: dict[str, Any] = {
        "id": "res-2",
        "type": "explicacion",
        "title": "Protocolos de transporte",
        "body": "En la capa de transporte de Internet los dos protocolos principales son TCP y UDP.",
    }
    res3: dict[str, Any] = {
        "id": "res-3",
        "type": "explicacion",
        "title": "Fotosintesis vegetal",
        "body": "La fotosintesis es el proceso mediante el cual las plantas convierten la luz solar en energia.",
    }

    report = find_duplicates([res1, res2, res3], threshold=0.70)
    assert report["threshold"] == 0.70
    assert report["comparedPairs"] == 3  # 3 * 2 // 2 = 3
    assert len(report["flaggedPairs"]) == 1

    flagged = report["flaggedPairs"][0]
    assert flagged["resourceIdA"] == "res-1"
    assert flagged["resourceIdB"] == "res-2"
    assert flagged["scope"] == "resource"
    assert flagged["score"] >= 0.70
    assert report["duplicatePairRate"] == round(1 / 3, 3)


def test_find_duplicates_deduplicates_same_resource_pair_keeping_highest_score():
    # B5: Evita contar dos veces el mismo hallazgo entre el mismo par de recursos
    res_a = {
        "id": "rec-a",
        "type": "item_opcion_multiple",
        "title": "Pregunta de redes TCP",
        "body": "¿Cómo se gestionan los paquetes de redes?",
    }
    res_b = {
        "id": "rec-b",
        "type": "item_opcion_multiple",
        "title": "Pregunta de redes TCP variante",
        "body": "¿Cómo se gestionaría los paquetes en una red?",
    }
    report = find_duplicates([res_a, res_b], threshold=0.70)
    # Coincidencia tanto a nivel resource como question: deja solo uno (el de mayor puntaje)
    assert len(report["flaggedPairs"]) == 1
    flagged = report["flaggedPairs"][0]
    assert {flagged["resourceIdA"], flagged["resourceIdB"]} == {"rec-a", "rec-b"}
    assert flagged["score"] >= 0.70
