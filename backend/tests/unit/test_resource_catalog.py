"""El contrato público y los exportadores usan el mismo catálogo del dominio."""
import json
from collections import Counter
from pathlib import Path
from typing import get_args

from platform5e.application.use_cases.catalog.list_resource_types import ListResourceTypesUseCase
from platform5e.domain.generation.resource_catalog import CUR_P2_TEXT_TYPES, RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import RESOURCE_CATALOG, resource_format, resource_stage
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter
from platform5e.infrastructure.http.schemas.catalog import ResourceTypeResponse
from platform5e.infrastructure.http.schemas.generations import ResourceType


def test_catalog_matches_generation_validation_and_export_metadata():
    assert len(RESOURCE_TYPES) == 50
    assert len({entry.id for entry in RESOURCE_TYPES}) == len(RESOURCE_TYPES)
    assert set(RESOURCE_CATALOG) == set(get_args(ResourceType))
    assert {entry.stage for entry in RESOURCE_TYPES} == {"engage", "explore", "explain", "elaborate", "evaluate"}
    for entry in RESOURCE_TYPES:
        assert resource_stage(entry.id) == entry.stage
        assert resource_format(entry.id) == entry.format
        assert entry.has_options == (entry.id == "item_opcion_multiple")


def test_public_labels_preserve_the_published_contract():
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures/resource_catalog.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    response = [ResourceTypeResponse.model_validate(entry).model_dump(mode="json", by_alias=True)
                for entry in ListResourceTypesUseCase().execute()]
    assert response[:len(expected)] == expected
    added = response[len(expected):]
    assert [item["id"] for item in added] == list(CUR_P2_TEXT_TYPES)
    assert all(item["format"] == "text" and item["modalities"] == ["Textual"] for item in added)
    assert set(Counter(item["stage"] for item in response).values()) == {10}


def test_new_types_carry_drafting_metadata_to_generation():
    by_id = {item.id: item for item in StaticResourceCatalogAdapter().entries()}
    assert len(CUR_P2_TEXT_TYPES) == 28
    for type_id, metadata in CUR_P2_TEXT_TYPES.items():
        entry = by_id[type_id]
        assert entry.description == metadata["description"]
        assert entry.verification == metadata["verification"]
        assert entry.length_hint is not None
        assert entry.length_hint.to_payload() == metadata["lengthHint"]


def test_catalog_queries_do_not_share_mutable_response_data():
    use_case = ListResourceTypesUseCase()
    first = use_case.execute()
    first[0]["name"] = "Modificado"
    assert use_case.execute()[0]["name"] == "Pregunta detonante"
