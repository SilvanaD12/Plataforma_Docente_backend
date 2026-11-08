"""
Script de exportación y compilación de esquemas JSON Schema.
"""

import json
from pathlib import Path

from platform5e.infrastructure.http.schemas.elaborate import ResourceElaborateItemModel
from platform5e.infrastructure.http.schemas.engage import ResourceEngageItemModel
from platform5e.infrastructure.http.schemas.evaluate import ResourceEvaluateItemModel
from platform5e.infrastructure.http.schemas.explain import ResourceExplainItemModel
from platform5e.infrastructure.http.schemas.explore import ResourceExploreItemModel
from platform5e.infrastructure.http.schemas.generations import GenerationRequest

# Determina la raíz del repositorio y el directorio de documentación compartido
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT_DIR / "docs" / "api" / "contracts"


def export_all_contracts() -> None:
    """Serializa cada contrato de datos en un archivo JSON Schema versionado."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    contract_catalog = {
        "generation-request.v1.json": GenerationRequest.model_json_schema(by_alias=True),
        "resource-engage.v1.json": ResourceEngageItemModel.model_json_schema(),
        "resource-explore.v1.json": ResourceExploreItemModel.model_json_schema(),
        "resource-explain.v1.json": ResourceExplainItemModel.model_json_schema(),
        "resource-elaborate.v1.json": ResourceElaborateItemModel.model_json_schema(),
        "resource-evaluate.v1.json": ResourceEvaluateItemModel.model_json_schema()
    }
    
    for file_name, json_schema in contract_catalog.items():
        output_path = OUTPUT_DIR / file_name
        with open(output_path, "w", encoding="utf-8") as file_path:
            json.dump(json_schema, file_path, indent=2, ensure_ascii=False)
        print(f"Esquema exportado exitosamente: {file_name}")


if __name__ == "__main__":
    export_all_contracts()