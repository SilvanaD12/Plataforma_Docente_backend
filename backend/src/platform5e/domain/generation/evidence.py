"""
GEN-R8: copia histórica de los fragmentos que un recurso referencia.

Los ids referenciados llegan ya calculados: los reúne `referenced_fragment_ids` de Revisión (por su puerto) desde las
citas, las alternativas y la estructura (pasos guiados, predicciones y criterios). Este módulo no importa nada de
Revisión; solo copia los fragmentos recuperados del pedido e informa los que faltan, para que el recurso quede
pendiente si la copia no está completa.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceSnapshotItem:
    """Un fragmento tal como se usó al generar: texto, ubicación, documento, procedencia y fecha de recuperación."""

    id: str
    text: str
    location: str
    document_id: str
    document_name: str
    source_url: str | None
    license: str | None
    retrieved_at: str

    def to_dict(self) -> dict[str, Any]:
        """Forma guardada en `evidence` del recurso (camelCase)."""
        return {
            "id": self.id,
            "text": self.text,
            "location": self.location,
            "documentId": self.document_id,
            "documentName": self.document_name,
            "sourceUrl": self.source_url,
            "license": self.license,
            "retrievedAt": self.retrieved_at,
        }


@dataclass(frozen=True)
class EvidenceSnapshot:
    """La copia de un recurso y los ids referenciados que no estaban entre los fragmentos recuperados."""

    items: tuple[EvidenceSnapshotItem, ...]
    missing_ids: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_ids


def _fragment_id(fragment: Mapping[str, Any]) -> str | None:
    """`chunkId` es el nombre del puerto de Material; `id` es el de los fragmentos que ya usa la generación."""
    value = fragment.get("chunkId") or fragment.get("id")
    return str(value) if value else None


def build_snapshot(
    referenced_ids: Iterable[str],
    fragments: Iterable[Mapping[str, Any]],
    retrieved_at: str,
) -> EvidenceSnapshot:
    """Copia, sin repetir y en el orden de referencia, cada fragmento referenciado por el recurso.

    `fragments` es la evidencia recuperada del pedido (`chunkId` o `id`, `text`, `location`, `documentId`,
    `documentName`, `sourceUrl` y `license`). `retrieved_at` es el instante en que el pedido la recuperó. Un id
    referenciado que no está en `fragments`, o cuyo texto está vacío o solo tiene espacios, se informa en
    `missing_ids` y no se copia.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for fragment in fragments:
        fragment_id = _fragment_id(fragment)
        if fragment_id is not None:
            by_id.setdefault(fragment_id, fragment)

    items: list[EvidenceSnapshotItem] = []
    missing: list[str] = []
    for fragment_id in dict.fromkeys(f_id for f_id in referenced_ids if isinstance(f_id, str) and f_id):
        fragment = by_id.get(fragment_id)
        text = str(fragment.get("text") or "") if fragment is not None else ""
        if not text.strip():
            # Sin texto no hay copia que sustente la cita: cuenta como faltante, igual que en Revisión.
            missing.append(fragment_id)
            continue
        items.append(
            EvidenceSnapshotItem(
                id=fragment_id,
                text=text,
                location=str(fragment.get("location") or ""),
                document_id=str(fragment.get("documentId") or ""),
                document_name=str(fragment.get("documentName") or ""),
                source_url=fragment.get("sourceUrl"),
                license=fragment.get("license"),
                retrieved_at=retrieved_at,
            )
        )
    return EvidenceSnapshot(items=tuple(items), missing_ids=tuple(missing))
