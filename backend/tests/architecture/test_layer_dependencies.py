"""Dependencias de todas las capas mediante AST, incluidos imports relativos."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import pytest

# Ruta base hacia el código fuente de la plataforma
ROOT = Path(__file__).resolve().parents[2] / 'src' / 'platform5e'

# Matriz de reglas de dependencias prohibidas por capa
RULES = {
    'domain': (
        'platform5e.application',
        'platform5e.infrastructure',
        'fastapi',
        'sqlalchemy',
    ),
    'application': (
        'platform5e.infrastructure',
        'fastapi',
        'sqlalchemy',
    ),
    'infrastructure/http': (
        'platform5e.infrastructure.persistence',
    ),
}


def imports(source: str, package: str):
    """Extrae todos los módulos y alias importados a partir del árbol AST del archivo."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ''
            if node.level:
                module_name = resolve_name('.' * node.level + module_name, package)
            yield module_name
            yield from (module_name + '.' + alias.name for alias in node.names)


def violations(source: str, package: str, forbidden_modules: tuple[str, ...]):
    """Determina si alguna importación viola la frontera arquitectónica establecida."""
    return [
        name
        for name in imports(source, package)
        if any(name == p or name.startswith(p + '.') for p in forbidden_modules)
    ]


@pytest.mark.parametrize('layer,forbidden_modules', RULES.items())
def test_layers_respect_the_dependency_rule(layer, forbidden_modules):
    failures = []
    files_found = list((ROOT / layer).rglob('*.py'))
    assert files_found, f'No se encontraron módulos en {layer}'
    for file_path in files_found:
        # Construye la ruta de importación canónica bajo platform5e
        relative_parts = file_path.relative_to(ROOT).parent.parts
        package = '.'.join(['platform5e', *relative_parts]) if relative_parts else 'platform5e'
        errors = violations(file_path.read_text(encoding='utf-8'), package, forbidden_modules)
        failures.extend(f'{file_path.relative_to(ROOT)}: {name}' for name in errors)
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize('source,package,forbidden', [
    ('import fastapi as web', 'platform5e.domain', 'fastapi'),
    ('from sqlalchemy.exc import SQLAlchemyError', 'platform5e.infrastructure.http', 'sqlalchemy'),
    ('from platform5e import infrastructure', 'platform5e.application', 'platform5e.infrastructure'),
    ('from ..application import services', 'platform5e.domain', 'platform5e.application'),
    ('def funcion():\n    from ..infrastructure import http', 'platform5e.application', 'platform5e.infrastructure'),
])
def test_detects_aliases_relative_imports_and_imports_inside_functions(source, package, forbidden):
    assert violations(source, package, (forbidden,))


def test_comments_and_strings_are_not_imports():
    assert violations('# import fastapi\ntexto = "sqlalchemy"', 'platform5e.domain', ('fastapi', 'sqlalchemy')) == []

# GEN-01 (T012, Constitución I): los casos de uso de Generación y sus puertos hacia otros módulos no importan los
# servicios de Cuentas, Material ni Revisión, ni el dominio de Revisión. Hablan con ellos solo por puertos.
GENERATION_ISOLATED = [
    'application/use_cases/generation',
    'application/ports/outbound/unit_membership_port.py',
    'application/ports/outbound/evidence_provider_port.py',
    'application/ports/outbound/generation_request_repository_port.py',
    'application/ports/outbound/generation_job_runner_port.py',
    'application/ports/outbound/resource_verification_port.py',
]
GENERATION_FORBIDDEN = (
    'platform5e.application.services.accounts',
    'platform5e.application.services.materials',
    'platform5e.application.services.review',
    'platform5e.domain.review',
)


def generation_files() -> list[Path]:
    files: list[Path] = []
    for relative in GENERATION_ISOLATED:
        path = ROOT / relative
        files += sorted(path.rglob('*.py')) if path.is_dir() else [path] if path.exists() else []
    return files


def test_generation_talks_to_other_modules_only_through_ports():
    files = generation_files()
    # Los puertos ya existen; la carpeta de casos de uso llega con T015.
    assert any(f.name == 'unit_membership_port.py' for f in files)
    failures = []
    for file_path in files:
        relative_parts = file_path.relative_to(ROOT).parent.parts
        package = '.'.join(['platform5e', *relative_parts])
        errors = violations(file_path.read_text(encoding='utf-8'), package, GENERATION_FORBIDDEN)
        failures.extend(f'{file_path.relative_to(ROOT)}: {name}' for name in errors)
    assert not failures, '\n'.join(failures)


def test_the_generation_rule_detects_a_review_import():
    source = 'from platform5e.domain.review.content_fingerprint import content_fingerprint'
    assert violations(source, 'platform5e.application.use_cases.generation', GENERATION_FORBIDDEN)
    assert violations('from ..services.accounts import account_service', 'platform5e.application.use_cases',
                      GENERATION_FORBIDDEN)
