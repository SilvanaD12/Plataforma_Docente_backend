"""Nombres en inglés: archivos, carpetas e identificadores de Python (clases, funciones, argumentos y variables).

Es una red de seguridad, no un traductor: busca palabras en español del glosario del proyecto dentro de los
nombres. El español sigue permitido en comentarios, docstrings, textos que ve el docente y valores guardados.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = [BACKEND / "src", BACKEND / "tests", BACKEND / "scripts", BACKEND / "evaluation"]
SPANISH = set(
    """
    alternativa alternativas aprobar aprobado aprobados archivo archivos arquitectura autorizacion borrar capa catalogo
    clave codigo competencia configuracion conexion contenido contexto contrato contratos correo crear cuenta cuentas
    curso cursos datos descarga descargas descripcion despliegue dificultad docente documento documentos entorno
    enunciado errores esquema estado etapa exportacion exportador exportar extraccion fragmentar fragmento fragmentos
    fuente fuentes generacion generaciones generador guardar historial indicaciones intento licencia limite listar logro
    maximo mensaje modalidades modelo modulo motor nombre obtener opcion opciones oracion oraciones orden palabras
    paquete parrafos pedido pregunta preguntas procesar proveedor prueba pruebas publico puerto raiz recuperacion
    recuperar recurso recursos redaccion registro reglas respuesta respuestas resultado resultados retroalimentacion
    revisar revision ruta rutas salida salud servidor sesion sesiones solicitud solicitudes sumilla tema texto textos
    titulo ubicacion unidad unidades usuario usuarios
    """.split()
)
SKIP_DIRS = {".venv", "__pycache__", "results", ".pytest_cache", "fixtures"}


def words(name: str) -> set[str]:
    """`crear_router_configuracion` → {crear, router, configuracion}; `CursoORM` → {curso, orm}."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return {w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w}


def python_files() -> list[Path]:
    return [p for root in ROOTS if root.exists() for p in root.rglob("*.py") if not SKIP_DIRS & set(p.parts)]


def test_file_and_folder_names_are_english():
    offenders = sorted(
        str(p.relative_to(BACKEND))
        for root in ROOTS
        if root.exists()
        for p in root.rglob("*")
        if not SKIP_DIRS & set(p.relative_to(BACKEND).parts) and words(p.stem) & SPANISH
    )
    assert not offenders, "Nombres en español:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(BACKEND)))
def test_identifiers_are_english(path: Path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
    offenders = sorted(n for n in names if words(n) & SPANISH)
    assert not offenders, f"Identificadores en español: {', '.join(offenders)}"
