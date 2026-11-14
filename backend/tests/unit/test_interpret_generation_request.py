from unittest.mock import Mock

import pytest

from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext, UnitMembershipPort
from platform5e.application.use_cases.generation.interpret_generation_request import (
    InterpretGenerationCommand,
    InterpretGenerationRequest,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode


@pytest.fixture
def interpreter():
    membership = Mock(spec=UnitMembershipPort)
    membership.get_unit_context.return_value = UnitContext(
        "course-1", "Redes", "", "", "unit-1", 1, "TCP/IP",
        (
            OutcomeRef("outcome-1", "RA1.1", "Comparar TCP y UDP"),
            OutcomeRef("outcome-2", "RA1.2", "Analizar tráfico"),
            OutcomeRef("outcome-3", "RA1.3", "Analizar tráfico"),
        ),
    )
    owned_units = Mock(return_value=[
        {"unitId": "unit-1", "label": "TCP/IP"},
        {"unitId": "unit-2", "label": "UDP"},
    ])
    use_case = InterpretGenerationRequest(membership, owned_units)

    def interpret(message):
        return use_case.execute(InterpretGenerationCommand("teacher-1", "unit-1", message))

    return interpret, membership, owned_units


def test_interprets_the_specification_example(interpreter):
    interpret, membership, owned = interpreter
    assert interpret("Para TCP/IP, quiero dos glosarios") == {
        "draft": {"unitId": "unit-1", "mode": "individual", "resourceTypes": ["glosario"], "quantity": 2},
        "stages": [{"resourceType": "glosario", "stage": "explain"}],
        "issues": [],
    }
    membership.get_unit_context.assert_called_once_with("teacher-1", "unit-1")
    owned.assert_not_called()


def test_orders_types_and_stages_without_duplicates(interpreter):
    result = interpreter[0]("Preguntas de opción múltiple, glosario, pregunta detonante y glosarios")
    assert result["draft"]["resourceTypes"] == ["pregunta_detonante", "glosario", "item_opcion_multiple"]
    assert result["draft"]["mode"] == "sequence"
    assert [item["stage"] for item in result["stages"]] == ["engage", "explain", "evaluate"]
    assert "quantity" not in result["draft"]


def test_unrecognized_message_leaves_mode_and_quantity_omitted(interpreter):
    result = interpreter[0]("Necesito algo para la clase")
    assert result["draft"] == {"unitId": "unit-1", "resourceTypes": []}
    assert result["stages"] == []
    assert result["issues"][0]["kind"] == "missing"


@pytest.mark.parametrize("message", [
    "Algo para enganchar en modalidad Gamificado",
    "Para enganchar, necesito algo en modalidad Gamificado",
])
def test_stage_only_offers_compatible_types_without_selecting_one(interpreter, message):
    result = interpreter[0](message)
    assert len(result["issues"]) == 1
    assert result["draft"]["resourceTypes"] == []
    assert result["issues"][0]["kind"] == "ambiguous"
    assert [option["value"] for option in result["issues"][0]["options"]] == ["reto_prediccion"]


def test_incompatible_type_is_reported_and_excluded(interpreter):
    result = interpreter[0]("Gamificado: glosario y preguntas de opción múltiple")
    assert result["draft"]["resourceTypes"] == ["item_opcion_multiple"]
    assert result["draft"]["modalities"] == ["Gamificado"]
    assert result["draft"]["mode"] == "individual"
    assert result["issues"][0]["kind"] == "not_allowed"


@pytest.mark.parametrize(("message", "kind"), [
    ("dos glosarios y tres mapas conceptuales", "ambiguous"),
    ("6 glosarios", "not_allowed"),
    ("once glosarios", "not_allowed"),
    ("-1 glosarios", "not_allowed"),
    ("2,5 glosarios", "not_allowed"),
])
def test_conflicting_or_out_of_range_quantities_are_issues(interpreter, message, kind):
    result = interpreter[0](message)
    assert "quantity" not in result["draft"]
    assert any(issue["field"] == "quantity" and issue["kind"] == kind for issue in result["issues"])


def test_sequence_limit_does_not_silently_drop_types(interpreter):
    result = interpreter[0](
        "Glosario, mapa conceptual, infografía, diagrama de proceso, explicación del tema, "
        "reto de predicción, caso aplicado, exploración guiada y pregunta detonante"
    )
    assert result["draft"]["resourceTypes"] == []
    assert "mode" not in result["draft"]
    assert len(result["issues"][0]["options"]) == 9


def test_resolves_outcome_and_preserves_explicit_context_text(interpreter):
    result = interpreter[0](
        "2 glosarios para RA1.1; Audiencia: Tercer ciclo; Competencia: Comparar TCP y UDP; "
        "Instrucciones: No agregar mapas conceptuales"
    )
    assert result["draft"] == {
        "unitId": "unit-1", "resourceTypes": ["glosario"], "mode": "individual", "quantity": 2,
        "outcomeId": "outcome-1", "audience": "Tercer ciclo", "competency": "Comparar TCP y UDP",
        "instructions": "No agregar mapas conceptuales",
    }


def test_ambiguous_outcome_returns_options_and_preserves_form(interpreter):
    result = interpreter[0]("Glosario; resultado: Analizar tráfico")
    assert "outcomeId" not in result["draft"]
    issue = result["issues"][0]
    assert issue["kind"] == "ambiguous"
    assert [option["value"] for option in issue["options"]] == ["outcome-2", "outcome-3"]


@pytest.mark.parametrize("message", ["Un glosario sin resultado de aprendizaje", "Glosario; resultado: Ninguno"])
def test_explicit_removal_returns_null(interpreter, message):
    result = interpreter[0](message)
    assert "outcomeId" in result["draft"]
    assert result["draft"]["outcomeId"] is None


def test_text_field_limit_leaves_existing_value_available(interpreter):
    result = interpreter[0]("Glosario; Audiencia: " + "x" * 201)
    assert "audience" not in result["draft"]
    assert result["issues"][0]["kind"] == "not_allowed"


@pytest.mark.parametrize("message", [
    "Para UDP, quiero un glosario",
    "Quiero un glosario para la unidad «UDP»",
])
def test_suggests_owned_unit_without_changing_the_draft(interpreter, message):
    interpret, _, owned = interpreter
    result = interpret(message)
    assert result["draft"]["unitId"] == "unit-1"
    assert result["suggestedUnit"] == {"unitId": "unit-2", "label": "UDP"}
    owned.assert_called_once_with("teacher-1")


def test_unknown_unit_and_ambiguous_unit_return_the_same_generic_issue(interpreter):
    interpret, _, owned = interpreter
    owned.return_value.append({"unitId": "unit-3", "label": "UDP"})
    unknown = interpret("Para Unidad ajena, quiero un glosario")
    ambiguous = interpret("Para UDP, quiero un glosario")
    assert ambiguous == unknown
    assert "suggestedUnit" not in unknown
    assert unknown["issues"][0]["field"] == "unitId"


def test_checks_active_unit_before_looking_up_suggestions(interpreter):
    interpret, membership, owned = interpreter
    membership.get_unit_context.return_value = None
    with pytest.raises(GenerationError) as error:
        interpret("Para UDP, quiero un glosario")
    assert error.value.code == GenerationErrorCode.UNIT_NOT_FOUND
    owned.assert_not_called()
