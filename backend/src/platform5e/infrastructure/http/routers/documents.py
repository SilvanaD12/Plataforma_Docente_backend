"""
Adaptador HTTP del material de la unidad: subir, procesar, consultar y buscar por tema (EP-002, HU-011).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import ValidationError

from platform5e.application.services.accounts.account_service import MAX_FILE_SIZE, AccountService
from platform5e.application.services.materials.material_service import MaterialService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.documents import (
    ChunkResponse,
    DocumentContextInput,
    DocumentResponse,
    TopicSearchRequest,
)

MEDIA_TYPES: dict[str, str] = {
    "txt": "text/plain; charset=utf-8",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
CONTEXT_EXAMPLE = (
    '{"unitId": "unidad-1", "outcomeIds": [], "documentType": "Separata o apuntes de clase", "usePermission": true}'
)


def create_documents_router(account_service: AccountService, material_service: MaterialService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get(
        "/search",
        summary="Hybrid search of evidence across documents",
        responses=error_responses(401, 404),
    )
    def search_evidence(
        query: str,
        unit_id: str | None = None,
        top_k: int = 5,
        teacher_id: str = Depends(current_teacher),
    ) -> list[dict[str, Any]]:
        """Realiza una búsqueda híbrida (BM25 + pgvector HNSW) para recuperar fragmentos relevantes."""
        # Aquí puedes invocar tu HybridEvidenceRetriever configurado a través del material_service o repositorio correspondiente
        return material_service.search_evidence(teacher_id, query, top_k=top_k, unit_id=unit_id)
    
    @router.get("", response_model=list[DocumentResponse], summary="List my documents", responses=error_responses(401))
    def list_documents(teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Documents of every unit of the teacher, with their processing status.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/documents" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return account_service.list_documents(teacher_id)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=DocumentResponse,
        summary="Upload a document",
        responses=error_responses(400, 401, 404, 409, 413, 422),
    )
    async def upload_document(
        file: UploadFile = File(description="PDF, PPTX or TXT up to 25 MB."),
        context: str = Form(description="JSON with the unit and the use permission.", examples=[CONTEXT_EXAMPLE]),
        teacher_id: str = Depends(current_teacher),
    ) -> dict[str, Any]:
        """Saves the file in the database with status `registrado`. Call POST /documents/{id}/process next.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/documents" -H "Authorization: Bearer $TOKEN" -F "file=@material.txt" -F 'context={"unitId":"unidad-1","outcomeIds":[],"documentType":"Separata o apuntes de clase","usePermission":true}'
        ```

        Replace material.txt with your own file. The context unitId must belong to your account. Expected 201; process the returned document id next."""
        try:
            try:
                parsed_context = DocumentContextInput.model_validate(json.loads(context)).model_dump(by_alias=True)
            except (ValueError, TypeError, ValidationError):
                raise AccountConfigurationError("INVALID_CONTEXT", "Revisa los datos del documento.", 422)
            
            # Validación de seguridad MAT-C2 antes de gastar memoria leyendo el archivo
            material_service.validate_unit_membership_secure(
                teacher_id, 
                parsed_context["unitId"], 
                parsed_context.get("outcomeIds", [])
            )

            content = await file.read(MAX_FILE_SIZE + 1)
            return account_service.register_document(teacher_id, file.filename or "archivo", content, parsed_context)
        finally:
            await file.close()

    @router.post(
        "/from-topic",
        status_code=status.HTTP_201_CREATED,
        response_model=list[DocumentResponse],
        summary="Add material from an open source",
        responses=error_responses(400, 401, 404, 422, 503),
    )
    def create_documents_from_topic(body: TopicSearchRequest, teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Searches the topic in Spanish Wikipedia (CC BY-SA 4.0) and saves each article as processed material.

        Articles already in the unit are skipped. 503 when the topic search is disabled or the source does not answer.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/documents/from-topic" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"unitId":"unidad-1","topic":"Protocolo de control de transmisión","maxResults":1}'
        ```

        Replace unidad-1 with your unit id. Expected 201 when topic search is enabled; a disabled or unavailable source returns 503."""
        return material_service.create_from_topic(teacher_id, body.unit_id, body.topic, body.max_results)

    @router.get(
        "/{document_id}/file",
        summary="Download the original file",
        response_class=Response,
        responses={
            200: {"content": {media: {} for media in MEDIA_TYPES.values()}, "description": "The original file."},
            **error_responses(401, 404),
        },
    )
    def download_document(document_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Returns the file as it was uploaded, with its name in Content-Disposition.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -X GET "$BASE_URL/api/v1/documents/${DOCUMENT_ID}/file" -H "Authorization: Bearer $TOKEN" -D respuesta-headers.txt --output material.txt
        ```

        Expected 200. See the response schema below for the returned fields."""
        metadata, content = account_service.get_document(teacher_id, document_id)
        file_name = quote(metadata["fileName"], safe="")
        return Response(
            content,
            media_type=MEDIA_TYPES.get(metadata["kind"], "application/octet-stream"),
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name}"},
        )

    @router.delete(
        "/{document_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a document",
        responses=error_responses(401, 404),
    )
    def delete_document(document_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Deletes the file and its chunks. Generated resources keep their own copy of the evidence.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X DELETE "$BASE_URL/api/v1/documents/${DOCUMENT_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Deletes the document and its chunks. Expected 204 with an empty body."""
        account_service.delete_document(teacher_id, document_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{document_id}/process",
        response_model=DocumentResponse,
        summary="Extract the text and split it into chunks",
        responses=error_responses(401, 404),
    )
    def process_document(document_id: str, teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Extracts the text (PDF, PPTX or TXT) and splits it into chunks of about 220 words with their location.

        A file without text ends with status `error` and an explanation in `errorMessage`; it does not fail the request.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/documents/${DOCUMENT_ID}/process" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return material_service.process_material(teacher_id, document_id)

    @router.get(
        "/{document_id}/chunks",
        response_model=list[ChunkResponse],
        summary="List the chunks of a document",
        responses=error_responses(401, 404),
    )
    def list_document_chunks(document_id: str, teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Chunks in document order. They are the evidence that generated resources cite.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/documents/${DOCUMENT_ID}/chunks" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return material_service.get_document_chunks(teacher_id, document_id)

    return router
