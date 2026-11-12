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

### ResourceVerificationPort (REV-01 · Revisión y Exportación)

```python
class ResourceVerificationPort(Protocol):
    def referenced_fragment_ids(self, resource: Mapping[str, Any]) -> list[str]:
        """Fragmentos que citan las afirmaciones, alternativas y estructura del recurso (REV-01)."""
    def fingerprint(self, resource: Mapping[str, Any]) -> str:
        """content_fingerprint(resource) de domain/review/content_fingerprint.py: 'sha256:<hex>'."""
    def verify(self, resource: Mapping[str, Any], threshold: float) -> dict[str, Any]:
        """verify_resource de domain/review/resource_verification.py con VERIFICATION_RULE_VERSION de grounding.py.
        Devuelve el bloque verification de REV-01."""
```

- Se llama después de armar la copia histórica y antes de entregar el recurso. Un borrador con `status = insufficient` se rechaza en el paso. Si `verify` lanza un error, el recurso se guarda con `status = pending` y el motivo.
- El adaptador inicial es `ReviewVerificationAdapter`. Las funciones ya existen en `feat/revision-y-exportacion`; las tareas que las usan dependen de que se integre el PR 1 de REV-01.

### ResourceRegenerationPort (lo define REV-01; Generación escribe el adaptador)

Firma propuesta por REV-01 en su D10, en `application/ports/outbound/resource_regeneration_port.py`:

```python
request_regeneration(teacher_id: str, resource_id: str, resource_version: int, params: dict) -> RegenerationStatus
get_regeneration(teacher_id: str, request_id: str) -> RegenerationStatus
# RegenerationStatus: request_id, status ("pending" | "running" | "succeeded" | "failed"),
#                     new_resource_ids: list[str], reason: str | None
```

