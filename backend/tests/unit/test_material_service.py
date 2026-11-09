"""
Servicio de ingesta con dobles de prueba: procesar documentos, consultar fragmentos y generar material desde temas.
"""

from typing import Any
import pytest

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.open_educational_resource_port import OpenEducationalResourcePort
from platform5e.application.ports.outbound.text_extractor_port import TextExtractorPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.materials.material_service import (
    MaterialService,
    build_article_filename,
)
from platform5e.domain.materials.chunking import MaterialError
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

PAGE_TEXT: str = (
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los datos. "
    "El protocolo UDP no establece conexión y es más rápido para videollamadas."
)


class MockConfigRepository(TeacherRepositoryPort):
    def __init__(self) -> None:
        self.docs: dict[str, tuple[dict[str, Any], bytes]] = {}
        self.unit: dict[str, Any] = {"id": "u1", "title": "Protocolos", "outcomes": []}

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [{"id": "c1", "units": [self.unit]}]

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return [metadata for metadata, _ in self.docs.values()]

    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None:
        self.docs[metadata["id"]] = (metadata, content)

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None:
        return self.docs.get(document_id)

    def init_catalog(self, teacher_id: str) -> None: ...
    def get_user_by_email(self, email: str) -> dict[str, Any] | None: return None
    def create_user(self, user_data: dict[str, Any]) -> None: ...
    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None: ...
    def get_session(self, fingerprint: str) -> tuple[str, float] | None: return None
    def delete_session(self, fingerprint: str) -> None: ...
    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None: ...
    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None: ...
    def delete_document(self, teacher_id: str, document_id: str) -> None:
        self.docs.pop(document_id, None)
    def get_history(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def get_generation_owner(self, generation_id: str) -> str | None: return None


class MockChunkRepository(ChunkRepositoryPort):
    def __init__(self, config_repo: MockConfigRepository) -> None:
        self.config_repo = config_repo
        self.chunks_db: dict[str, list[dict[str, Any]]] = {}

    def replace_chunks(
        self, teacher_id: str, document_id: str, unit_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        self.chunks_db[document_id] = [
            {**chunk, "documentId": document_id, "documento_id": document_id, "unitId": unit_id, "unidad_id": unit_id}
            for chunk in chunks
        ]

    def get_chunks_by_document(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]:
        return self.chunks_db.get(document_id, [])

    def get_chunks_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [
            chunk
            for chunk_list in self.chunks_db.values()
            for chunk in chunk_list
            if chunk.get("unitId") == unit_id or chunk.get("unidad_id") == unit_id
        ]

    def update_document(self, teacher_id: str, document_data: dict[str, Any]) -> None:
        _, content = self.config_repo.docs[document_data["id"]]
        self.config_repo.docs[document_data["id"]] = (document_data, content)


class MockExtractor(TextExtractorPort):
    def __init__(self, pages: list[tuple[str, str]] | None = None, error: Exception | None = None) -> None:
        self.pages = pages
        self.error = error

    def extract(self, file_type: str, content: bytes) -> list[tuple[str, str]]:
        if self.error:
            raise self.error
        return self.pages or []


class MockOpenResource(OpenEducationalResourcePort):
    def __init__(self, articles: list[dict[str, Any]] | None = None, should_fail: bool = False) -> None:
        self.articles = articles or []
        self.should_fail = should_fail
        self.recorded_requests: list[tuple[str, int]] = []

    def search(self, topic: str, limit: int) -> list[dict[str, Any]]:
        self.recorded_requests.append((topic, limit))
        if self.should_fail:
            raise ConnectionError("sin red")
        return self.articles


def build_test_environment(
    pages: list[tuple[str, str]] | None = None,
    error: Exception | None = None,
    open_resource: OpenEducationalResourcePort | None = None,
) -> tuple[MaterialService, MockConfigRepository, MockChunkRepository]:
    config_repo = MockConfigRepository()
    chunk_repo = MockChunkRepository(config_repo)
    config_repo.save_document(
        "d",
        {"id": "doc1", "unitId": "u1", "kind": "txt", "fileName": "apuntes.txt", "status": "registrado"},
        b"x",
    )
    service = MaterialService(
        config_repo,
        chunk_repo,
        MockExtractor(pages if pages is not None else [("p. 1", PAGE_TEXT)], error),
        open_resource_port=open_resource,
    )
    return service, config_repo, chunk_repo


def test_processing_saves_chunks_and_marks_processed():
    service, config_repo, chunk_repo = build_test_environment()
    data = service.process_material("d", "doc1")
    assert data["status"] == "procesado" and data["fragmentCount"] == 1 and data["pageCount"] == 1
    assert data["processedAt"] and data["errorMessage"] is None
    assert config_repo.docs["doc1"][0]["status"] == "procesado"
    assert chunk_repo.chunks_db["doc1"][0]["id"].startswith("frag-")

    fragments_view = service.get_document_chunks("d", "doc1")
    assert fragments_view[0]["location"] == "p. 1"
    assert fragments_view[0]["text"].startswith("El protocolo TCP")


def test_processing_without_text_leaves_an_explained_error():
    service, _, chunk_repo = build_test_environment(pages=[("p. 1", " "), ("p. 2", "")])
    data = service.process_material("d", "doc1")
    assert data["status"] == "error" and "escaneado" in data["errorMessage"] and data["pageCount"] == 2
    assert chunk_repo.chunks_db["doc1"] == []


def test_processing_an_unreadable_file_does_not_raise_and_explains():
    service, _, _ = build_test_environment(error=MaterialError("PROTECTED_PDF", "El PDF está protegido."))
    data = service.process_material("d", "doc1")
    assert data["status"] == "error" and data["errorMessage"] == "El PDF está protegido."


def test_missing_document_returns_404():
    service, _, _ = build_test_environment()
    with pytest.raises(MaterialError) as error:
        service.process_material("d", "no-existe")
    assert error.value.status_code == 404
    with pytest.raises(MaterialError):
        service.get_document_chunks("d", "no-existe")


def test_from_topic_creates_processed_documents_without_duplicates():
    article = {
        "titulo": "Protocolo de control de transmisión",
        "url": "https://es.wikipedia.org/wiki/TCP",
        "texto": PAGE_TEXT,
        "licencia": "CC BY-SA 4.0",
        "fuente": "Wikipedia",
    }
    mock_source = MockOpenResource([article])
    service, config_repo, _ = build_test_environment(open_resource=mock_source)
    created = service.create_from_topic("d", "u1", "  protocolo   TCP ", 9)

    assert mock_source.recorded_requests == [("protocolo TCP", 5)]
    assert len(created) == 1 and created[0]["status"] == "procesado"
    assert created[0]["origin"]["url"] == article["url"]
    assert created[0]["documentType"] == "Artículo de fuente abierta"

    saved_content = config_repo.docs[created[0]["id"]][1].decode()
    assert saved_content.startswith("Protocolo de control de transmisión\n\n")
    assert "wikipedia" not in saved_content.lower()
    assert created[0]["origin"]["license"] == "CC BY-SA 4.0"

    re_requested = service.create_from_topic("d", "u1", "protocolo TCP")
    assert re_requested[0]["id"] == created[0]["id"]


@pytest.mark.parametrize(
    "topic,unit_id,source_instance,expected_code",
    [
        ("ab", "u1", MockOpenResource(), "INVALID_TOPIC"),
        ("redes", "otra", MockOpenResource(), "UNIT_NOT_FOUND"),
        ("redes", "u1", None, "TOPIC_SEARCH_UNAVAILABLE"),
        ("redes", "u1", MockOpenResource(should_fail=True), "SOURCE_UNAVAILABLE"),
        ("redes", "u1", MockOpenResource([]), "NO_RESULTS"),
    ],
)
def test_from_topic_rejections(topic, unit_id, source_instance, expected_code):
    service, _, _ = build_test_environment(open_resource=source_instance)
    with pytest.raises(MaterialError) as error:
        service.create_from_topic("d", unit_id, topic)
    assert error.value.code == expected_code


def test_from_topic_propagates_source_errors():
    class SourceWithQuotaError(MockOpenResource):
        def search(self, topic: str, limit: int) -> list[dict[str, Any]]:
            raise MaterialError("CUOTA", "Límite de la fuente.", 429)

    service, _, _ = build_test_environment(open_resource=SourceWithQuotaError())
    with pytest.raises(MaterialError) as error:
        service.create_from_topic("d", "u1", "redes")
    assert error.value.code == "CUOTA"


def test_article_file_name_is_safe():
    assert build_article_filename("TCP/IP \\ redes", "Wikipedia") == "TCP IP   redes.txt"
    assert build_article_filename("", "Wikipedia") == "Artículo.txt"

def test_material_service_unit_membership_validation():
    """Valida que el servicio verifique la membresía de la unidad (MAT-C2)."""
    service, config_repo, _ = build_test_environment()
    courses = config_repo.get_courses("d")
    unit_id = courses[0]["units"][0]["id"]
    
    # Verificamos que acepte una unidad y outcomes válidos sin error
    try:
        service.validate_unit_membership_secure("d", unit_id, [])
    except Exception as e:
        pytest.fail(f"La validación falló con datos válidos: {e}")