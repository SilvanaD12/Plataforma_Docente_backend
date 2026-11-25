"""Pruebas unitarias para MAT-P1 (Pedido P6 / Plan v2-H): ingesta desde URLs públicas y bloqueo anti-SSRF."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from platform5e.application.services.materials.material_service import MaterialService
from platform5e.domain.materials.chunking import MaterialError
from platform5e.infrastructure.extraction.document_text_extractor import DocumentTextExtractor
from platform5e.infrastructure.sources.web_page_extractor import (
    WebPageExtractor,
    extract_readable_text,
    validate_public_http_url,
)


class _InMemoryTeacherRepo:
    def __init__(self, courses: list[dict[str, Any]]) -> None:
        self._courses = courses
        self.documents: dict[str, tuple[dict[str, Any], bytes]] = {}

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return self._courses

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return [meta for meta, _ in self.documents.values()]

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None:
        return self.documents.get(document_id)

    def save_document(self, teacher_id: str, doc_data: dict[str, Any], content: bytes) -> None:
        self.documents[doc_data["id"]] = (dict(doc_data), content)


class _InMemoryChunkRepo:
    def __init__(self, teacher_repo: _InMemoryTeacherRepo) -> None:
        self._teacher_repo = teacher_repo
        self.chunks: dict[str, list[dict[str, Any]]] = {}

    def replace_chunks(
        self, teacher_id: str, document_id: str, unit_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        self.chunks[document_id] = list(chunks)

    def update_document(self, teacher_id: str, document_data: dict[str, Any]) -> None:
        if document_data["id"] in self._teacher_repo.documents:
            _, raw = self._teacher_repo.documents[document_data["id"]]
            self._teacher_repo.documents[document_data["id"]] = (dict(document_data), raw)

    def get_chunks_by_document(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]:
        return self.chunks.get(document_id, [])


@pytest.mark.parametrize(
    "forbidden_url",
    [
        "ftp://example.com/archivo.txt",
        "http://localhost:8000/admin",
        "http://127.0.0.1/secret",
        "http://192.168.1.10/router",
        "http://10.0.0.5/internal",
        "http://172.16.0.1/panel",
    ],
)
def test_validate_public_http_url_blocks_ssrf_and_invalid_schemes(forbidden_url: str) -> None:
    with pytest.raises(MaterialError) as exc_info:
        validate_public_http_url(forbidden_url)
    assert exc_info.value.status_code in {400, 422}


def test_extract_readable_text_strips_scripts_styles_and_navigation() -> None:
    sample_html = """
    <html>
      <head>
        <title>Arquitectura de Redes TCP/IP</title>
        <style>body { color: red; }</style>
        <script>console.log('ignorar');</script>
      </head>
      <body>
        <nav>Inicio | Cursos | Salir</nav>
        <main>
          <h1>Modelo TCP/IP</h1>
          <p>El protocolo TCP garantiza la entrega ordenada y fiable de paquetes en la red.</p>
        </main>
        <footer>Derechos reservados</footer>
      </body>
    </html>
    """
    title, text = extract_readable_text(sample_html, "fallback")
    assert title == "Arquitectura de Redes TCP/IP"
    assert "Modelo TCP/IP" in text
    assert "entrega ordenada y fiable" in text
    assert "console.log" not in text
    assert "Inicio | Cursos" not in text


def test_extract_readable_text_handles_void_tags_inside_ignored_blocks() -> None:
    sample_html = """
    <html>
      <head><title>Artículo con saltos en navegación</title></head>
      <body>
        <nav>
          Enlace 1<br>
          Enlace 2<br/>
          <img src="/logo.png" alt="Logo">
          <hr>
        </nav>
        <article>
          <h1>Contenido Principal</h1>
          <p>Este párrafo debe conservarse íntegro después de cerrar la barra de navegación.</p>
        </article>
      </body>
    </html>
    """
    title, text = extract_readable_text(sample_html, "fallback")
    assert title == "Artículo con saltos en navegación"
    assert "Enlace 1" not in text
    assert "Enlace 2" not in text
    assert "Contenido Principal" in text
    assert "Este párrafo debe conservarse íntegro" in text


def test_extract_readable_text_cleans_wikipedia_noise_and_title_suffix() -> None:
    wiki_html = """
    <html>
      <head>
        <title>Modelo OSI - Wikipedia, la enciclopedia libre</title>
      </head>
      <body>
        <div id="toc" class="toc">Índice de contenidos</div>
        <main>
          <h1>Modelo OSI <span class="mw-editsection">[editar]</span></h1>
          <p>El modelo de interconexión de sistemas abiertos<sup class="reference">[1]</sup> define siete capas de red[2].</p>
          <h2>Referencias</h2>
          <div class="reflist">Tanenbaum, Redes de computadoras.</div>
        </main>
        <div class="navbox">Plantilla de navegación</div>
      </body>
    </html>
    """
    title, text = extract_readable_text(wiki_html, "fallback")
    assert title == "Modelo OSI"
    assert "siete capas de red" in text
    assert "[editar]" not in text
    assert "[1]" not in text
    assert "[2]" not in text
    assert "Tanenbaum" not in text
    assert "Índice de contenidos" not in text
    assert "Plantilla de navegación" not in text


def test_web_page_extractor_fetches_public_html_with_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "platform5e.infrastructure.sources.web_page_extractor.validate_public_http_url",
        lambda url: url,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "<html><head><title>Sistemas Distribuidos</title></head>"
            "<body><p>" + ("Consistencia eventual y replicación de datos en nodos distribuidos. " * 6) + "</p></body></html>"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    extractor = WebPageExtractor(client=client)
    result = extractor.fetch("https://ejemplo-educativo.org/distribuidos")

    assert result["url"] == "https://ejemplo-educativo.org/distribuidos"
    assert result["title"] == "Sistemas Distribuidos"
    assert "Consistencia eventual" in result["text"]


def test_material_service_create_from_url_ingests_and_isolates_units() -> None:
    courses = [
        {
            "id": "c-1",
            "name": "Bases de Datos",
            "units": [{"id": "u-1", "title": "Modelo Relacional", "outcomes": [{"id": "out-1"}]}],
        }
    ]
    teacher_repo = _InMemoryTeacherRepo(courses)
    chunk_repo = _InMemoryChunkRepo(teacher_repo)

    class _FakeWebFetcher:
        def fetch(self, url: str) -> dict[str, Any]:
            return {
                "url": url,
                "title": "Introducción a Bases de Datos - Wikipedia, la enciclopedia libre",
                "text": "Una base de datos relacional organiza la información en tablas normalizadas. " * 10,
            }

    service = MaterialService(
        teacher_repository=teacher_repo,  # type: ignore[arg-type]
        chunk_repository=chunk_repo,  # type: ignore[arg-type]
        text_extractor=DocumentTextExtractor(),
        web_fetcher_port=_FakeWebFetcher(),
    )

    created = service.create_from_url(
        teacher_id="docente-1",
        unit_id="u-1",
        url="https://ejemplo.org/bd",
        outcome_ids=["out-1"],
    )
    assert created["status"] == "procesado"
    assert created["fragmentCount"] >= 1
    assert created["pageCount"] is None
    assert created["origin"]["source"] == "Web"
    assert created["origin"]["url"] == "https://ejemplo.org/bd"

    # Unidad ajena devuelve 404 indistinguible
    with pytest.raises(MaterialError) as exc_info:
        service.create_from_url(teacher_id="docente-1", unit_id="u-ajena", url="https://ejemplo.org/bd")
    assert exc_info.value.status_code == 404