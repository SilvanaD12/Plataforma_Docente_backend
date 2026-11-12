"""PR #14: borrar el curso mientras un paso genera o guarda la imagen de un recurso.

Reproduce lo que encontró la revisión: el pedido, sus pasos y el recurso desaparecían, pero la imagen se guardaba
después del borrado y quedaba huérfana en `media_assets`. Usa los repositorios reales de Cuentas, Revisión, Generación y
multimedia sobre un SQLite temporal (con la cascada de claves foráneas apagada) y un generador de imágenes falso.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from platform5e.application.ports.outbound.media_port import GeneratedMedia
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_media_repository as media_module,
    sqlalchemy_resource_repository as resources,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from tests.support.generation_fakes import FakeEvidence, FakeRunner
from tests.unit.test_sequence_orchestrator import DISTINCT_RESOURCES, StageAwareGenerator

TEACHER = "docente@example.com"
IMAGE_RESOURCE = {
    "titulo": "Conexión TCP en tres pasos",
    "contenido": "La ilustración muestra cómo TCP establece una conexión antes de enviar datos.",
    "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
    "alternativas": [],
    "estructura": {
        "descripcion_imagen": "Ilustración didáctica de dos computadoras que establecen una conexión TCP antes de "
        "enviar datos.",
        "texto_alternativo": "Dos computadoras conectadas que intercambian mensajes de inicio de conexión.",
        "leyenda": "TCP establece la conexión antes de enviar datos.",
    },
}


class PausingMediaGenerator:
    """Genera una imagen falsa; la primera vez espera a que la prueba la libere."""

    description = "imágenes falsas"

    def __init__(self, pause: bool) -> None:
        self.pause = pause
        self.generating = threading.Event()
        self.release = threading.Event()

    def generate_image(self, prompt: str) -> GeneratedMedia:
        self.generating.set()
        if self.pause:
            assert self.release.wait(10), "la prueba no liberó el generador de imágenes"
        return GeneratedMedia(b"\x89PNGimagen-falsa", "image/png", "png")

    def synthesize_speech(self, script: str) -> GeneratedMedia:
        return GeneratedMedia(b"ID3audio-falso", "audio/mpeg", "mp3")


class HookedMediaRepository(media_module.SQLAlchemyMediaRepository):
    """Repositorio real de multimedia que puede ejecutar algo justo después de guardar."""

    after_saving: Callable[[], None] = staticmethod(lambda: None)

    def save_media(self, teacher_id: str, media: Any, content: bytes) -> None:
        super().save_media(teacher_id, media, content)
        self.after_saving()


class Setup:
    def __init__(self, tmp_path, monkeypatch, pause_media: bool) -> None:
        self.engine: Engine = create_engine(
            URL.create("sqlite", database=str(tmp_path / "multimedia.db")), connect_args={"check_same_thread": False}
        )
        sessions = sessionmaker(bind=self.engine)
        for module in (accounts, media_module):
            monkeypatch.setattr(module, "engine", self.engine)
            monkeypatch.setattr(module, "SessionLocal", sessions)
        monkeypatch.setattr(resources, "SessionLocal", sessions)

        account_repository = accounts.SQLAlchemyAccountRepository()
        self.service = AccountService(account_repository, "", "")
        self.review = resources.SQLAlchemyResourceRepository()
        self.requests = SQLAlchemyGenerationRequestRepository(self.engine)
        self.media = HookedMediaRepository()
        self.media_generator = PausingMediaGenerator(pause_media)
        membership = AccountUnitMembershipAdapter(account_repository)
        evidence = FakeEvidence()
        with self.engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 0

        self.course = self.service.save_course(
            TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Protocolos"}]}
        )
        self.unit_id = self.course["units"][0]["id"]
        self.request_id = StartGenerationRequest(membership, evidence, self.requests, FakeRunner()).execute(
            StartGenerationCommand(
                TEACHER,
                self.unit_id,
                GenerationMode.INDIVIDUAL,
                "clave-imagen-y-borrado",
                GenerationParameters(resource_types=("imagen_ilustrativa",)),
            )
        ).request.id
        self.run = RunGenerationRequest(
            self.requests,
            membership,
            evidence,
            self.review,
            ReviewVerificationAdapter(),
            StageAwareGenerator({**DISTINCT_RESOURCES, "imagen_ilustrativa": IMAGE_RESOURCE}),
            media_generator=self.media_generator,
            media_repository=self.media,
            heartbeat_seconds=0,
        )

    def delete_course(self) -> None:
        self.service.delete_course(TEACHER, self.course["id"])

    def assert_nothing_left(self) -> None:
        with self.engine.connect() as connection:
            count = lambda sql: connection.execute(text(sql), {"unit": self.unit_id, "id": self.request_id}).scalar()  # noqa: E731
            assert count("SELECT COUNT(*) FROM media_assets") == 0, "quedó multimedia huérfana"
            assert count("SELECT COUNT(*) FROM ep002_recursos WHERE unidad = :unit") == 0
            assert count("SELECT COUNT(*) FROM gen_generation_requests WHERE unit_id = :unit") == 0
            assert count("SELECT COUNT(*) FROM gen_generation_steps WHERE request_id = :id") == 0


@pytest.fixture
def make_setup(tmp_path, monkeypatch, request):
    def make(pause_media: bool) -> Setup:
        setup = Setup(tmp_path, monkeypatch, pause_media)
        request.addfinalizer(setup.engine.dispose)
        return setup

    return make


def test_without_deleting_the_course_the_image_is_saved_with_its_resource(make_setup):
    """Control: el recurso de imagen llega a Revisión con su archivo guardado."""
    setup = make_setup(pause_media=False)
    setup.run.execute(setup.request_id)

    [resource] = setup.review.get_resources_by_unit(TEACHER, setup.unit_id)
    assert resource["media"]["status"] == "ready"
    stored = setup.media.get_media(TEACHER, resource["media"]["id"])
    assert stored is not None and stored[1] == b"\x89PNGimagen-falsa"


def test_deleting_the_course_while_the_image_is_generated_leaves_no_media(make_setup):
    """El generador de imágenes se detiene; la prueba borra el curso y lo libera."""
    setup = make_setup(pause_media=True)
    worker = threading.Thread(target=setup.run.execute, args=(setup.request_id,), name="generation-test")
    worker.start()
    assert setup.media_generator.generating.wait(10), "el paso no llegó a generar la imagen"

    setup.delete_course()
    setup.media_generator.release.set()
    worker.join(timeout=30)
    assert not worker.is_alive()

    setup.assert_nothing_left()


def test_deleting_the_course_after_saving_the_image_and_before_confirming_the_step_leaves_no_media(make_setup):
    """El curso se borra justo después de guardar la imagen, antes de que el paso se confirme."""
    setup = make_setup(pause_media=False)
    setup.media.after_saving = setup.delete_course

    setup.run.execute(setup.request_id)

    setup.assert_nothing_left()