- `GenerationRegenerationAdapter` llama a `StartRegeneration` y `GetGenerationRequest` y traduce los estados ([research R9](../research.md#r9-regeneración-y-edición-durante-el-pedido)): `queued` → `pending`, `running` → `running`, `succeeded` → `succeeded` y `failed` o `interrupted` → `failed`.
  - `new_resource_ids` son solo los recursos nuevos que siguen en Revisión. Si el pedido terminó bien pero ya no queda ninguno, devuelve `failed` con `code = REGENERATED_RESOURCE_NOT_FOUND`.
  - Si una consulta falla de forma inesperada cuando el pedido ya existe, devuelve `pending` o `running` con el id del pedido, en vez de propagar el error.
  - Revisión, por su parte, vuelve a comprobar al ver `succeeded` que los recursos nuevos existen. Si no queda ninguno, lo trata como `failed` con el mismo código, sin descartar el anterior y liberando la reserva.
  - Un rechazo al iniciar se devuelve como `failed` con su código. Los de `StartRegeneration` son `REGENERATION_PARAMETERS_MISSING` (422: sin `params` o sin `resourceType`), `REGENERATION_TARGET_INVALID` (422: id o versión del recurso no válidos) y `REGENERATION_ATTEMPTS_EXHAUSTED` (409: se agotaron los intentos de la versión). Revisión asigna el estado HTTP de su ruta; esos son los previstos. `REGENERATION_UNAVAILABLE` ya no lo usa Generación: queda solo para el 503 propio de Revisión.
- Generación no modifica ni descarta el recurso anterior; eso lo hace Revisión con su guardado condicional por versión.

## Propios de Generación

### GenerationRequestRepositoryPort

```python
class IdempotencyKeyTaken(DomainError): existing: GenerationRequest
class ActiveRequestLimitReached(DomainError): max_active: int
class UnitNoLongerOwned(DomainError): ...

class GenerationRequestRepositoryPort(Protocol):
    def create(self, request: GenerationRequest) -> GenerationRequest:
        """Guarda el pedido con sus pasos (request.steps) en una sola transacción.
        Lanza IdempotencyKeyTaken(existing) si (teacher_id, idempotency_key) ya existe."""
    def create_within_limit(
        self, request: GenerationRequest, max_active: int, unit_still_owned: Callable[[], bool] | None = None
    ) -> GenerationRequest:
        """Como create, pero comprueba el cupo y registra el pedido de forma atómica por docente.
        Con el bloqueo del docente tomado, en este orden: lanza IdempotencyKeyTaken(existing) si la clave ya existe,
        aunque el cupo esté lleno o la unidad ya no exista; UnitNoLongerOwned si unit_still_owned() devuelve False;
        y ActiveRequestLimitReached si el docente ya tiene max_active pedidos queued o running."""
    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationRequest | None: ...
    def get(self, teacher_id: str, request_id: str) -> GenerationRequest | None:
        """Filtra por docente. Un pedido ajeno devuelve None."""
    def get_for_runner(self, request_id: str) -> GenerationRequest | None: ...
    def list_by_unit(self, teacher_id: str, unit_id: str, active_only: bool, limit: int) -> list[GenerationRequest]: ...
    def count_active(self, teacher_id: str) -> int: ...
    def mark_running(self, request_id: str, worker_boot_id: str) -> None: ...
    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> bool: ...
    def update_step(self, request_id: str, step: GenerationStep) -> bool: ...
    def heartbeat(self, request_id: str) -> bool:
        """Renueva el latido de un pedido queued o running."""
    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> bool:
        """Cierra el pedido y sus pasos sin terminar. Un pedido ya terminado no cambia."""
    def mark_interrupted(self, stale_before: datetime) -> int:
        """Pasa a interrupted los pedidos queued o running con el latido (o la creación) anterior a stale_before.
        Lo usan el barrido de arranque y el barrido periódico. Devuelve cuántos cambió."""
```

- `GenerationRequest` ya incluye sus pasos (`steps`), así que `create` no los recibe aparte.
- `StartGenerationRequest` registra con `create_within_limit(request, MAX_ACTIVE_REQUESTS, unit_still_owned=…)`, no con `count_active` seguido de `create`. `unit_still_owned` vuelve a consultar `UnitMembershipPort.get_unit_context`; si la unidad ya no es del docente, el caso de uso responde `UNIT_NOT_FOUND`. El adaptador SQLAlchemy serializa por docente con `pg_advisory_xact_lock` en PostgreSQL y con `BEGIN IMMEDIATE` en SQLite ([research R4](../research.md#r4-límites-de-carga)). `delete_course` toma el mismo bloqueo en PostgreSQL (`lock_teacher_generation_requests`), así que el alta y el borrado de un curso del mismo docente no se cruzan.
- `save_evidence`, `update_step`, `heartbeat` y `finish` solo actualizan filas existentes; nunca insertan. Devuelven si el pedido existía (`update_step`, si existen el pedido y el paso). Si el curso se borró durante la ejecución, devuelven `False` y no dejan filas huérfanas ([research R3](../research.md#r3-ejecución-en-segundo-plano-y-reinicio)).
- `finish` cierra también los pasos que quedaron en `pending` o `running`: pasan a `interrupted` si el pedido se cierra como `interrupted`, y a `failed` en los demás casos, con el mismo `failure` como motivo. Así un pedido terminado nunca tiene pasos en curso. Los pasos ya terminados y sus recursos no cambian.

### GenerationJobRunnerPort

```python
class GenerationJobRunnerPort(Protocol):
    def submit(self, request_id: str) -> None:
        """Encola la ejecución. No bloquea. El adaptador inicial es ThreadPoolGenerationRunner."""
    def shutdown(self, wait: bool) -> None: ...
```

- `ThreadPoolGenerationRunner` renueva cada 15 s el latido de todos los pedidos que tiene en cola o en ejecución, y lo renueva también al recibir cada uno.
- `StaleRequestSweeper` (infraestructura, sin puerto propio) llama a `mark_interrupted(ahora − 60 s)` cada `GENERATION_SWEEP_INTERVAL_SECONDS` (30 s por defecto). El `lifespan` lo inicia después del barrido de arranque, junto al ejecutor, y lo detiene al apagar.

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
