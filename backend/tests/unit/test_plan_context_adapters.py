"""GEN-P1 (T004): adaptadores provisionales de los puertos del plan (catálogo, referentes y tipologías)."""

from __future__ import annotations

from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import MODALITY_TYPES
from platform5e.infrastructure.adapters.plan_context_adapters import NoReferentsAdapter, NoSessionTypologyAdapter
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter


def test_the_catalog_adapter_lists_every_current_type_with_its_stage_description_and_modalities():
    entries = {entry.id: entry for entry in StaticResourceCatalogAdapter().entries()}
    assert list(entries) == [entry.id for entry in RESOURCE_TYPES]
    for definition in RESOURCE_TYPES:
        entry = entries[definition.id]
        assert (entry.name, entry.stage, entry.format, entry.active) == (
            definition.name, definition.stage, definition.format, True)
        assert entry.description and "5E" not in entry.description
        assert set(entry.modalities) == {m for m, types in MODALITY_TYPES.items() if definition.id in types}


def test_until_material_and_courses_deliver_them_there_are_no_referents_or_previous_sessions():
    assert list(NoReferentsAdapter().referents_for("docente-a", "u1", "TCP", ())) == []
    typologies = NoSessionTypologyAdapter()
    assert list(typologies.previous_typologies("docente-a", "u1")) == []
    assert typologies.record_typology("docente-a", "u1", "gen-plan-1", ["explicacion"], "2026-11-22T10:00:00Z") is None
