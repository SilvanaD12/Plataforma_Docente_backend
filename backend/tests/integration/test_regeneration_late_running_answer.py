"""PR #17 sobre el #18 de REV-01: una respuesta tardía `running` del mismo intento no reabre un intento fallido.

Orden que pidió Silvana, con el mismo `attemptId`:
1. Una consulta de estado guarda `failed` y libera la reserva.
2. Después llega, para ese mismo intento, una respuesta tardía de otra consulta con `running`.
3. Debe quedar `failed` (sin volver a `running` ni retomar la reserva), y el docente puede pedir la regeneración otra
   vez desde la misma versión: Generación crea el intento `-r2`.

Usa los repositorios reales de Cuentas, Revisión y Generación sobre un SQLite temporal, el adaptador real de Generación
(T029) y un adaptador de prueba que lo envuelve para controlar el orden de las respuestas.
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import URL, create_engine, select
from sqlalchemy.orm import sessionmaker

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationRequest
from platform5e.application.use_cases.generation.start_regeneration import StartRegeneration
from platform5e.domain.generation.generation_request import Problem, RequestStatus
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter
from platform5e.infrastructure.adapters.generation_regeneration_adapter import GenerationRegenerationAdapter
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_generation_repository as generations,
    sqlalchemy_resource_repository as resources,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from tests.integration.test_regeneration_concurrency import TEACHER, explanation
from tests.support.generation_fakes import FakeEvidence, FakeRunner
from tests.unit.test_sequence_orchestrator import StageAwareGenerator

FAILURE = Problem("INSUFFICIENT_EVIDENCE", "La regeneración no citó el material.")


class LateRunningAnswer:
    """Envuelve el adaptador real de Generación. La primera consulta de estado se queda esperando y, cuando la prueba
    la suelta, responde `running` para el pedido consultado (una respuesta tardía). Las demás van al adaptador real."""

    def __init__(self, real: GenerationRegenerationAdapter) -> None:
        self._real = real
        self._lock = threading.Lock()
        self._queries = 0
        self.late_query_waiting = threading.Event()
        self.release_late_query = threading.Event()

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        return self._real.request_regeneration(teacher_id, resource_id, resource_version, params)

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        with self._lock:
            self._queries += 1
            late = self._queries == 1
        if late:
            self.late_query_waiting.set()
            assert self.release_late_query.wait(10), "la prueba no soltó la respuesta tardía"
            return RegenerationStatus(request_id, "running")
        return self._real.get_regeneration(teacher_id, request_id)


def test_a_late_running_answer_keeps_failed_and_the_same_version_can_be_regenerated_again(
    tmp_path, monkeypatch, request
):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "tardia-running.db")), connect_args={"check_same_thread": False}
    )
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
    course = AccountService(account_repository, "", "").save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Transporte"}]}
    )
    unit_id = course["units"][0]["id"]
    review_repository = resources.SQLAlchemyResourceRepository()
    review_repository.save_resources(TEACHER, unit_id, [explanation("viejo", unit_id)])

    # Generación real (pedidos en SQLite); el ejecutor falso no corre nada hasta que la prueba lo pide.
    generation_requests = SQLAlchemyGenerationRequestRepository(engine)
    membership = AccountUnitMembershipAdapter(account_repository)
    evidence = FakeEvidence()
    real_adapter = GenerationRegenerationAdapter(
        StartRegeneration(StartGenerationRequest(membership, evidence, generation_requests, FakeRunner())),
        GetGenerationRequest(generation_requests, membership, review_repository),
        wait_seconds=0,
    )
    generation = LateRunningAnswer(real_adapter)
    service = ResourceReviewService(account_repository, review_repository, generation)
    service.list_resources(TEACHER, unit_id)  # la primera lectura verifica el recurso antiguo (D7)
    version = review_repository.get_resource_by_id(TEACHER, "viejo")["version"]

    def stored() -> tuple[dict[str, Any], int | None, str | None]:
        """El registro de regeneración, la reserva (`regeneration_claim`) y el intento (`regeneration_attempt`)."""
        with sessions() as session:
            row = session.execute(
                select(resources.TeacherResourceORM.regeneration_claim, resources.TeacherResourceORM.regeneration_attempt)
                .where(resources.TeacherResourceORM.id == "viejo")
            ).one()
        return review_repository.get_resource_by_id(TEACHER, "viejo")["regeneration"], row[0], row[1]

    # Primer intento: queda en curso y Generación lo registra con la clave base.
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    first, claim, attempt = stored()
    first_attempt, first_request = first["attemptId"], first["requestId"]
    assert (claim, attempt) == (version, first_attempt)
    assert generation_requests.get(TEACHER, first_request).idempotency_key == f"regen-viejo-v{version}"
    generation_requests.finish(first_request, RequestStatus.FAILED, FAILURE)  # el pedido falla en Generación

    # Una consulta lenta pregunta primero y se queda esperando la respuesta de Generación.
    late_result: list[dict[str, Any]] = []
    slow = threading.Thread(
        target=lambda: late_result.append(service.get_regeneration_status(TEACHER, unit_id, "viejo"))
    )
    slow.start()
    assert generation.late_query_waiting.wait(10)

    # 1. Otra consulta ve el fallo: guarda `failed` y libera la reserva.
    failed = service.get_regeneration_status(TEACHER, unit_id, "viejo")
    assert failed["status"] == "failed" and failed["code"] == "INSUFFICIENT_EVIDENCE"
    record, claim, attempt = stored()
    assert record["status"] == "failed" and record["attemptId"] == first_attempt
    assert claim is None and attempt == first_attempt

    # 2. Llega tarde la respuesta `running` de la consulta lenta, para el mismo intento.
    generation.release_late_query.set()
    slow.join(timeout=10)
    assert not slow.is_alive()

    # 3. Sigue `failed`, sin retomar la reserva ni cambiar el recurso; la consulta tardía devuelve lo guardado.
    record, claim, attempt = stored()
    assert record["status"] == "failed" and record["attemptId"] == first_attempt
    assert record["reason"] == FAILURE.message and record["requestId"] == first_request
    assert claim is None and attempt == first_attempt
    assert late_result[0]["status"] == "failed"
    old = review_repository.get_resource_by_id(TEACHER, "viejo")
    assert old["status"] == "pendiente" and old["version"] == version

    # 4. El docente lo pide otra vez desde la misma versión: intento nuevo en Revisión y `-r2` en Generación.
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    second, claim, attempt = stored()
    assert second["attemptId"] != first_attempt and second["requestId"] != first_request
    assert (claim, attempt) == (version, second["attemptId"])
    retry = generation_requests.get(TEACHER, second["requestId"])
    assert retry.idempotency_key == f"regen-viejo-v{version}-r2" and retry.status == RequestStatus.QUEUED

    # El segundo intento termina bien y descarta el anterior.
    RunGenerationRequest(
        generation_requests, membership, evidence, review_repository, ReviewVerificationAdapter(),
        StageAwareGenerator(), heartbeat_seconds=0,
    ).execute(retry.id)
    finished = service.get_regeneration_status(TEACHER, unit_id, "viejo")
    assert finished["status"] == "succeeded" and finished["previousDiscarded"] is True
    assert review_repository.get_resource_by_id(TEACHER, "viejo")["status"] == "descartado"
