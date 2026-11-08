"""
EP-002 y HU-001: cuentas de docente, sesiones, cursos y archivos.
La extracción y procesamiento de texto reside en material_service.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import re
import secrets
import time
import zipfile
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

MAX_FILE_SIZE: int = 25 * 1024 * 1024
ALLOWED_DOCUMENT_TYPES: set[str] = {
    "Separata o apuntes de clase",
    "Diapositivas de clase",
    "Guía de práctica",
    "Sílabo de la unidad",
    "Transcripción de clase",
}
SESSION_DURATION_SECONDS: int = 8 * 3600
PBKDF2_ITERATIONS: int = 200000
EMAIL_REGEX: re.Pattern[str] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_password(password: str, salt: bytes) -> bytes:
    """Calcula el hash PBKDF2 de una contraseña usando SHA-256."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)


class AccountService:
    """Servicio de aplicación para autenticación docente, cursos y documentos base."""

    def __init__(
        self,
        repository: TeacherRepositoryPort,
        seed_email: str,
        seed_password: str,
        seed_demo_catalog: bool = True,
        default_name: str = "Docente",
    ) -> None:
        """
        Inicializa el servicio. seed_email y seed_password conforman la cuenta administrativa inicial.
        seed_demo_catalog siembra el curso de ejemplo en el primer inicio de sesión para pruebas.
        """
        self.repository = repository
        self.seed_email = seed_email.strip().lower()
        self.default_name = default_name
        self.seed_demo_catalog = seed_demo_catalog
        self._seed_salt = secrets.token_bytes(16)
        self._seed_password_hash = _hash_password(seed_password, self._seed_salt)

    def register_account(self, name: str, email: str, password: str) -> dict[str, Any]:
        """Registra un nuevo docente y crea una sesión activa."""
        normalized_email = email.strip().lower()
        cleaned_name = " ".join(str(name).split())

        if len(cleaned_name) < 2:
            raise AccountConfigurationError("INVALID_NAME", "Escribe tu nombre.", 422)
        if not EMAIL_REGEX.match(normalized_email):
            raise AccountConfigurationError("INVALID_EMAIL", "Escribe un correo válido.", 422)
        if len(password) < 8:
            raise AccountConfigurationError(
                "WEAK_PASSWORD", "La contraseña debe tener al menos 8 caracteres.", 422
            )
        if normalized_email == self.seed_email or self.repository.get_user_by_email(normalized_email):
            raise AccountConfigurationError(
                "ACCOUNT_EXISTS", "Ya existe una cuenta con ese correo. Inicia sesión.", 409
            )

        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        self.repository.create_user(
            {
                "email": normalized_email,
                "nombre": cleaned_name,
                "sal": salt.hex(),
                "clave": password_hash.hex(),
                "creado": datetime.now(timezone.utc).isoformat(),
            }
        )
        return self._open_session(normalized_email, cleaned_name)

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Autentica las credenciales del docente y genera una nueva sesión."""
        normalized_email = email.strip().lower()
        user_record = self.repository.get_user_by_email(normalized_email)

        if user_record:
            user_salt = bytes.fromhex(user_record["sal"])
            is_valid = hmac.compare_digest(
                _hash_password(password, user_salt).hex(), user_record["clave"]
            )
            display_name = user_record["nombre"]
        else:
            # Se calcula la huella para mantener el mismo tiempo de respuesta y evitar enumeración
            is_valid = (
                hmac.compare_digest(_hash_password(password, self._seed_salt), self._seed_password_hash)
                and bool(self.seed_email)
                and normalized_email == self.seed_email
            )
            display_name = self.default_name

        if not is_valid:
            raise AccountConfigurationError(
                "INVALID_CREDENTIALS", "Correo o contraseña incorrectos.", 401
            )

        if self.seed_demo_catalog and normalized_email == self.seed_email:
            self.repository.init_catalog(normalized_email)

        return self._open_session(normalized_email, display_name)

    def _open_session(self, email: str, name: str) -> dict[str, Any]:
        """Genera el token de sesión y lo persiste cifrado."""
        token = secrets.token_urlsafe(32)
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        expires_at = time.time() + SESSION_DURATION_SECONDS
        self.repository.save_session(fingerprint, email, expires_at)
        return {
            "email": email,
            "name": name,
            "token": token,
            "expiresIn": SESSION_DURATION_SECONDS,
        }

    def get_profile(self, email: str) -> dict[str, Any]:
        """Obtiene el perfil del docente autenticado."""
        user_record = self.repository.get_user_by_email(email)
        return {"email": email, "name": user_record["nombre"] if user_record else self.default_name}

    def authenticate_token(self, authorization_header: str | None) -> str:
        """Verifica la cabecera Bearer y retorna el correo del docente autenticado."""
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AccountConfigurationError("SESSION_REQUIRED", "Inicia sesión con el backend.", 401)
        raw_token = authorization_header[7:]
        fingerprint = hashlib.sha256(raw_token.encode()).hexdigest()
        session_info = self.repository.get_session(fingerprint)
        if not session_info or session_info[1] <= time.time():
            raise AccountConfigurationError(
                "SESSION_EXPIRED", "La sesión venció. Vuelve a iniciar sesión.", 401
            )
        return session_info[0]

    def logout(self, authorization_header: str | None) -> None:
        """Invalida la sesión activa en el repositorio."""
        self.authenticate_token(authorization_header)
        assert authorization_header is not None
        fingerprint = hashlib.sha256(authorization_header[7:].encode()).hexdigest()
        self.repository.delete_session(fingerprint)

    def get_unit(self, teacher_id: str, unit_id: str) -> dict[str, Any]:
        """Recupera una unidad verificando pertenencia al catálogo de cursos del docente."""
        found_unit = next(
            (u for course in self.repository.get_courses(teacher_id) for u in course["units"] if u["id"] == unit_id),
            None,
        )
        if not found_unit:
            raise AccountConfigurationError(
                "UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404
            )
        return found_unit

    def save_course(
        self, teacher_id: str, course_data: dict[str, Any], course_id: str | None = None
    ) -> dict[str, Any]:
        """Crea o actualiza la configuración de un curso y sus unidades de aprendizaje."""
        existing_courses = self.repository.get_courses(teacher_id)
        previous_course = next((c for c in existing_courses if c["id"] == course_id), None)
        if course_id and not previous_course:
            raise AccountConfigurationError("COURSE_NOT_FOUND", "El curso no existe.", 404)

        code = course_data["code"].strip().upper()
        if any(c["id"] != course_id and c["code"] == code for c in existing_courses):
            raise AccountConfigurationError(
                "DUPLICATE_CODE", "Ya existe un curso con ese código.", 409
            )

        previous_units = previous_course["units"] if previous_course else []
        incoming_unit_ids = [u.get("id") for u in course_data["units"] if u.get("id")]
        if len(set(incoming_unit_ids)) != len(incoming_unit_ids) or set(incoming_unit_ids) != {
            u["id"] for u in previous_units
        }:
            raise AccountConfigurationError(
                "INVALID_UNITS", "Conserva las unidades existentes y sus identificadores."
            )

        saved_course: dict[str, Any] = {
            "id": course_id or f"curso-{uuid4()}",
            **{key: course_data[key].strip() for key in ("code", "name", "term")},
        }
        saved_course["code"] = code

        for field_name in ("summary", "learningGoal"):
            incoming_val = course_data.get(field_name)
            saved_course[field_name] = (
                incoming_val.strip()
                if isinstance(incoming_val, str)
                else (previous_course or {}).get(field_name, "")
            )

        built_units: list[dict[str, Any]] = []
        max_number = max([u["number"] for u in previous_units], default=0)
        for unit_item in course_data["units"]:
            matched_prev = next((p for p in previous_units if p["id"] == unit_item.get("id")), None)
            if not matched_prev:
                max_number += 1
            unit_number = matched_prev["number"] if matched_prev else max_number
            built_units.append(
                {
                    "id": matched_prev["id"] if matched_prev else f"unidad-{uuid4()}",
                    "courseId": saved_course["id"],
                    "number": unit_number,
                    "title": unit_item["title"].strip(),
                    "outcomes": self._build_outcomes(
                        unit_item.get("outcomes"), matched_prev, unit_number
                    ),
                }
            )

        saved_course["units"] = built_units
        self.repository.save_course(teacher_id, saved_course)
        return saved_course

    @staticmethod
    def _build_outcomes(
        outcomes_input: list[dict[str, Any]] | None,
        previous_unit: dict[str, Any] | None,
        unit_number: int,
    ) -> list[dict[str, Any]]:
        """Construye y valida los resultados de aprendizaje respetando identificadores previos."""
        previous_outcomes = previous_unit["outcomes"] if previous_unit else []
        if outcomes_input is None:
            return previous_outcomes

        previous_ids = {item["id"] for item in previous_outcomes}
        result_outcomes: list[dict[str, Any]] = []
        used_ids: set[str] = set()

        for index, raw_item in enumerate(outcomes_input, start=1):
            cleaned_text = " ".join(str(raw_item.get("text", "")).split())
            if not cleaned_text:
                continue
            item_id = (
                raw_item.get("id")
                if raw_item.get("id") in previous_ids and raw_item.get("id") not in used_ids
                else f"ra-{uuid4().hex[:8]}"
            )
            used_ids.add(item_id)
            code = " ".join(str(raw_item.get("code") or "").split()) or f"RA{unit_number}.{index}"
            result_outcomes.append({"id": item_id, "code": code, "text": cleaned_text})

        return result_outcomes

    def register_document(
        self,
        teacher_id: str,
        file_name: str,
        file_content: bytes,
        context_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Valida e inicializa el registro binario de un documento docente."""
        unit = self.get_unit(teacher_id, context_data["unitId"])
        if not context_data["usePermission"]:
            raise AccountConfigurationError(
                "PERMISSION_REQUIRED", "Confirma el permiso de uso del material."
            )
        if context_data["documentType"] not in ALLOWED_DOCUMENT_TYPES:
            raise AccountConfigurationError("INVALID_TYPE", "Elige un tipo de documento válido.")

        selected_outcome_ids = context_data["outcomeIds"]
        unit_outcome_ids = {o["id"] for o in unit["outcomes"]}
        if not set(selected_outcome_ids).issubset(unit_outcome_ids) or (
            unit["outcomes"] and not selected_outcome_ids
        ):
            raise AccountConfigurationError(
                "INVALID_OUTCOME", "Selecciona resultados de aprendizaje de esta unidad."
            )

        if (
            not file_name
            or len(file_name) > 200
            or "/" in file_name
            or "\\" in file_name
            or any(ord(c) < 32 for c in file_name)
        ):
            raise AccountConfigurationError("INVALID_NAME", "Usa un nombre de archivo válido.")

        file_kind = file_name.rsplit(".", 1)[-1].lower()
        if file_kind not in ("pdf", "pptx", "txt"):
            raise AccountConfigurationError("INVALID_FORMAT", "Usa PDF, PPTX o TXT.")

        if not file_content or len(file_content) > MAX_FILE_SIZE:
            raise AccountConfigurationError(
                "INVALID_SIZE", "El archivo debe tener contenido y no superar 25 MB."
            )

        if file_kind == "pdf" and not file_content.startswith(b"%PDF-"):
            raise AccountConfigurationError(
                "INVALID_FORMAT", "El archivo no tiene cabecera PDF."
            )

        if file_kind == "pptx":
            try:
                with zipfile.ZipFile(io.BytesIO(file_content)) as archive:
                    entries = archive.namelist()
                    if "[Content_Types].xml" not in entries or "ppt/presentation.xml" not in entries:
                        raise ValueError()
            except (zipfile.BadZipFile, ValueError):
                raise AccountConfigurationError(
                    "INVALID_FORMAT", "El archivo no tiene estructura PPTX."
                )

        if file_kind == "txt":
            try:
                file_content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise AccountConfigurationError(
                    "INVALID_FORMAT", "Guarda el TXT con codificación UTF-8."
                )

        existing_documents = self.repository.get_documents(teacher_id)
        if any(
            doc["unitId"] == unit["id"] and doc["fileName"].casefold() == file_name.casefold()
            for doc in existing_documents
        ):
            raise AccountConfigurationError(
                "DUPLICATE_DOCUMENT", "Ya existe un documento con ese nombre en la unidad.", 409
            )

        created_document: dict[str, Any] = {
            **context_data,
            "id": f"doc-api-{uuid4()}",
            "fileName": file_name,
            "kind": file_kind,
            "sizeBytes": len(file_content),
            "status": "registrado",
            "currentStep": None,
            "registeredAt": datetime.now(timezone.utc).isoformat(),
            "processedAt": None,
            "fragmentCount": 0,
            "pageCount": None,
            "errorMessage": None,
            "isDemo": False,
            "source": "backend",
        }
        self.repository.save_document(teacher_id, created_document, file_content)
        return created_document

    def verify_generation_ownership(self, generation_id: str, authorization_header: str | None) -> None:
        """Comprueba que la solicitud de generación pertenezca al docente en sesión."""
        owner = self.repository.get_generation_owner(generation_id)
        if owner and self.authenticate_token(authorization_header) != owner:
            raise AccountConfigurationError(
                "GENERATION_NOT_FOUND", "La solicitud no existe.", 404
            )

    def list_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        """Lista los cursos configurados del docente."""
        return self.repository.get_courses(teacher_id)

    def delete_course(self, teacher_id: str, course_id: str) -> None:
        """Borra el curso y sus unidades completas en cascada."""
        courses = self.repository.get_courses(teacher_id)
        target = next((c for c in courses if c["id"] == course_id), None)
        if target is None:
            raise AccountConfigurationError("COURSE_NOT_FOUND", "El curso no existe.", 404)
        self.repository.delete_course(teacher_id, course_id, [u["id"] for u in target["units"]])

    def list_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        """Lista los documentos asociados al docente."""
        return self.repository.get_documents(teacher_id)

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes]:
        """Obtiene los metadatos y binario de un documento."""
        doc = self.repository.get_document(teacher_id, document_id)
        if doc is None:
            raise AccountConfigurationError(
                "DOCUMENT_NOT_FOUND", "El documento no existe.", 404
            )
        return doc

    def delete_document(self, teacher_id: str, document_id: str) -> None:
        """Elimina un documento tras verificar su existencia."""
        self.get_document(teacher_id, document_id)
        self.repository.delete_document(teacher_id, document_id)

    def list_generation_requests(self, teacher_id: str) -> list[dict[str, Any]]:
        """Obtiene el historial de solicitudes ordenadas de forma descendente."""
        return sorted(self.repository.get_history(teacher_id), key=lambda r: r["createdAt"], reverse=True)