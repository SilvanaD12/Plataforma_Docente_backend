"""
Punto de composición (composition root): crea los adaptadores, los inyecta en los servicios y casos de uso de la
capa de aplicación y registra las rutas HTTP. Es el único módulo que conoce todas las capas.

    uvicorn platform5e.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from platform5e.application.use_cases.catalog.list_resource_types import ListResourceTypesUseCase
from platform5e.infrastructure.http.routers.catalog import create_catalog_router

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.materials.chunk_embedding_service import ChunkEmbeddingService
from platform5e.application.services.materials.material_service import MaterialService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.application.services.materials.referent_service import ReferentService
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.application.services.generation.plan_drafting import GenerationPlanner
from platform5e.application.use_cases.generation.approve_generation_plan import ApproveGenerationPlan
from platform5e.application.use_cases.generation.create_generation_plan import (
    INVALID_OUTCOME_MESSAGE,
    UNIT_NOT_FOUND_MESSAGE,
    CreateGenerationPlan,
)
from platform5e.application.use_cases.generation.get_generation_evidence import GetGenerationEvidence
from platform5e.application.use_cases.generation.get_generation_plan import GetGenerationPlan
from platform5e.application.use_cases.generation.update_generation_plan import UpdateGenerationPlan
from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.interpret_generation_request import (
    InterpretGenerationRequest,
    SuggestedUnit,
)
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationRequest
from platform5e.application.use_cases.generation.start_regeneration import StartRegeneration
from platform5e.application.use_cases.media.get_resource_media import GetResourceMediaUseCase
from platform5e.application.use_cases.media.regenerate_resource_media import RegenerateResourceMediaUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import GenerationPlan
from platform5e.domain.materials.chunking import MaterialError
from platform5e.domain.shared.errors import DuplicateRecordError, EntityNotFoundError, PersistenceUnavailableError
from platform5e.application.use_cases.health.check_dependencies import CheckDependencies
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter
from platform5e.infrastructure.adapters.database_probe_adapter import DatabaseProbeAdapter
from platform5e.infrastructure.adapters.gemini_probe_adapter import GeminiProbeAdapter
from platform5e.infrastructure.adapters.generation_regeneration_adapter import GenerationRegenerationAdapter
from platform5e.infrastructure.adapters.material_evidence_adapter import MaterialEvidenceAdapter
from platform5e.infrastructure.adapters.course_session_typology_adapter import CourseSessionTypologyAdapter
from platform5e.infrastructure.adapters.plan_context_adapters import NoReferentsAdapter
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.adapters.wikipedia_probe_adapter import WikipediaProbeAdapter
from platform5e.infrastructure.exporters.moodle_xml_exporter import MoodleXmlExporter
from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from platform5e.infrastructure.exporters.scorm_package_exporter import ScormPackageExporter
from platform5e.infrastructure.exporters.visual_renderer import SvgVisualRenderer
from platform5e.infrastructure.extraction.document_text_extractor import DocumentTextExtractor
from platform5e.infrastructure.http.error_handlers import (
    conflict_error_handler,
    domain_error_handler,
    not_found_handler,
    persistence_unavailable_handler,
    request_validation_error_handler,
    value_error_handler,
)
from platform5e.infrastructure.http.routers.accounts import create_accounts_router
from platform5e.infrastructure.http.routers.courses import create_courses_router
from platform5e.infrastructure.http.routers.documents import create_documents_router
from platform5e.infrastructure.http.routers.downloads import (
    create_downloads_router,
    create_teacher_downloads_router,
)
from platform5e.infrastructure.http.routers.exports import create_exports_router
from platform5e.infrastructure.http.routers.generation_plans import create_generation_plans_router
from platform5e.infrastructure.http.routers.generation_requests import (
    create_generation_interpretation_router,
    create_generation_requests_router,
)
from platform5e.infrastructure.http.routers.generations import create_generations_router
from platform5e.infrastructure.http.routers.health import create_health_router
from platform5e.infrastructure.http.routers.resources import create_resources_router
from platform5e.infrastructure.http.security import (
    IpRateLimitMiddleware,
    PayloadSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from platform5e.infrastructure.llm.language_model_factory import (
    create_embedding_generator,
    create_generators,
    create_media_generator,
    describe_generator,
)
from platform5e.infrastructure.jobs.stale_request_sweeper import StaleRequestSweeper
from platform5e.infrastructure.jobs.thread_pool_generation_runner import ThreadPoolGenerationRunner
from platform5e.infrastructure.persistence.database import engine as db_engine
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import SQLAlchemyAccountRepository
from platform5e.infrastructure.retrieval.bm25_evidence_retriever import Bm25EvidenceRetriever
from platform5e.infrastructure.retrieval.hybrid_evidence_retriever import HybridEvidenceRetriever
from platform5e.infrastructure.persistence.repositories.sqlalchemy_chunk_repository import SQLAlchemyChunkRepository
from platform5e.infrastructure.persistence.repositories.sqlalchemy_media_repository import SQLAlchemyMediaRepository
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
    SQLAlchemyGenerationPlanRepository,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_resource_repository import (
    SQLAlchemyResourceRepository,
)
from platform5e.infrastructure.settings import (
    GENERATION_STALE_REQUEST_SECONDS,
    generation_implicit_plan,
    generation_max_workers,
    generation_require_plan,
    generation_regeneration_wait_seconds,
    generation_request_deadline_seconds,
    generation_sweep_interval_seconds,
    read_flag,
    read_setting,
    review_duplicate_threshold,
    topic_coverage_threshold,
)
from platform5e.infrastructure.sources.wikipedia_source import WikipediaSource
from platform5e.infrastructure.sources.web_page_extractor import WebPageExtractor
from platform5e.infrastructure.llm.gemini_referent_extractor import GeminiReferentExtractor
from platform5e.infrastructure.persistence.repositories.sqlalchemy_referent_repository import (
    SQLAlchemyReferentRepository,
)

API_DESCRIPTION = """
Backend of **Platform 5E**: teachers upload the material of a unit, generate 5E learning resources that cite it
(RAG), review them and export the approved ones to Moodle (Moodle XML) or Chamilo (SCORM 1.2).

