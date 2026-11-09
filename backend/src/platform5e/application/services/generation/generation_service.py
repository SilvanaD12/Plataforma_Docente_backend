"""
HU-053 y HU-018: genera propuestas pedagógicas para revisión docente.
Recupera fragmentos relevantes del material procesado de la unidad (RAG)
y solicita la redacción con citas exactas al modelo o motor generador.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.evidence_retriever_port import EvidenceRetrieverPort
from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.ports.outbound.media_port import MediaGeneratorPort, MediaRepositoryPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import find_course_and_unit
from platform5e.application.services.media.media_attachment import attach_generated_media
from platform5e.application.services.generation.prompt_drafting import build_generation_context

# T013: la redacción de cada paso vive en step_drafting.py. Estos nombres se reexportan para los importadores actuales.
from platform5e.application.services.generation.step_drafting import (  # noqa: F401
    NO_REPEAT_INSTRUCTION,
    OPTION_LETTERS,
    REQUEST_PARAMETERS,
    SEQUENCE_PREVIEW_CHARS,
    build_grounding_report,
    build_resource_dict,
    draft_resources,
    draft_step,
    evidence_query_text,
    filter_repeated,
    previous_sequence,
    retrieval_limit,
    saved_parameters,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.distractor_reliability import reliability_report
from platform5e.domain.generation.resource_formats import resource_stage
from platform5e.domain.generation.sequence import (
    SequenceError,
    order_resource_types,
    stage_agent,
)

NO_MATERIAL_NOTICE: str = (
    "Esta unidad todavía no tiene material procesado. Sube un documento o busca el tema "
    "en la pestaña Material y vuelve a intentar."
)


class GenerationService:
    """Servicio de aplicación para orquestar la generación 5E con evidencia y respaldo."""

    def __init__(
        self,
        repository: GenerationRepositoryPort,
        teacher_repository: TeacherRepositoryPort | None = None,
        chunk_repository: ChunkRepositoryPort | None = None,
        primary_generator: ResourceGeneratorPort | None = None,
        fallback_generator: ResourceGeneratorPort | None = None,
        review_repository: ResourceReviewRepositoryPort | None = None,
        demo_examples_enabled: bool = True,
        evidence_retriever: EvidenceRetrieverPort | None = None,
        media_generator: MediaGeneratorPort | None = None,
        media_repository: MediaRepositoryPort | None = None,
    ) -> None:
        self._media_generator = media_generator
        self._media_repository = media_repository
        self._repository = repository
        self._evidence_retriever = evidence_retriever
        self._demo_examples_enabled = demo_examples_enabled
        self._review_repository = review_repository
        self._teacher_repository = teacher_repository
        self._chunk_repository = chunk_repository
        self._primary_generator = primary_generator
        self._fallback_generator = fallback_generator

    def generate(self, request_data: dict[str, Any], teacher_id: str | None = None) -> dict[str, Any]:
        """Genera un recurso o coordina una secuencia según los tipos solicitados."""
        if request_data.get("resourceTypes"):
            return self.generate_sequence(request_data, teacher_id)

        if (
            teacher_id
            and self._teacher_repository
            and self._chunk_repository
            and self._evidence_retriever
            and (self._primary_generator or self._fallback_generator)
        ):
            course, unit = self._get_course_and_unit(teacher_id, request_data["unitId"])
            if unit is not None:
                chunks = self._chunk_repository.get_chunks_by_unit(teacher_id, unit["id"])
                if chunks:
                    return self._generate_with_material(
                        request_data, teacher_id, course, unit, chunks
                    )

        if not self._demo_examples_enabled:
            raise GenerationError("NO_PROCESSED_MATERIAL", NO_MATERIAL_NOTICE)

        return self._generate_demo(request_data, teacher_id)

    def generate_sequence(self, request_data: dict[str, Any], teacher_id: str | None) -> dict[str, Any]:
        """HU-003: reparte un pedido con varios tipos entre los agentes de etapa, en el orden de la clase.

        Todos los agentes usan la misma evidencia recuperada y reciben lo que redactaron los anteriores. Un recurso
        demasiado parecido a otro de la secuencia se pide de nuevo una vez y, si sigue repetido, se rechaza.
        """
        try:
            ordered_types = order_resource_types(list(request_data.get("resourceTypes") or []))
        except SequenceError as error:
            raise GenerationError("INVALID_SEQUENCE", str(error)) from error

        if not (
            teacher_id
            and self._teacher_repository
            and self._chunk_repository
            and self._evidence_retriever
            and (self._primary_generator or self._fallback_generator)
        ):
            raise GenerationError("NO_PROCESSED_MATERIAL", NO_MATERIAL_NOTICE)
        course, unit = self._get_course_and_unit(teacher_id, request_data["unitId"])
        chunks = self._chunk_repository.get_chunks_by_unit(teacher_id, unit["id"]) if unit else []
        if unit is None or not chunks:
            raise GenerationError("NO_PROCESSED_MATERIAL", NO_MATERIAL_NOTICE)
        if request_data["outcomeId"] and not any(
            outcome["id"] == request_data["outcomeId"] for outcome in unit.get("outcomes", [])
        ):
            raise GenerationError("INVALID_OUTCOME", "El resultado de aprendizaje no pertenece a la unidad.")

        # Contexto compartido por todos los agentes: la misma evidencia de la unidad.
        top_k = retrieval_limit(request_data.get("topK"))
        selected_chunks = self._evidence_retriever.retrieve(
            query=self._build_query(unit, request_data),
            chunks=chunks,
            top_k=top_k,
            unit_id=unit["id"],
        )

        documents_map = {
            doc["id"]: doc
            for doc in self._teacher_repository.get_documents(teacher_id)
            if doc["unitId"] == unit["id"]
        }
        document_names = {doc_id: doc["fileName"] for doc_id, doc in documents_map.items()}

        timestamp = datetime.now(timezone.utc).isoformat()
        request_id = f"sol-api-{uuid4()}"
        resolved_outcome_id = request_data["outcomeId"] or next((o["id"] for o in unit.get("outcomes", [])), "")
        accepted: list[dict[str, Any]] = []  # recursos aceptados (formato del generador), con su etapa
        output_resources: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        warnings: list[str] = []
        generators: list[ResourceGeneratorPort] = []
        grounding_rejections: list[dict[str, Any]] = []

        for resource_type in ordered_types:
            agent = stage_agent(resource_type)
            step_request = {
                **request_data,
                "id": request_id,
                "createdAt": timestamp,
                "stage": resource_stage(resource_type),
                "resourceType": resource_type,
            }
            context = build_generation_context(course, unit, step_request, selected_chunks, document_names)
            context["secuenciaPrevia"] = previous_sequence(accepted)
            step_grounding: list[dict[str, Any]] = []
            drafted_step = draft_step(
                context, accepted, self._primary_generator, self._fallback_generator, step_grounding
            )
            kept, generator, warning = drafted_step.kept, drafted_step.generator, drafted_step.warning
            rejected = [item["reason"] for item in drafted_step.repeated]
            if warning:
                warnings.append(f"{agent}: {warning}")

            if generator is not None and kept:
                generators.append(generator)
            step_resources = [
                {
                    **self._build_resource_dict(
                        resource, step_request, unit["id"], resolved_outcome_id, generator.description, timestamp
                    ),
                    "agent": agent,
                }
                for resource in kept
                if generator is not None
            ]
            accepted += [{**resource, "etapa": step_request["stage"]} for resource in kept]
            output_resources += step_resources
            steps.append(
                {
                    "stage": step_request["stage"],
                    "resourceType": resource_type,
                    "agent": agent,
                    "generated": len(step_resources),
                    "rejected": rejected + [item["reason"] for item in step_grounding],
                }
            )
            grounding_rejections += step_grounding

            if step_resources:
                cited = {f_id for r in step_resources for c in r["citations"] for f_id in c["fragmentIds"]}
                cited |= {f_id for r in step_resources for o in (r["options"] or []) for f_id in o["sourceFragmentIds"]}
                step_chunks = [c for c in selected_chunks if c["id"] in cited]
                for resource in step_resources:
                    self._attach_media(teacher_id, resource)
                self._save_for_review(
                    teacher_id,
                    unit["id"],
                    step_resources,
                    step_chunks,
                    list(documents_map.values()),
                    step_request,
                    bool(getattr(generator, "uses_ai", False)),
                )

        if not output_resources:
            raise GenerationError(
                "INSUFFICIENT_EVIDENCE",
                "No se pudieron redactar recursos que citen el material sin repetirse. "
                "Prueba con otros tipos de recurso o agrega más material a la unidad."
                + _rejection_detail(grounding_rejections),
            )

        cited_ids = {f_id for r in output_resources for c in r["citations"] for f_id in c["fragmentIds"]}
        cited_ids |= {f_id for r in output_resources for o in (r["options"] or []) for f_id in o["sourceFragmentIds"]}
        used_chunks = [c for c in selected_chunks if c["id"] in cited_ids]
        associated_docs = [
            documents_map[doc_id]
            for doc_id in dict.fromkeys(c.get("documentId") or c.get("documento_id") for c in used_chunks)
            if doc_id in documents_map
        ]
        main_generator = generators[0]
        enriched_request = {
            **request_data,
            "id": request_id,
            "createdAt": timestamp,
            "stage": resource_stage(ordered_types[0]),
            "resourceType": ordered_types[0],
            "resourceTypes": ordered_types,
        }
        grounding_report = build_grounding_report(output_resources, grounding_rejections)
        rejected_total = sum(len(step["rejected"]) for step in steps) - len(grounding_rejections)
        notice = (
            f"Secuencia generada por {len({s['agent'] for s in steps if s['generated']})} agente(s) "
            f"con {main_generator.description} a partir de tu material."
        )
        if rejected_total:
            notice += f" Se descartaron {rejected_total} recurso(s) por repetir contenido de otra etapa."
        notice += _grounding_notice(grounding_report)
        if warnings:
            notice += " " + " ".join(warnings)

        result_payload: dict[str, Any] = {
            "mode": "rag",
            "notice": notice,
            "generator": {
                "description": main_generator.description,
                "usesAi": bool(getattr(main_generator, "uses_ai", False)),
                "fallback": bool(warnings),
            },
            "request": enriched_request,
            "resources": output_resources,
            "available": len(output_resources),
            "grounding": grounding_report,
            "distractorReliability": reliability_report(output_resources),
            "sequence": steps,
            "fragments": [
                {
                    "id": chunk["id"],
                    "documentId": chunk.get("documentId") or chunk.get("documento_id"),
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "unitId": unit["id"],
                    "outcomeId": resolved_outcome_id,
                    "text": chunk.get("text") or chunk.get("texto"),
                    "relevance": chunk.get("relevance", chunk.get("relevancia", 0.0)),
                }
                for chunk in used_chunks
            ],
            "documents": associated_docs,
            "retrievedChunks": [
                {
                    "id": chunk["id"],
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "text": chunk.get("text") or chunk.get("texto"),
                    "relevance": chunk.get("relevance", chunk.get("relevancia", 0.0)),
                }
                for chunk in selected_chunks
            ],
        }
        self._repository.save(result_payload, teacher_id)
        return result_payload

    @staticmethod
    def _filter_repeated(
        drafted: list[dict[str, Any]], accepted: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Separa los recursos nuevos de los que repiten contenido de otro recurso de la secuencia."""
        kept, rejected = filter_repeated(drafted, accepted)
        return kept, [item["reason"] for item in rejected]

    def _get_course_and_unit(
        self, teacher_id: str, unit_id: str
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Localiza el curso y la unidad dentro del repositorio de configuración."""
        assert self._teacher_repository is not None
        match = find_course_and_unit(self._teacher_repository.get_courses(teacher_id), unit_id)
        return match if match is not None else ({}, None)

    def _generate_with_material(
        self,
        request_data: dict[str, Any],
        teacher_id: str,
        course: dict[str, Any],
        unit: dict[str, Any],
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Orquesta la recuperación de evidencia (puerto de recuperación) y la redacción (puerto del modelo)."""
        assert self._teacher_repository is not None and self._evidence_retriever is not None
        if request_data["outcomeId"] and not any(
            outcome["id"] == request_data["outcomeId"] for outcome in unit.get("outcomes", [])
        ):
            raise GenerationError("INVALID_OUTCOME", "El resultado de aprendizaje no pertenece a la unidad.")

        query_text = self._build_query(unit, request_data)

        top_k = retrieval_limit(request_data.get("topK"))
        selected_chunks = self._evidence_retriever.retrieve(
            query=query_text,
            chunks=chunks,
            top_k=top_k,
            unit_id=unit["id"],
        )

        documents_map = {
            doc["id"]: doc
            for doc in self._teacher_repository.get_documents(teacher_id)
            if doc["unitId"] == unit["id"]
        }
        generation_context = build_generation_context(
            course,
            unit,
            request_data,
            selected_chunks,
            {doc_id: doc["fileName"] for doc_id, doc in documents_map.items()},
        )

        grounding_rejections: list[dict[str, Any]] = []
        resources, active_generator, warning_message = self._draft_resources(
            generation_context, grounding_rejections
        )

        if not resources or active_generator is None:
            raise GenerationError(
                "INSUFFICIENT_EVIDENCE",
                "No se pudieron redactar recursos que citen el material. "
                "Prueba con otro tipo de recurso o agrega más material a la unidad."
                + _rejection_detail(grounding_rejections),
            )

        current_timestamp = datetime.now(timezone.utc).isoformat()
        enriched_request = {**request_data, "id": f"sol-api-{uuid4()}", "createdAt": current_timestamp}
        resolved_outcome_id = request_data["outcomeId"] or next(
            (o["id"] for o in unit.get("outcomes", [])), ""
        )

        output_resources = [
            self._build_resource_dict(
                resource,
                enriched_request,
                unit["id"],
                resolved_outcome_id,
                active_generator.description,
                current_timestamp,
            )
            for resource in resources
        ]

        cited_fragment_ids = {
            f_id for r in output_resources for c in r["citations"] for f_id in c["fragmentIds"]
        }
        cited_fragment_ids |= {
            f_id for r in output_resources for opt in (r["options"] or []) for f_id in opt["sourceFragmentIds"]
        }

        used_chunks = [c for c in selected_chunks if c["id"] in cited_fragment_ids]
        associated_docs = [
            documents_map[doc_id]
            for doc_id in dict.fromkeys(
                chunk.get("documentId") or chunk.get("documento_id") for chunk in used_chunks
            )
            if doc_id in documents_map
        ]

        uses_ai = bool(getattr(active_generator, "uses_ai", False))
        for resource in output_resources:
            self._attach_media(teacher_id, resource)
        self._save_for_review(
            teacher_id,
            unit["id"],
            output_resources,
            used_chunks,
            associated_docs,
            enriched_request,
            uses_ai,
        )

        suffix_notice = f" {warning_message}" if warning_message else ""
        grounding_report = build_grounding_report(output_resources, grounding_rejections)
        result_payload: dict[str, Any] = {
            "mode": "rag",
            "notice": (
                f"Generado con {active_generator.description} a partir de tu material.{suffix_notice}"
                f"{_grounding_notice(grounding_report)}"
            ),
            "grounding": grounding_report,
            "distractorReliability": reliability_report(output_resources),
            "generator": {
                "description": active_generator.description,
                "usesAi": uses_ai,
                "fallback": warning_message is not None,
            },
            "request": enriched_request,
            "resources": output_resources,
            "available": len(output_resources),
            "fragments": [
                {
                    "id": chunk["id"],
                    "documentId": chunk.get("documentId") or chunk.get("documento_id"),
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "unitId": unit["id"],
                    "outcomeId": resolved_outcome_id,
                    "text": chunk.get("text") or chunk.get("texto"),
                    "relevance": chunk.get("relevance", chunk.get("relevancia", 0.0)),
                }
                for chunk in used_chunks
            ],
            "documents": associated_docs,
            "retrievedChunks": [
                {
                    "id": chunk["id"],
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "text": chunk.get("text") or chunk.get("texto"),
                    "relevance": chunk.get("relevance", chunk.get("relevancia", 0.0)),
                }
                for chunk in selected_chunks
            ],
        }

        self._repository.save(result_payload, teacher_id)
        return result_payload

    @staticmethod
    def _build_query(unit: dict[str, Any], request_data: dict[str, Any]) -> str:
        """Consulta de recuperación: título de la unidad, resultados elegidos, indicaciones y competencia."""
        return evidence_query_text(
            unit.get("title", ""),
            [
                outcome.get("text", "")
                for outcome in unit.get("outcomes", [])
                if not request_data["outcomeId"] or outcome["id"] == request_data["outcomeId"]
            ],
            request_data.get("instructions", ""),
            request_data.get("competency", ""),
        )

    def _draft_resources(
        self, generation_context: dict[str, Any], rejections: list[dict[str, Any]] | None = None
    ) -> tuple[list[dict[str, Any]], ResourceGeneratorPort | None, str | None]:
        """Pide la redacción al generador principal y, si no devuelve recursos válidos, al de respaldo."""
        return draft_resources(generation_context, self._primary_generator, self._fallback_generator, rejections)

    def _attach_media(self, teacher_id: str, resource: dict[str, Any]) -> None:
        """Genera la imagen o el audio del recurso. Si el servicio falla, deja el respaldo y la generación sigue."""
        attach_generated_media(teacher_id, resource, self._media_generator, self._media_repository)

    def _save_for_review(
        self,
        teacher_id: str,
        unit_id: str,
        output_resources: list[dict[str, Any]],
        used_chunks: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        request_data: dict[str, Any],
        uses_ai: bool,
    ) -> None:
        """Asocia la evidencia textual y parámetros congelados al recurso para su revisión posterior."""
        doc_names = {d["id"]: d.get("fileName", "") for d in documents}
        doc_origins = {d["id"]: d.get("origin") or {} for d in documents}
        chunks_by_id = {c["id"]: c for c in used_chunks}
        frozen_parameters = saved_parameters(request_data)

        for resource in output_resources:
            referenced_ids = [f_id for c in resource["citations"] for f_id in c["fragmentIds"]]
            referenced_ids += [
                f_id for opt in (resource["options"] or []) for f_id in opt["sourceFragmentIds"]
            ]

            evidence_list: list[dict[str, Any]] = []
            for f_id in dict.fromkeys(referenced_ids):
                if f_id in chunks_by_id:
                    matched_chunk = chunks_by_id[f_id]
                    doc_id = matched_chunk.get("documentId") or matched_chunk.get("documento_id")
                    evidence_list.append(
                        {
                            "id": f_id,
                            "text": matched_chunk.get("text") or matched_chunk.get("texto"),
                            "location": matched_chunk.get("location") or matched_chunk.get("ubicacion"),
                            "documentId": doc_id,
                            "documentName": doc_names.get(doc_id, ""),
                            "sourceUrl": doc_origins.get(doc_id, {}).get("url"),
                            "license": doc_origins.get(doc_id, {}).get("license"),
                        }
                    )

            resource["evidence"] = evidence_list
            resource["params"] = frozen_parameters
            resource["generatorKind"] = "ia" if uses_ai else "respaldo"

        if self._review_repository is not None:
            self._review_repository.save_resources(teacher_id, unit_id, output_resources)

    @staticmethod
    def _build_resource_dict(
        resource_data: dict[str, Any],
        request_data: dict[str, Any],
        unit_id: str,
        outcome_id: str,
        generator_name: str,
        timestamp: str,
    ) -> dict[str, Any]:
        """Crea el diccionario con formato estándar para la API de revisión docente."""
        return build_resource_dict(resource_data, request_data, unit_id, outcome_id, generator_name, timestamp)

    def _generate_demo(self, request_data: dict[str, Any], teacher_id: str | None = None) -> dict[str, Any]:
        """Genera resultados basados en el catálogo de demostración precargado."""
        demo_catalog = self._repository.get_demo_catalog()
        matched_unit = next(
            (u for u in demo_catalog["units"] if u["id"] == request_data["unitId"]), None
        )
        if matched_unit is None:
            raise GenerationError("NO_PROCESSED_MATERIAL", NO_MATERIAL_NOTICE)

        if request_data["outcomeId"] and not any(
            o["id"] == request_data["outcomeId"] for o in matched_unit["outcomes"]
        ):
            raise GenerationError("INVALID_OUTCOME", "El resultado de aprendizaje no pertenece a la unidad.")

        available_examples = [
            ex
            for ex in demo_catalog["examples"]
            if ex["unitId"] == request_data["unitId"]
            and ex["stage"] == request_data["stage"]
            and ex["type"] == request_data["resourceType"]
            and (request_data["outcomeId"] is None or ex["outcomeId"] == request_data["outcomeId"])
        ]

        if request_data["stage"] == "evaluate":
            available_examples = [
                ex for ex in available_examples if len(ex.get("options", [])) == request_data["optionCount"]
            ]

        if not available_examples:
            raise GenerationError(
                "INSUFFICIENT_EVIDENCE",
                "La API de demostración no tiene ejemplos para esta combinación de unidad, etapa y tipo.",
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        enriched_request = {**request_data, "id": f"sol-api-{uuid4()}", "createdAt": timestamp}
        demo_resources: list[dict[str, Any]] = []
        referenced_fragments: set[str] = set()

        for original_example in available_examples[: request_data["quantity"]]:
            cloned = deepcopy(original_example)
            rec_id = f"rec-api-{uuid4()}"
            rebased_citations = []
            for cit in cloned["citations"]:
                referenced_fragments.update(cit["fragmentIds"])
                rebased_citations.append(
                    {**cit, "fragmentIds": [f"api-demo:{fid}" for fid in cit["fragmentIds"]]}
                )

            rebased_options = None
            if cloned.get("options") is not None:
                rebased_options = []
                for opt in cloned["options"]:
                    referenced_fragments.update(opt["sourceFragmentIds"])
                    rebased_options.append(
                        {
                            **opt,
                            "id": f"{rec_id}:{opt['id']}",
                            "sourceFragmentIds": [f"api-demo:{fid}" for fid in opt["sourceFragmentIds"]],
                            "decision": "pendiente",
                            "discardReason": None,
                            "edited": False,
                            "reliabilityWarning": opt.get("reliabilityWarning"),
                        }
                    )

            demo_resources.append(
                {
                    **{
                        k: cloned[k]
                        for k in ("exampleId", "unitId", "outcomeId", "stage", "type", "title", "body")
                    },
                    "id": rec_id,
                    "requestId": enriched_request["id"],
                    "source": "api_demo",
                    "options": rebased_options,
                    "citations": rebased_citations,
                    "status": "pendiente",
                    "edited": False,
                    "discardReason": None,
                    "createdAt": timestamp,
                    "updatedAt": timestamp,
                    "decidedAt": None,
                }
            )

        matched_fragments = [f for f in demo_catalog["fragments"] if f["id"] in referenced_fragments]
        if {f["id"] for f in matched_fragments} != referenced_fragments:
            raise GenerationError(
                "INSUFFICIENT_EVIDENCE",
                "Faltan fragmentos de demostración para sustentar la propuesta.",
            )

        matched_doc_ids = {f["documentId"] for f in matched_fragments}
        matched_documents = [d for d in demo_catalog["documents"] if d["id"] in matched_doc_ids]
        if {d["id"] for d in matched_documents} != matched_doc_ids:
            raise GenerationError(
                "INSUFFICIENT_EVIDENCE",
                "Falta el documento de origen de la evidencia de demostración.",
            )

        result_payload: dict[str, Any] = {
            "mode": "api_demo",
            "notice": demo_catalog["notice"],
            "request": enriched_request,
            "resources": demo_resources,
            "available": len(available_examples),
            "fragments": [
                {
                    **frag,
                    "id": f"api-demo:{frag['id']}",
                    "documentId": f"api-demo:{frag['documentId']}",
                }
                for frag in matched_fragments
            ],
            "documents": [{**doc, "id": f"api-demo:{doc['id']}"} for doc in matched_documents],
        }

        self._repository.save(result_payload, teacher_id)
        return result_payload

    def get_by_id(self, generation_id: str) -> dict[str, Any]:
        """Recupera una generación previamente procesada."""
        result = self._repository.get_by_id(generation_id)
        if result is None:
            raise GenerationError("GENERATION_NOT_FOUND", "La solicitud de generación no existe.")
        return result


def _grounding_notice(report: dict[str, Any]) -> str:
    rejected = len(report["rejectedResources"])
    removed = report["unsupportedClaims"]
    paragraphs = report.get("unsupportedParagraphs", 0)
    if not removed and not paragraphs:
        return ""
    pieces = [f"{removed} afirmación(es)"] if removed else []
    if paragraphs:
        pieces.append(f"{paragraphs} párrafo(s)")
    parts = [f" Se quitaron {' y '.join(pieces)} sin respaldo en el material"]
    if rejected:
        parts.append(f" y se rechazaron {rejected} recurso(s)")
    return "".join(parts) + "."


def _rejection_detail(rejections: list[dict[str, Any]]) -> str:
    if not rejections:
        return ""
    return " Motivo: " + " ".join(item["reason"] for item in rejections[:3])