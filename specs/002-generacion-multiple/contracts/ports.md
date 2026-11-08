# Puertos de Generación (GEN-01)

[Plan](../plan.md) · [Research R5](../research.md#r5-puertos-hacia-otros-módulos) · [Modelo de datos](../data-model.md)

Todos los puertos se declaran como `typing.Protocol` en `backend/src/platform5e/application/ports/outbound/`. Los adaptadores se inyectan en `main.py`. Los tipos de datos son `dataclass(frozen=True)` en `domain/generation/` o en el dominio del módulo dueño. Las firmas siguientes son el acuerdo que se propone a cada responsable.

## Hacia otros módulos

### UnitMembershipPort (CC-01 · Cuentas y Cursos)

```python
@dataclass(frozen=True)
class OutcomeRef:
    id: str
    code: str
    text: str

@dataclass(frozen=True)
class UnitContext:
    course_id: str
    course_name: str
    course_summary: str
    learning_goal: str
    unit_id: str
    unit_number: int | None
    unit_title: str
    outcomes: tuple[OutcomeRef, ...]

class UnitMembershipPort(Protocol):
    def get_unit_context(self, teacher_id: str, unit_id: str) -> UnitContext | None:
        """Unidad del docente con los datos que necesita el prompt. Devuelve None si no existe o es ajena."""
```

- La consulta se hace al crear el pedido y otra vez al empezar a ejecutarlo. Si el curso se borró mientras el pedido estaba en cola, el pedido termina `failed` con `UNIT_NOT_FOUND`.
- El adaptador inicial es `AccountUnitMembershipAdapter`, sobre `TeacherRepositoryPort.get_courses` y `find_course_and_unit`.

### EvidenceProviderPort (MAT-01 · Material y Evidencia)

```python
@dataclass(frozen=True)
class EvidenceQuery:
    teacher_id: str
    unit_id: str
    query: str
    limit: int  # topK, de 1 a 50

@dataclass(frozen=True)
class EvidenceFragment:
    chunk_id: str
    document_id: str
    document_name: str
    location: str
    text: str
    relevance: float           # de 0 a 1
    source_url: str | None
    license: str | None

@dataclass(frozen=True)
class EvidenceRetrieval:
    fragments: tuple[EvidenceFragment, ...]
    retrieval_mode: Literal["hybrid", "bm25_fallback"]

class NoProcessedMaterial(DomainError): ...
class EvidenceUnavailable(DomainError): ...

class EvidenceProviderPort(Protocol):
    def has_processed_material(self, teacher_id: str, unit_id: str) -> bool: ...
    def retrieve(self, query: EvidenceQuery) -> EvidenceRetrieval:
        """Solo busca en material listo del docente y la unidad. Lanza NoProcessedMaterial o EvidenceUnavailable."""
```

- `has_processed_material` se usa antes de aceptar el pedido. Si devuelve `False`, la respuesta es `400 NO_PROCESSED_MATERIAL` (GEN-C6).
- `retrieve` se llama **una vez por pedido**, y la evidencia se comparte entre los pasos (GEN-R2).
- `retrievedAt` lo asigna Generación al recibir la respuesta.
- El adaptador inicial es `MaterialEvidenceAdapter`, sobre `ChunkRepositoryPort.get_chunks_by_unit(teacher_id, unit_id)`, `HybridEvidenceRetriever` y `TeacherRepositoryPort.get_documents`. Necesita que el recuperador informe si degradó a BM25.

### ContentFingerprintPort (REV-01 · Revisión y Exportación)

```python
class ContentFingerprintPort(Protocol):
    def fingerprint(self, resource: Mapping[str, Any]) -> str:
        """Huella del contenido normalizado del recurso, calculada con domain/review/content_fingerprint.py."""
```

- La huella se calcula después de la verificación y antes de entregar el recurso. Un recurso sin huella no se entrega; el paso termina `failed` con `FINGERPRINT_UNAVAILABLE`.
- Esta parte está **bloqueada** hasta que REV-01 publique `content_fingerprint.py`.

### ResourceReviewRepositoryPort (REV-01, se amplía)

Ya existe. Generación sigue usando `save_resources` y necesita una operación nueva:

```python
def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None: ...  # ya existe
def discard_if_version(
    self, teacher_id: str, resource_id: str, expected_version: int, reason: str
) -> bool:
    """Pasa el recurso a Descartados solo si sigue en expected_version. Devuelve False si cambió. Es atómico."""
```

## Propios de Generación

### GenerationRequestRepositoryPort

```python
class GenerationRequestRepositoryPort(Protocol):
    def create(self, request: GenerationRequest, steps: list[GenerationStep]) -> GenerationRequest:
        """Lanza IdempotencyKeyTaken(existing) si (teacher_id, idempotency_key) ya existe."""
    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationRequest | None: ...
    def get(self, teacher_id: str, request_id: str) -> GenerationRequest | None:
        """Filtra por docente. Un pedido ajeno devuelve None."""
    def get_for_runner(self, request_id: str) -> GenerationRequest | None: ...
    def list_by_unit(self, teacher_id: str, unit_id: str, active_only: bool, limit: int) -> list[GenerationRequest]: ...
    def count_active(self, teacher_id: str) -> int: ...
    def mark_running(self, request_id: str, worker_boot_id: str) -> None: ...
    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> None: ...
    def update_step(self, request_id: str, step: GenerationStep) -> None: ...
    def heartbeat(self, request_id: str) -> None: ...
    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> None: ...
    def mark_interrupted(self, stale_before: datetime) -> int:
        """Pasa a interrupted los pedidos queued o running con el latido vencido. Devuelve cuántos cambió."""
```

### GenerationJobRunnerPort

```python
class GenerationJobRunnerPort(Protocol):
    def submit(self, request_id: str) -> None:
        """Encola la ejecución. No bloquea. El adaptador inicial es ThreadPoolGenerationRunner."""
    def shutdown(self, wait: bool) -> None: ...
```

### Se conservan sin cambios

- `ResourceGeneratorPort`, con `GeminiLanguageModel` y `RuleBasedGenerator`.
- `MediaGeneratorPort` y `MediaRepositoryPort`.

## Dependencias permitidas

```text
infrastructure/http/routers/generation_requests.py
        │
        ▼
application/use_cases/generation/{start,run,get,regenerate}_*.py
        │                     │
        ▼                     ▼
application/ports/outbound/*  application/services/generation/{prompt_drafting, rule_based_generator}
        │
        ▼
domain/generation/{sequence, evidence, verification, grounding, distractor_reliability, resource_*}
```

`tests/architecture/test_layer_dependencies.py` debe seguir pasando. La aplicación de Generación no importa servicios de `accounts`, `materials` ni `review`.
