"""
Script para calcular y verificar la tasa de duplicidad por unidad curricular.

Uso:
    python docs/evidence/REV-P3/calculate_duplicate_rate.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend" / "src"
sys.path.insert(0, str(BACKEND_DIR))

from platform5e.domain.review.duplication import DEFAULT_DUPLICATE_THRESHOLD, find_duplicates, similarity  # noqa: E402

DATA_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "src"
    / "platform5e"
    / "infrastructure"
    / "persistence"
    / "seed"
    / "demo_generation.json"
)


def run_fixed_cases() -> list[tuple[str, str, str, float, bool]]:
    cases = [
        (
            "Ejemplo profesor",
            "¿Cómo se gestionan los paquetes de redes?",
            "¿Cómo se gestionaría los paquetes en una red?",
            DEFAULT_DUPLICATE_THRESHOLD,
        ),
        (
            "Par UDP",
            "El protocolo UDP no ofrece garantías sobre la entrega o el orden de los paquetes.",
            "UDP no ofrece garantías para la entrega o el orden de los paquetes en la red.",
            DEFAULT_DUPLICATE_THRESHOLD,
        ),
        (
            "Pila vs Cola (LIFO / FIFO)",
            "Una pila es una estructura LIFO donde el último elemento en entrar es el primero en salir.",
            "Una cola es una estructura FIFO donde el primer elemento en entrar es el primero en salir.",
            DEFAULT_DUPLICATE_THRESHOLD,
        ),
        (
            "Pila vs Cola (pregunta simple)",
            "¿Qué es una pila?",
            "¿Qué es una cola?",
            DEFAULT_DUPLICATE_THRESHOLD,
        ),
        (
            "Modelo OSI (enrutar vs cifrar)",
            "¿Qué capa del modelo OSI enruta los paquetes?",
            "¿Qué capa del modelo OSI cifra los datos?",
            DEFAULT_DUPLICATE_THRESHOLD,
        ),
    ]

    results = []
    for name, text_a, text_b, threshold in cases:
        score = similarity(text_a, text_b)
        flagged = score >= threshold
        results.append((name, text_a, text_b, score, flagged))
    return results


def run_unit_analysis() -> None:
    print(f"Leyendo catálogo: {DATA_PATH}")
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    units = data.get("units", [])
    examples = data.get("examples", [])

    print(f"\n--- CASOS FIJOS (Umbral = {DEFAULT_DUPLICATE_THRESHOLD}) ---")
    fixed = run_fixed_cases()
    for name, text_a, text_b, score, flagged in fixed:
        status = "MARCADO" if flagged else "NO MARCADO"
        print(f"{name:30} -> Score: {score:.3f} [{status}]")

    print(f"\n--- ANÁLISIS POR UNIDAD CURRICULAR ---")
    thresholds = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90]

    for unit in units:
        unit_id = unit["id"]
        unit_title = unit.get("title", "")
        unit_resources = [e for e in examples if e.get("unitId") == unit_id]
        print(f"\nUnidad {unit_id}: {unit_title} ({len(unit_resources)} recursos)")

        for th in thresholds:
            rep = find_duplicates(unit_resources, threshold=th)
            comp = rep["comparedPairs"]
            flagged_count = len(rep["flaggedPairs"])
            rate = rep["duplicatePairRate"]
            print(
                f"  Umbral {th:.2f}: comparados={comp:3d}, marcados={flagged_count:2d}, duplicatePairRate={rate:.3f}"
            )
            for pair in rep["flaggedPairs"]:
                print(f"     * {pair['resourceIdA']} <-> {pair['resourceIdB']} ({pair['scope']}): {pair['score']:.3f}")


if __name__ == "__main__":
    run_unit_analysis()
