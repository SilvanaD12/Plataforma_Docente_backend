"""REV-P3 · Pruebas unitarias de detección de duplicidad (REV-R15)."""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.review.duplication import (
    SPANISH_STOPWORDS,
    find_cross_unit_duplicates,
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


def test_find_cross_unit_duplicates_flags_identical_pair_across_units():
    current = [
        {
            "id": "u1-res-1",
            "type": "explicacion",
            "title": "Protocolo TCP",
            "body": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
        }
    ]
    others = [
        (
            "u2",
            "Unidad 2: Transporte avanzado",
            {
                "id": "u2-res-1",
                "type": "explicacion",
                "title": "Protocolo TCP",
                "body": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
            },
        )
    ]

    report = find_cross_unit_duplicates(current, others, threshold=0.70)
    assert report["threshold"] == 0.70
    assert report["comparedPairs"] == 1
    assert report["duplicatePairRate"] == 1.0
    assert len(report["flaggedPairs"]) == 1

    pair = report["flaggedPairs"][0]
    assert pair["resourceIdA"] == "u1-res-1"
    assert pair["resourceIdB"] == "u2-res-1"
    assert pair["unitIdB"] == "u2"
    assert pair["unitTitleB"] == "Unidad 2: Transporte avanzado"
    assert pair["crossUnit"] is True
    assert pair["scope"] == "resource"
    assert pair["score"] == 1.0


def test_find_cross_unit_duplicates_does_not_flag_distinct_resources():
    current = [
        {
            "id": "u1-res-1",
            "type": "explicacion",
            "title": "Fotosíntesis",
            "body": "La fotosíntesis convierte la luz solar en energía química en las plantas.",
        }
    ]
    others = [
        (
            "u2",
            "Unidad 2: Algoritmos",
            {
                "id": "u2-res-1",
                "type": "explicacion",
                "title": "Algoritmo de Dijkstra",
                "body": "El algoritmo de Dijkstra calcula la ruta más corta en un grafo ponderado.",
            },
        )
    ]

    report = find_cross_unit_duplicates(current, others, threshold=0.70)
    assert report["comparedPairs"] == 1
    assert report["flaggedPairs"] == []
    assert report["duplicatePairRate"] == 0.0


def test_find_cross_unit_duplicates_does_not_compare_other_units_with_each_other():
    current = [
        {
            "id": "u1-res-1",
            "type": "explicacion",
            "title": "Revolución Industrial",
            "body": "La revolución industrial transformó la economía y la producción manufacturera.",
        }
    ]
    # u2 y u3 tienen recursos idénticos entre sí, pero distintos al de u1.
    others = [
        (
            "u2",
            "Unidad 2",
            {
                "id": "u2-res-1",
                "type": "explicacion",
                "title": "Protocolo UDP",
                "body": "UDP envía datagramas sin establecer conexión previa ni confirmar entrega.",
            },
        ),
        (
            "u3",
            "Unidad 3",
            {
                "id": "u3-res-1",
                "type": "explicacion",
                "title": "Protocolo UDP",
                "body": "UDP envía datagramas sin establecer conexión previa ni confirmar entrega.",
            },
        ),
    ]

    report = find_cross_unit_duplicates(current, others, threshold=0.70)
    assert report["comparedPairs"] == 2  # Solo u1 vs u2 y u1 vs u3; nunca u2 vs u3
    assert report["flaggedPairs"] == []
    assert report["duplicatePairRate"] == 0.0


def test_find_cross_unit_duplicates_deduplicates_resource_and_question_keeping_highest_score():
    current = [
        {
            "id": "u1-q1",
            "type": "item_opcion_multiple",
            "title": "Evaluación de protocolos de red en capa de transporte",
            "body": "¿Cómo se gestionan los paquetes de redes?",
            "options": [
                {"text": "Mediante conmutación", "feedback": "Correcto."},
                {"text": "Mediante difusión amplia", "feedback": "Incorrecto."},
            ],
        }
    ]
    others = [
        (
            "u2",
            "Unidad 2",
            {
                "id": "u2-q1",
                "type": "item_opcion_multiple",
                "title": "Cuestionario de arquitectura alternativa en sistemas distribuidos",
                "body": "¿Cómo se gestionaría los paquetes en una red?",
                "options": [
                    {"text": "Con nodos intermedios", "feedback": "Válido en ciertos contextos."},
                    {"text": "Con canales dedicados", "feedback": "Descartado."},
                ],
            },
        )
    ]

    report = find_cross_unit_duplicates(current, others, threshold=0.70)
    # Pregunta coincide con score=1.0; además compara 1 par de recurso + 1 par de pregunta = 2
    assert report["comparedPairs"] == 2
    assert len(report["flaggedPairs"]) == 1
    flagged = report["flaggedPairs"][0]
    assert flagged["resourceIdA"] == "u1-q1"
    assert flagged["resourceIdB"] == "u2-q1"
    assert flagged["scope"] == "question"
    assert flagged["score"] == 1.0
    assert flagged["crossUnit"] is True
    assert flagged["unitIdB"] == "u2"
    assert flagged["unitTitleB"] == "Unidad 2"


def test_service_cross_unit_duplication_report_behaves_additively():
    class StubTeachers:
        def __init__(self) -> None:
            self.courses = {
                "teacher-1": [
                    {
                        "id": "course-1",
                        "units": [
                            {"id": "u1", "title": "Unidad 1: Transporte"},
                            {"id": "u2", "title": "Unidad 2: Enrutamiento"},
                        ],
                    }
                ]
            }

        def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
            return self.courses.get(teacher_id, [])

    class StubReviews:
        def __init__(self) -> None:
            self.by_unit: dict[str, list[dict[str, Any]]] = {
                "u1": [
                    {
                        "id": "r1a",
                        "unitId": "u1",
                        "type": "explicacion",
                        "title": "Protocolo TCP",
                        "body": "El protocolo TCP es orientado a la conexión y garantiza entrega confiable.",
                    },
                    {
                        "id": "r1b",
                        "unitId": "u1",
                        "type": "explicacion",
                        "title": "Protocolo TCP variante",
                        "body": "El protocolo TCP es orientado a la conexión y garantiza entrega confiable.",
                    },
                    {
                        "id": "r1c",
                        "unitId": "u1",
                        "type": "explicacion",
                        "title": "Fotosíntesis",
                        "body": "La fotosíntesis convierte la luz solar en energía química.",
                    },
                ],
                "u2": [
                    {
                        "id": "r2a",
                        "unitId": "u2",
                        "type": "explicacion",
                        "title": "TCP repetido",
                        "body": "El protocolo TCP es orientado a la conexión y garantiza entrega confiable.",
                    }
                ],
            }

        def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
            return self.by_unit.get(unit_id, []) if teacher_id == "teacher-1" else []

    service = ResourceReviewService(StubTeachers(), StubReviews())  # type: ignore[arg-type]

    within_only = service.get_duplication_report("teacher-1", "u1", threshold=0.70, include_course=False)
    assert within_only["comparedPairs"] == 3
    assert len(within_only["flaggedPairs"]) == 1
    assert "crossUnit" not in within_only["flaggedPairs"][0]

    with_course = service.get_duplication_report("teacher-1", "u1", threshold=0.70, include_course=True)
    assert with_course["comparedPairs"] == 6  # 3 pares en u1 + 3*1 pares entre u1 y u2
    assert len(with_course["flaggedPairs"]) == 3  # (r1a, r1b), (r1a, r2a), (r1b, r2a)
    assert with_course["duplicatePairRate"] == round(3 / 6, 3)

    same_unit_pairs = [p for p in with_course["flaggedPairs"] if not p["crossUnit"]]
    cross_unit_pairs = [p for p in with_course["flaggedPairs"] if p["crossUnit"]]
    assert len(same_unit_pairs) == 1
    assert same_unit_pairs[0]["unitIdB"] is None
    assert same_unit_pairs[0]["unitTitleB"] is None
    assert len(cross_unit_pairs) == 2
    assert all(p["unitIdB"] == "u2" and p["unitTitleB"] == "Unidad 2: Enrutamiento" for p in cross_unit_pairs)

    with pytest.raises(AccountConfigurationError) as err:
        service.get_duplication_report("other-teacher", "u1", include_course=True)
    assert err.value.status_code == 404
    assert err.value.code == "UNIT_NOT_FOUND"
