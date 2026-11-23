"""Servicio de aplicación para extraer, guardar y entregar referentes de la unidad (MAT-P2)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from platform5e.application.ports.outbound.referent_extractor_port import ReferentExtractorPort
from platform5e.application.ports.outbound.referent_repository_port import ReferentRepositoryPort
from platform5e.application.ports.outbound.referents_port import ReferentsPort
from platform5e.domain.generation.generation_plan import PlanFragment, Referent

logger = logging.getLogger("platform5e.referents")


class ReferentService(ReferentsPort):
    """Coordina la persistencia de referentes y satisface `ReferentsPort` para `GEN-P1`."""

    def __init__(
        self,
        repository: ReferentRepositoryPort,
        extractor: ReferentExtractorPort | None = None,
    ) -> None:
        self._repository = repository
        self._extractor = extractor

    def extract_and_store_for_unit(
        self,
        teacher_id: str,
        unit_id: str,
        topic: str,
        fragments: Sequence[PlanFragment],
        document_id: str | None = None,
    ) -> list[Referent]:
        if self._extractor is None or not fragments:
            return []
        try:
            extracted = self._extractor.extract_referents(topic=topic, fragments=fragments)
        except Exception as exc:
            logger.warning("No se pudieron persistir referentes para unidad %s: %s", unit_id, exc.__class__.__name__)
            return []

        self._repository.replace_unit_referents(
            teacher_id=teacher_id,
            unit_id=unit_id,
            referents=extracted,
            document_id=document_id,
        )
        return list(extracted)

    def referents_for(
        self,
        teacher_id: str,
        unit_id: str,
        topic: str,
        fragments: Sequence[PlanFragment],
    ) -> Sequence[Referent]:
        stored = self._repository.get_unit_referents(teacher_id=teacher_id, unit_id=unit_id)
        if stored:
            return tuple(stored)
        if self._extractor is not None and fragments:
            return tuple(self._extractor.extract_referents(topic=topic, fragments=fragments))
        return ()