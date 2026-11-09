"""
HU-010 y HU-052: revisión docente persistida en base de datos e historial de descargas.
Permite validar que un recurso cumpla las condiciones pedagógicas de aprobación
(clave correcta definida y mínimo dos distractores aceptados).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.resource_regeneration_port import (
    RegenerationStatus,
    ResourceRegenerationPort,
)
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.domain.review.errors import RegenerationFailedError
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import AccountConfigurationError, find_course_and_unit
from platform5e.application.services.media.media_attachment import EDITED_NOTES, fallback_media
from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION
from platform5e.domain.generation.resource_formats import needs_structure, normalize_structure, structure_problems
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.media_change import media_source_changed
from platform5e.application.services.review.legacy_verification import upgrade_resource_verification
from platform5e.domain.review.resource_verification import (
    INSUFFICIENT,
    PENDING,
    assess_edited_distractors,
    incomplete_copy_reason,
    stored_threshold,
    verify_resource,
)

MIN_ACCEPTED_DISTRACTORS: int = 2
ALLOWED_REVIEW_STATUSES: set[str] = {"pendiente", "aprobado", "descartado"}
ALLOWED_OPTION_DECISIONS: set[str] = {"pendiente", "aceptado", "descartado"}
ALLOWED_DISCARD_REASONS: set[str] = {
    "sin_sentido",
    "tambien_correcto",
    "duplicado",
    "fuera_de_unidad",
    "otro",
    "regenerado",
}
MAX_DOWNLOADS_HISTORY: int = 50


def validate_approval_blockers(resource_data: dict[str, Any]) -> list[str]:
    """Evalúa las reglas de negocio para determinar si un recurso puede ser aprobado."""
    reasons: list[str] = []
    if not str(resource_data.get("body", "")).strip():
        reasons.append("El contenido no puede estar vacío.")

    options = resource_data.get("options")
    if options:
        distractors = [opt for opt in options if not opt.get("isCorrect")]
        pending_count = sum(opt.get("decision") == "pendiente" for opt in distractors)
        if pending_count:
            reasons.append(
                "Decide el distractor pendiente para poder aprobar." if pending_count == 1
                else f"Decide los {pending_count} distractores pendientes para poder aprobar."
            )
        elif sum(opt.get("decision") == "aceptado" for opt in distractors) < MIN_ACCEPTED_DISTRACTORS:
            reasons.append(
                f"Acepta al menos {MIN_ACCEPTED_DISTRACTORS} distractores para poder aprobar."
            )

        if not any(opt.get("isCorrect") and str(opt.get("text", "")).strip() for opt in options):
            reasons.append("La pregunta necesita una respuesta correcta.")

    if resource_data.get("type"):
        reasons += structure_problems(resource_data["type"], resource_data.get("structure"))
    media = resource_data.get("media") or {}
    if media.get("status") == "ready" and media.get("outdated"):
        reasons.append("El archivo no coincide con el texto editado: genéralo de nuevo para poder aprobar.")
    if media.get("invalidated"):
        reasons.append("Cambiaste el guion o la descripción: genera el archivo de nuevo para poder aprobar.")
    return reasons


def verification_blockers(resource_data: dict[str, Any]) -> list[str]:
    """REV-C3, C5 y C11: motivo por el que la verificación no permite aprobar.

    Sin `verification` no hay bloqueo que mostrar: el guardado verifica la versión editada antes de evaluar la
    aprobación, así que al aprobar siempre existe (opción A del bloque c).
    """
    verification = resource_data.get("verification")
    if not isinstance(verification, dict):
        return []
    if verification.get("fingerprint") != content_fingerprint(resource_data):
        return ["La comprobación del respaldo corresponde a otra versión del contenido: guarda el recurso para comprobarlo de nuevo."]
    reason = verification.get("reason") or ""
    if verification.get("status") == INSUFFICIENT:
        return [f"El respaldo es insuficiente: {reason}".strip()]
    if verification.get("status") == PENDING:
        return [f"La comprobación del respaldo está pendiente: {reason}".strip()]
    return []


def approval_blockers(resource_data: dict[str, Any]) -> list[str]:
    """Todos los motivos que impiden aprobar: las reglas pedagógicas y la verificación vigente."""
    return validate_approval_blockers(resource_data) + verification_blockers(resource_data)


def _same_finished_attempt(stored: dict[str, Any], record: dict[str, Any]) -> bool:
    """El pedido guardado es el mismo intento y ya terminó: no se sobrescribe (revisión de Silvana en el PR #13)."""
    if stored.get("status") not in ("succeeded", "failed"):
        return False
    if stored.get("attemptId") and record.get("attemptId"):
        return stored["attemptId"] == record["attemptId"]
    return bool(stored.get("requestId")) and stored.get("requestId") == record.get("requestId")


def _regeneration_response(resource_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "previousResourceId": resource_id,
        "previousDiscarded": bool(record.get("previousDiscarded")),
        "newResourceIds": list(record.get("newResourceIds") or []),
        "status": record.get("status"),
    }


class ResourceReviewService:
    """Servicio de aplicación para la gestión del ciclo de vida de revisión y descargas."""

    def __init__(
        self,
        teacher_repository: TeacherRepositoryPort,
        review_repository: ResourceReviewRepositoryPort,
        regeneration: ResourceRegenerationPort | None = None,
    ) -> None:
        self._teacher_repository = teacher_repository
        self._review_repository = review_repository
        self._regeneration = regeneration

    def _verify_unit_access(self, teacher_id: str, unit_id: str) -> None:
        """Comprueba que la unidad académica pertenezca al docente en sesión."""
        courses = self._teacher_repository.get_courses(teacher_id)
        if find_course_and_unit(courses, unit_id) is None:
            raise AccountConfigurationError(
                "UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404
            )

    def get_resource(self, teacher_id: str, unit_id: str, resource_id: str) -> dict[str, Any]:
        """Un recurso de la unidad del docente (404 si no existe o es de otra unidad)."""
        return self._get_resource_or_fail(teacher_id, unit_id, resource_id)

    def _get_resource_or_fail(
        self, teacher_id: str, unit_id: str, resource_id: str
    ) -> dict[str, Any]:
        """Recupera un recurso específico verificando tenencia de unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        resource = self._review_repository.get_resource_by_id(teacher_id, resource_id)
        if resource is None or resource.get("unitId") != unit_id:
            raise AccountConfigurationError(
                "RESOURCE_NOT_FOUND", "El recurso no existe.", 404
            )
        return upgrade_resource_verification(self._review_repository, teacher_id, unit_id, resource)

    def list_resources(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista los recursos de una unidad ordenados por fecha de creación descendente."""
        self._verify_unit_access(teacher_id, unit_id)
        resources = [
            upgrade_resource_verification(self._review_repository, teacher_id, unit_id, resource)
            for resource in self._review_repository.get_resources_by_unit(teacher_id, unit_id)
        ]
        return sorted(resources, key=lambda r: r.get("createdAt", ""), reverse=True)

    def retry_verification(
        self, teacher_id: str, unit_id: str, resource_id: str, expected_version: int
    ) -> dict[str, Any]:
        """REV-C3: «Reintentar comprobación» de una comprobación pendiente, sobre la misma versión y sin editar.

        Usa la regla vigente, el `evidenceThreshold` guardado y solo la copia histórica. No cambia la versión.
        """
        existing = self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        verification = existing.get("verification") or {}
        if verification.get("status") != PENDING:
            raise AccountConfigurationError(
                "VERIFICATION_NOT_PENDING", "Solo se puede reintentar una comprobación pendiente.", 409
            )
        if not verification.get("retryAvailable") or incomplete_copy_reason(existing):
            raise AccountConfigurationError(
                "REGENERATION_REQUIRED",
                incomplete_copy_reason(existing) or "La comprobación no se puede reintentar: regenera el recurso.",
                409,
            )
        checked = {
            **existing,
            "verification": verify_resource(
                existing, stored_threshold(existing), VERIFICATION_RULE_VERSION, previous=verification
            ),
        }
        if not self._review_repository.save_resource_if_version(
            teacher_id, unit_id, checked, expected_version, increment=False
        ):
            raise AccountConfigurationError(
                "VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de reintentar.", 409
            )
        return checked

    def update_resource(
        self,
        teacher_id: str,
        unit_id: str,
        resource_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica y persiste las modificaciones y decisiones del docente sobre el recurso."""
        existing = self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        # REV-C14: la versión de partida se compara primero con la guardada, antes de validar y de evaluar la
        # aprobación, para que una pestaña desactualizada reciba VERSION_CONFLICT y no un bloqueo de su contenido
        # viejo. El UPDATE condicional del final sigue cubriendo un guardado de otra pestaña entre lectura y escritura.
        expected_version = changes.get("expectedVersion")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise AccountConfigurationError(
                "VERSION_REQUIRED", "Indica la versión del recurso de la que parte el guardado.", 422
            )
        if expected_version != existing.get("version", 1):
            raise AccountConfigurationError(
                "VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de guardar.", 409
            )

        status = changes["status"]
        if status not in ALLOWED_REVIEW_STATUSES:
            raise AccountConfigurationError(
                "INVALID_STATUS", "El estado del recurso no es válido.", 422
            )

        discard_reason = changes.get("discardReason")
        if discard_reason is not None and discard_reason not in ALLOWED_DISCARD_REASONS:
            raise AccountConfigurationError("INVALID_REASON", "Elige un motivo de la lista.", 422)

        updated_resource: dict[str, Any] = {
            **existing,
            "title": changes["title"],
            "body": changes["body"],
            "edited": bool(changes.get("edited")),
        }
        incoming_html = changes.get("bodyHtml")
        if changes["body"] != existing.get("body") and incoming_html in (None, existing.get("bodyHtml")):
            # El cuerpo cambió y no llegó un HTML nuevo: el guardado es del texto anterior. Se borra para que la
            # revisión y los exportadores (SCORM, documento) usen el cuerpo vigente.
            updated_resource["bodyHtml"] = None
        elif "bodyHtml" in changes:
            # Ya llega limpio (sin scripts ni atributos peligrosos) desde el adaptador HTTP.
            updated_resource["bodyHtml"] = incoming_html or None
        if changes.get("structure") is not None:
            if not needs_structure(existing.get("type", "")):
                raise AccountConfigurationError(
                    "INVALID_STRUCTURE", "Este tipo de recurso no tiene elementos para editar.", 422
                )
            structure = normalize_structure(existing["type"], changes["structure"])
            if structure is None:
                raise AccountConfigurationError(
                    "INVALID_STRUCTURE", "Completa todos los elementos de la actividad antes de guardar.", 422
                )
            media = existing.get("media") or {}
            if media.get("status") == "ready" and media_source_changed(existing["type"], existing.get("structure"), structure):
                # REV-C8: el archivo se generó con el guion o la descripción anterior y deja de usarse, para que la
                # revisión y el SCORM no mezclen el texto nuevo con el audio o la imagen viejos. Si cambian solo `alt`
                # o `caption`, el archivo se conserva. Hasta generarlo de nuevo, la aprobación queda bloqueada y el
                # recurso no entra en exportaciones nuevas (D9, opción A).
                updated_resource["media"] = {
                    **fallback_media(existing["format"], EDITED_NOTES[existing["format"]]),
                    "invalidated": True,
                }
            updated_resource["structure"] = structure

        options = existing.get("options")
        if options is not None:
            incoming_options = changes.get("options")
            if incoming_options is None or sorted(o["id"] for o in incoming_options) != sorted(
                o["id"] for o in options
            ):
                raise AccountConfigurationError(
                    "INVALID_OPTIONS", "Las alternativas no coinciden con el recurso.", 422
                )

            options_by_id = {opt["id"]: opt for opt in incoming_options}
            updated_options = []
            for original_opt in options:
                target = options_by_id[original_opt["id"]]
                if target["decision"] not in ALLOWED_OPTION_DECISIONS or (
                    target.get("discardReason") is not None
                    and target["discardReason"] not in ALLOWED_DISCARD_REASONS
                ):
                    raise AccountConfigurationError(
                        "INVALID_DECISION",
                        "La decisión sobre la alternativa no es válida.",
                        422,
                    )

                decision = "pendiente" if original_opt["isCorrect"] else target["decision"]
                updated_options.append(
                    {
                        **original_opt,
                        "text": target["text"],
                        "feedback": target.get("feedback", ""),
                        "decision": decision,
                        "discardReason": target.get("discardReason")
                        if decision == "descartado"
                        else None,
                        "edited": bool(target.get("edited")),
                    }
                )
            updated_resource["options"] = updated_options
            # REV-C4: un distractor cuyo texto cambió se evalúa de nuevo contra la copia histórica.
            edited_ids = {
                o["id"] for o in options if not o.get("isCorrect") and options_by_id[o["id"]]["text"] != o.get("text")
            }
            warnings = assess_edited_distractors(updated_resource, edited_ids)
            updated_resource["options"] = [
                {**o, "reliabilityWarning": warnings[o["id"]]} if o["id"] in warnings else o for o in updated_options
            ]

        # REV-C1, C2 y C5: se verifica de nuevo solo si cambió el contenido verificable o si el resultado guardado es de
        # otra versión. Un recurso aprobado cuyo contenido cambió vuelve a revisión y necesita otra aprobación manual.
        fingerprint = content_fingerprint(updated_resource)
        review_reset = existing.get("status") == "aprobado" and fingerprint != content_fingerprint(existing)
        if review_reset:
            status = "pendiente"

        updated_resource["version"] = expected_version + 1

        stored = existing.get("verification")
        if isinstance(stored, dict) and stored.get("fingerprint") == fingerprint:
            updated_resource["verification"] = stored
        else:
            updated_resource["verification"] = verify_resource(
                updated_resource, stored_threshold(existing), VERIFICATION_RULE_VERSION, previous=stored
            )

        # La aprobación se evalúa con la verificación de la versión editada, ya calculada.
        if status == "aprobado":
            blockers = approval_blockers(updated_resource)
            if blockers:
                raise AccountConfigurationError("APPROVAL_BLOCKED", blockers[0], 409)

        current_time = datetime.now(timezone.utc).isoformat()
        if status != existing.get("status"):
            updated_resource["decidedAt"] = current_time if status != "pendiente" else None

        updated_resource["status"] = status
        updated_resource["discardReason"] = discard_reason if status == "descartado" else None
        updated_resource["updatedAt"] = current_time

        if not self._review_repository.save_resource_if_version(teacher_id, unit_id, updated_resource, expected_version):
            raise AccountConfigurationError(
                "VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de guardar.", 409
            )
        return {**updated_resource, "reviewReset": review_reset}

    def delete_resource(self, teacher_id: str, unit_id: str, resource_id: str) -> None:
        """Elimina un recurso del repositorio."""
        self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        self._review_repository.delete_resource(teacher_id, resource_id)

    def get_summary(self, teacher_id: str) -> list[dict[str, Any]]:
        """Genera el consolidado de recursos pendientes y aprobados por unidad."""
        summary_list: list[dict[str, Any]] = []
        for course in self._teacher_repository.get_courses(teacher_id):
            for unit in course["units"]:
                resources = self._review_repository.get_resources_by_unit(teacher_id, unit["id"])
                summary_list.append(
                    {
                        "courseId": course["id"],
                        "unitId": unit["id"],
                        "approved": sum(r.get("status") == "aprobado" for r in resources),
                        "pending": sum(r.get("status") == "pendiente" for r in resources),
                    }
                )
        return summary_list

    def get_downloads_history(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista las descargas recientes de la unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        return sorted(
            self._review_repository.get_downloads(teacher_id, unit_id),
            key=lambda d: d["createdAt"],
            reverse=True,
        )[:MAX_DOWNLOADS_HISTORY]

    def get_teacher_downloads(self, teacher_id: str) -> list[dict[str, Any]]:
        """REV-C9: el historial del docente, que se conserva al borrar el curso (solo el registro, no el archivo).

        Los registros anteriores a REV-01 no guardaban el curso ni la unidad: si la unidad todavía existe, se completan
        con sus nombres actuales; si no, quedan sin nombre y la interfaz muestra «Curso eliminado».
        """
        units = {
            unit["id"]: {"courseId": course["id"], "courseName": course.get("name"),
                         "unitName": unit.get("title"), "unitNumber": unit.get("number")}
            for course in self._teacher_repository.get_courses(teacher_id)
            for unit in course.get("units", [])
        }
        records = []
        for record in self._review_repository.get_downloads_by_teacher(teacher_id):
            if record.get("courseName") is None and record.get("unitId") in units:
                record = {**record, **units[record["unitId"]]}
            records.append(record)
        return sorted(records, key=lambda d: d.get("createdAt", ""), reverse=True)[:MAX_DOWNLOADS_HISTORY]

    def regenerate_resource(
        self, teacher_id: str, unit_id: str, resource_id: str, expected_version: int
    ) -> dict[str, Any]:
        """REV-C12 y REV-C13: pide a Generación un recurso nuevo y descarta el anterior solo si sigue en la versión
        registrada. Decisión provisional D10 (sin confirmación de Generación).

        - Antes de pedirlo, reserva el pedido de forma atómica y registra en el anterior `regeneration` con la versión
          de partida. Pedirlo otra vez desde la misma versión, incluso al mismo tiempo, devuelve el mismo resultado sin
          generar de nuevo (salvo que el pedido anterior haya fallado, que libera la reserva).
        - Si termina bien, los recursos nuevos guardan `regeneratedFrom` y se verifican al leerlos, como los antiguos.
          El anterior pasa a `descartado` con `discardReason = "regenerado"` con un guardado condicional: si el
          docente lo editó mientras tanto, no se toca y los dos quedan en Revisión.
        - Si falla, el anterior queda como estaba (su contenido y su versión) y se informa el motivo.
        """
        existing = self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        if self._regeneration is None:
            raise AccountConfigurationError(
                "REGENERATION_UNAVAILABLE", "La regeneración no está disponible en el servidor.", 503
            )
        record = existing.get("regeneration") or {}
        if record.get("fromVersion") == expected_version and record.get("status") in ("running", "succeeded"):
            return _regeneration_response(resource_id, record)
        if existing.get("version", 1) != expected_version:
            raise AccountConfigurationError(
                "VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de regenerarlo.", 409
            )

        # La reserva es atómica: si dos solicitudes llegan a la vez desde la misma versión, solo una la consigue y
        # la otra devuelve el pedido en curso sin generar otro recurso.
        record = {"fromVersion": expected_version, "attemptId": f"intento-{uuid4()}", "requestId": None,
                  "status": "running", "newResourceIds": []}
        if not self._review_repository.claim_regeneration(
            teacher_id, unit_id, {**existing, "regeneration": record}, expected_version
        ):
            latest = self._review_repository.get_resource_by_id(teacher_id, resource_id) or {}
            claimed = latest.get("regeneration") or {}
            if claimed.get("fromVersion") == expected_version and claimed.get("status") in ("running", "succeeded"):
                return _regeneration_response(resource_id, claimed)
            raise AccountConfigurationError(
                "VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de regenerarlo.", 409
            )

        params = {**(existing.get("params") or {}), "unitId": unit_id}
        outcome = self._regeneration.request_regeneration(teacher_id, resource_id, expected_version, params)
        return self._apply_regeneration_outcome(teacher_id, unit_id, resource_id, record, outcome, raise_on_failure=True)

    def get_regeneration_status(self, teacher_id: str, unit_id: str, resource_id: str) -> dict[str, Any]:
        """D10 (confirmada por Yan): estado del último pedido de regeneración del recurso.

        Si sigue en curso, consulta a Generación con `get_regeneration`: al ver `succeeded` hace el descarte condicional
        del anterior (REV-C12) y al ver `failed` registra el motivo y libera la reserva (REV-C13). Consultar otra vez
        un pedido terminado devuelve lo mismo sin repetir nada.
        """
        existing = self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        record = existing.get("regeneration") or {}
        if not record:
            raise AccountConfigurationError(
                "REGENERATION_NOT_FOUND", "Este recurso no tiene una regeneración pedida.", 404
            )
        if record.get("status") in ("pending", "running") and record.get("requestId") and self._regeneration:
            outcome = self._regeneration.get_regeneration(teacher_id, record["requestId"])
            if outcome is None:
                outcome = RegenerationStatus(
                    record["requestId"], "failed", (), "Generación ya no tiene este pedido. Pide la regeneración otra vez."
                )
            record = self._apply_regeneration_outcome(
                teacher_id, unit_id, resource_id, record, outcome, raise_on_failure=False, as_record=True
            )
        return {**_regeneration_response(resource_id, record), "reason": record.get("reason"), "code": record.get("code")}

    def _apply_regeneration_outcome(
        self,
        teacher_id: str,
        unit_id: str,
        resource_id: str,
        record: dict[str, Any],
        outcome: RegenerationStatus,
        raise_on_failure: bool,
        as_record: bool = False,
    ) -> dict[str, Any]:
        """Aplica el estado que devolvió Generación al pedido registrado en el recurso anterior.

        - `pending` o `running`: el pedido sigue en curso; se guarda su id y se conserva la reserva.
        - `failed`: se registra el motivo y se libera la reserva; el anterior queda como estaba (REV-C13).
        - `succeeded`: los nuevos guardan `regeneratedFrom` y el anterior se descarta solo si sigue en la versión de
          partida; si no, los dos quedan en Revisión (REV-C12).
        """
        expected_version = record["fromVersion"]
        record = {**record, "requestId": outcome.request_id, "newResourceIds": list(outcome.new_resource_ids)}

        if outcome.status in ("pending", "running"):
            record = self._record_regeneration(teacher_id, unit_id, resource_id, {**record, "status": "running"})
            return record if as_record else _regeneration_response(resource_id, record)

        if outcome.status != "succeeded":
            reason = outcome.reason or "La regeneración no terminó bien."
            failed = {**record, "status": "failed", "reason": reason, "code": outcome.code}
            record = self._record_regeneration(teacher_id, unit_id, resource_id, failed)
            if record is failed:  # si otra consulta ya cerró este intento, o hay uno nuevo, se devuelve lo guardado
                self._review_repository.release_regeneration(teacher_id, unit_id, resource_id, failed["attemptId"])
                if raise_on_failure:
                    raise RegenerationFailedError(reason, outcome.code)
            return record if as_record else _regeneration_response(resource_id, record)

        record = {**record, "status": "succeeded"}
        for new_id in outcome.new_resource_ids:
            new = self._review_repository.get_resource_by_id(teacher_id, new_id)
            if new is not None:
                self._review_repository.save_resource_if_version(
                    teacher_id, unit_id,
                    {**new, "regeneratedFrom": {"resourceId": resource_id, "version": expected_version}},
                    new.get("version", 1), increment=False,
                )

        latest = self._review_repository.get_resource_by_id(teacher_id, resource_id) or {}
        now = datetime.now(timezone.utc).isoformat()
        discarded = {**latest, "status": "descartado", "discardReason": "regenerado", "decidedAt": now,
                     "updatedAt": now, "regeneration": {**record, "previousDiscarded": True}}
        if latest.get("version", 1) == expected_version and self._review_repository.save_resource_if_attempt(
            teacher_id, unit_id, discarded, expected_version, record["attemptId"], increment=True
        ):
            record = discarded["regeneration"]
        else:
            # No se descartó: el docente lo editó, otra consulta ya terminó este intento y lo descartó, o hay un intento
            # más nuevo. En los dos últimos casos se devuelve lo guardado en lugar de sobrescribirlo.
            record = self._record_regeneration(teacher_id, unit_id, resource_id, {**record, "previousDiscarded": False})
        return record if as_record else _regeneration_response(resource_id, record)

    def _record_regeneration(
        self, teacher_id: str, unit_id: str, resource_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Guarda el estado del pedido en el recurso anterior sin cambiar su versión ni su contenido.

        No sobrescribe un intento que ya terminó (`succeeded` o `failed`): si dos consultas del mismo pedido se solapan,
        la segunda devuelve lo que guardó la primera. Tampoco escribe sobre un intento más nuevo (revisión de Silvana en
        el PR #17): la escritura compara la versión y el `attemptId` vigente en el mismo UPDATE; si alguno cambió entre
        la lectura y la escritura, se vuelve a leer. Devuelve el registro que quedó guardado.
        """
        for _ in range(5):
            latest = self._review_repository.get_resource_by_id(teacher_id, resource_id)
            if latest is None:
                return record
            stored = latest.get("regeneration") or {}
            if stored.get("attemptId") != record.get("attemptId") or _same_finished_attempt(stored, record):
                return stored
            if self._review_repository.save_resource_if_attempt(
                teacher_id, unit_id, {**latest, "regeneration": record}, latest.get("version", 1), record["attemptId"]
            ):
                return record
        return record

    def clear_downloads_history(self, teacher_id: str, unit_id: str) -> None:
        """Elimina el registro histórico de descargas de una unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        self._review_repository.delete_downloads(teacher_id, unit_id)

