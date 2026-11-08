"""Escribe docs/api/openapi.json con el contrato actual de la API. Uso, desde backend/: python scripts/export_openapi.py"""

from __future__ import annotations

import json
from pathlib import Path

from platform5e.main import create_application

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def main() -> None:
    spec = create_application().openapi()
    OUTPUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(OUTPUT.parents[2])}: {len(spec['paths'])} rutas")


if __name__ == "__main__":
    main()