**Authentication.** `POST /api/v1/accounts` or `POST /api/v1/sessions` return a bearer token. Click *Authorize* and
paste only the token. Private routes answer 401 without it.

**Errors.** Every error has the same shape: `{"error": {"code": "UNIT_NOT_FOUND", "message": "…"}}`. The `code` is
stable and in English; the `message` is shown to the teacher, so it is in Spanish.

**Stored values.** Review statuses (`pendiente`, `aprobado`, `descartado`), resource types (`item_opcion_multiple`…)
and difficulties (`basica`, `intermedia`, `avanzada`) are values saved in the database. They move to English in
Sprint 2 together with a data migration.
"""

OPENAPI_TAGS = [
    {"name": "catalog", "description": "Public resource types, labels, stages and formats."},
    {"name": "accounts", "description": "Teacher registration."},
    {"name": "sessions", "description": "Sign in, current teacher and sign out."},
    {"name": "courses", "description": "Courses with their units and learning outcomes."},
    {"name": "documents", "description": "Unit material: upload, text extraction, chunks and open sources."},
    {"name": "generations", "description": "Resource generation from the unit material (RAG) and its history."},
    {
        "name": "generation-plans",
        "description": "The plan reviewed and approved before generating: resources, purposes, concepts and evidence.",
    },
    {"name": "resources", "description": "Teacher review of the generated resources."},
    {"name": "downloads", "description": "Download history of each unit."},
    {"name": "exports", "description": "Moodle XML and SCORM 1.2 files built in the backend."},
    {"name": "system", "description": "Health check and active generator."},
]

# Research R3: un pedido activo sin latido en este tiempo no tiene dueño (quedó de un proceso anterior o detenido).
STALE_REQUEST_SECONDS = GENERATION_STALE_REQUEST_SECONDS


def create_application() -> FastAPI:
    """Crea la aplicación con sus dependencias. Las variables de entorno se leen solo aquí y en los adaptadores."""
    generation_request_repository = SQLAlchemyGenerationRequestRepository()
    generation_runner: ThreadPoolGenerationRunner | None = None  # se crea abajo, con sus casos de uso
    stale_request_sweeper = StaleRequestSweeper(
        generation_request_repository,
        interval_seconds=generation_sweep_interval_seconds(),
        stale_seconds=STALE_REQUEST_SECONDS,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """GEN-01 (research R3): antes de aceptar tráfico, marca como interrumpidos los pedidos que quedaron a medias,
        crea el grupo de hilos e inicia el barrido periódico; al apagar, detiene el barrido y cierra el grupo sin
        esperar los pedidos que todavía están en cola."""
        generation_request_repository.mark_interrupted(
            datetime.now(timezone.utc) - timedelta(seconds=STALE_REQUEST_SECONDS)
        )
        assert generation_runner is not None
        generation_runner.start()
        stale_request_sweeper.start()
        try:
            yield
        finally:
            stale_request_sweeper.stop()
            generation_runner.shutdown(wait=False)

    app = FastAPI(
        title="Platform 5E API",
        version="2.0.0",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    app.add_middleware(PayloadSizeLimitMiddleware)
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    cors_origins = [o.strip().rstrip("/") for o in read_setting("CORS_ALLOWED_ORIGINS").split(",") if o.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

    # 1. Adaptadores de salida
    account_repository = SQLAlchemyAccountRepository()
    chunk_repository = SQLAlchemyChunkRepository()
    resource_repository = SQLAlchemyResourceRepository()
    open_source = WikipediaSource() if read_flag("TOPIC_SEARCH_ENABLED", True) else None
    web_fetcher = WebPageExtractor() if read_flag("URL_INGEST_ENABLED", True) else None
    primary_generator, fallback_generator = create_generators()
    media_repository = SQLAlchemyMediaRepository()
    media_generator = create_media_generator()
    embedding_generator = create_embedding_generator()

    # Recuperador híbrido con RRF (k=60), BM25 léxico y pgvector HNSW semántico
    evidence_retriever = HybridEvidenceRetriever(
        chunk_repository=chunk_repository,
        embedding_generator=embedding_generator,
        rrf_k=60,
    )

    # EN-028: dependency health probes (database, Gemini, Wikipedia).
    llm_api_key = read_setting("LLM_API_KEY").strip() or None
    llm_provider = (read_setting("LLM_PROVIDER") or ("gemini" if llm_api_key else "rules")).lower().strip()
    gemini_configured = llm_provider not in {"rules", "reglas"} and bool(llm_api_key)
    gemini_model = read_setting("LLM_MODEL").strip() or "gemini-3.8-flash"
    gemini_base_url = read_setting("LLM_BASE_URL").strip() or None

    dependency_probes = [
        DatabaseProbeAdapter(db_engine),
        GeminiProbeAdapter(
            api_key=llm_api_key if gemini_configured else None,
            model=gemini_model,
            base_url=gemini_base_url,
        ),
        WikipediaProbeAdapter(),
    ]
    check_dependencies = CheckDependencies(dependency_probes)

    # 2. Servicios y casos de uso de la capa de aplicación
    demo_catalog_enabled = read_flag("DEMO_CATALOG", False)
    account_service = AccountService(
        account_repository,
        seed_email=read_setting("BOOTSTRAP_TEACHER_EMAIL", "docente@5e.demo" if demo_catalog_enabled else ""),
        seed_password=read_setting("BOOTSTRAP_TEACHER_PASSWORD", "Demo5E!2026" if demo_catalog_enabled else ""),
        seed_demo_catalog=demo_catalog_enabled,
    )
    embedding_service = (
        ChunkEmbeddingService(chunk_repository, embedding_generator) if embedding_generator is not None else None
    )

    # Adaptador T007 para validación de pertenencia de unidades y resultados; lo comparten Material y Generación.
    unit_membership = AccountUnitMembershipAdapter(account_repository)

    def list_owned_units(teacher_id: str) -> list[SuggestedUnit]:
        return [
            {"unitId": unit["id"], "label": unit["title"]}
            for course in account_service.list_courses(teacher_id)
            for unit in course["units"]
        ]

    interpret_generation = InterpretGenerationRequest(unit_membership, list_owned_units)

    referent_repository = SQLAlchemyReferentRepository()
    referent_extractor = (
        GeminiReferentExtractor(
            api_key=llm_api_key,
            model=gemini_model,
            base_url=gemini_base_url,
        )
        if gemini_configured and llm_api_key
        else None
    )
    referent_service = ReferentService(
        repository=referent_repository,
        extractor=referent_extractor,
    )

    material_service = MaterialService(
        teacher_repository=account_repository,
        chunk_repository=chunk_repository,
        text_extractor=DocumentTextExtractor(),
        open_resource_port=open_source,
        embedding_service=embedding_service,
        unit_membership_port=unit_membership,
        evidence_retriever=evidence_retriever,
        web_fetcher_port=web_fetcher,
        referent_service=referent_service
    )

    # GEN-01: pedido de generación en segundo plano, con puertos hacia Cuentas, Material y Revisión.
    evidence_provider = MaterialEvidenceAdapter(chunk_repository, evidence_retriever, account_repository)
    # GEN-P1 y GEN-P2: el plan de generación, del que parte todo pedido. La IA arma el plan si el generador activo
    # sabe hacerlo (Gemini); si no, reglas.
    resource_catalog = StaticResourceCatalogAdapter()
    def validate_plan_reference(plan: GenerationPlan) -> None:
        unit = unit_membership.get_unit_context(plan.teacher_id, plan.unit_id)
        if unit is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)
        outcome_id = plan.inputs.outcome_id
        if outcome_id and outcome_id not in {outcome.id for outcome in unit.outcomes}:
            raise GenerationError(GenerationErrorCode.INVALID_OUTCOME, INVALID_OUTCOME_MESSAGE)

    generation_plan_repository = SQLAlchemyGenerationPlanRepository(validate_reference=validate_plan_reference)
    # CUR-P3: las tipologías de las últimas sesiones del curso, para el plan y para el pedido.
    session_typologies = CourseSessionTypologyAdapter(account_repository, generation_plan_repository)
    plan_drafter = primary_generator if hasattr(primary_generator, "draft_plan") else None
    create_plan = CreateGenerationPlan(
        unit_membership,
        evidence_provider,
        NoReferentsAdapter(),
        session_typologies,
        resource_catalog,
        GenerationPlanner(plan_drafter, {entry.id: entry for entry in resource_catalog.entries()}),
        generation_plan_repository,
        topic_coverage_threshold=topic_coverage_threshold(),
    )
    run_generation = RunGenerationRequest(
        generation_request_repository,
        unit_membership,
        evidence_provider,
        resource_repository,
        ReviewVerificationAdapter(),
        primary_generator,
        fallback_generator,
        media_generator=media_generator,
        media_repository=media_repository,
        deadline_seconds=generation_request_deadline_seconds(),
        topic_coverage_threshold=topic_coverage_threshold(),
        plans=generation_plan_repository,
        catalog=resource_catalog,
    )
    generation_runner = ThreadPoolGenerationRunner(
        run_generation.execute, generation_request_repository, max_workers=generation_max_workers()
    )
    # GEN-P2: el pedido parte de un plan aprobado; el cuerpo anterior crea un plan implícito mientras
    # GENERATION_REQUIRE_PLAN=false. GENERATION_IMPLICIT_PLAN=false (solo para medir la línea base de P4) lo redacta
    # como antes de GEN-P1; GENERATION_REQUIRE_PLAN=true tiene prioridad, porque se comprueba primero.
    start_generation = StartGenerationRequest(
        unit_membership,
        evidence_provider,
        generation_request_repository,
        generation_runner,
        plans=generation_plan_repository,
        implicit_plans=create_plan if generation_implicit_plan() else None,
        require_plan=generation_require_plan(),
        typologies=session_typologies,
    )
    get_generation = GetGenerationRequest(generation_request_repository, unit_membership, resource_repository)
    get_evidence = GetGenerationEvidence(generation_request_repository)

    get_plan = GetGenerationPlan(generation_plan_repository, unit_membership, resource_catalog)
    update_plan = UpdateGenerationPlan(generation_plan_repository, resource_catalog)
    approve_plan = ApproveGenerationPlan(generation_plan_repository, resource_catalog)
    # REV-01 (D10) y GEN-01 (T029): Revisión pide la regeneración por su puerto; el adaptador de Generación crea un
    # pedido `regeneration` en segundo plano y espera su resultado hasta GENERATION_REGENERATION_WAIT_SECONDS.
    review_service = ResourceReviewService(
        account_repository,
        resource_repository,
        GenerationRegenerationAdapter(
            StartRegeneration(start_generation, resource_repository),
            get_generation,
            wait_seconds=generation_regeneration_wait_seconds(),
        ),
        default_duplicate_threshold=review_duplicate_threshold(),
    )
    export_use_case = ExportUnitResourcesUseCase(
        account_repository,
        resource_repository,
        [ScormPackageExporter(), MoodleXmlExporter(), UnitDocumentExporter()],
        media_repository,
    )
    media_use_case = GetResourceMediaUseCase(review_service, media_repository, SvgVisualRenderer())
    regenerate_media_use_case = RegenerateResourceMediaUseCase(
        review_service, resource_repository, media_generator, media_repository
    )

    # 3. Errores del dominio
    for domain_error in (AccountConfigurationError, MaterialError, GenerationError):
        app.add_exception_handler(domain_error, domain_error_handler)
    app.add_exception_handler(DuplicateRecordError, conflict_error_handler)
    app.add_exception_handler(PersistenceUnavailableError, persistence_unavailable_handler)
    app.add_exception_handler(EntityNotFoundError, not_found_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    # 4. Adaptadores de entrada (rutas HTTP)
    app.include_router(create_catalog_router(ListResourceTypesUseCase()))
    app.include_router(create_accounts_router(account_service))
    app.include_router(create_courses_router(account_service))
    app.include_router(create_documents_router(account_service, material_service))
    app.include_router(create_generation_interpretation_router(interpret_generation, account_service))
    app.include_router(
        create_generation_requests_router(
            start_generation,
            get_generation,
            account_service,
            describe_generator(primary_generator),
            get_evidence,
        )
    )
    app.include_router(
        create_generation_plans_router(create_plan, get_plan, update_plan, approve_plan, account_service)
    )
    app.include_router(create_generations_router(account_service))
    app.include_router(
        create_resources_router(review_service, account_service, media_use_case, regenerate_media_use_case)
    )
    app.include_router(create_downloads_router(review_service, account_service))
    app.include_router(create_teacher_downloads_router(review_service, account_service))
    app.include_router(create_exports_router(export_use_case, account_service))
    app.include_router(create_health_router(check_dependencies))
    return app


app = create_application()