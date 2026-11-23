"""Crea N docentes de prueba con su curso, unidad y material procesado, y escribe users.csv."""
from __future__ import annotations

import argparse
import csv
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

BACKEND = Path(__file__).resolve().parents[2]
EVALUATION = BACKEND / "evaluation"
DEFAULT_CORPUS = EVALUATION / "corpus" / "protocols.txt"
DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_USERS = 50
DEFAULT_OUT = Path(__file__).resolve().parent / "users.csv"
DEFAULT_BASE_EMAIL = "docente.estres@correo.pe"
DEFAULT_PASSWORD = "clave-segura-local-123"
DEFAULT_WORKERS = 10


def load_collect_samples() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_samples", EVALUATION / "collect_samples.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar evaluation/collect_samples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def teacher_email(base: str, index: int) -> str:
    local, _, domain = base.partition("@")
    return f"{local}.carga{index + 1}@{domain}"


def prepare_single_user(
    index: int,
    api: str,
    base_email: str,
    password: str,
    corpus: Path,
) -> dict[str, str]:
    collect = load_collect_samples()
    email = teacher_email(base_email, index)
    with httpx.Client(base_url=api, timeout=60.0) as client:
        headers = collect.login(client, email, password)
        unit = collect.ensure_unit(client, headers)
        collect.ensure_material(client, headers, unit, corpus)
        return {
            "email": email,
            "password": password,
            "unit_id": unit["id"],
        }


def prepare_users(
    api: str,
    count: int,
    out_path: Path,
    base_email: str = DEFAULT_BASE_EMAIL,
    password: str = DEFAULT_PASSWORD,
    corpus: Path = DEFAULT_CORPUS,
    workers: int = DEFAULT_WORKERS,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    print(f"Preparando {count} docentes contra {api} usando {workers} workers...")

    if workers <= 1:
        for i in range(count):
            row = prepare_single_user(i, api, base_email, password, corpus)
            rows.append(row)
            if (i + 1) % 10 == 0 or (i + 1) == count:
                print(f"  [{i + 1}/{count}] docente {row['email']} listo (unidad {row['unit_id']})")
    else:
        results: dict[int, dict[str, str]] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(prepare_single_user, i, api, base_email, password, corpus): i
                for i in range(count)
            }
            completed_count = 0
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                res = future.result()
                results[idx] = res
                completed_count += 1
                if completed_count % 20 == 0 or completed_count == count:
                    print(f"  [{completed_count}/{count}] docentes preparados...")

        rows = [results[i] for i in range(count)]

    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "password", "unit_id"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Completado: {len(rows)} docentes guardados en {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara docentes de prueba para JMeter")
    parser.add_argument("--api", default=DEFAULT_API, help=f"URL base de la API (por defecto {DEFAULT_API})")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS, help=f"Cantidad de docentes (por defecto {DEFAULT_USERS})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Ruta del archivo CSV de salida")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="Ruta del corpus a cargar")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Workers concurrentes (por defecto {DEFAULT_WORKERS})")
    args = parser.parse_args()

    prepare_users(api=args.api, count=args.users, out_path=args.out, corpus=args.corpus, workers=args.workers)


if __name__ == "__main__":
    main()
