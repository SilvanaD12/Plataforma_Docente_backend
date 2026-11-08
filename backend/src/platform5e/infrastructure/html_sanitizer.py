"""
Limpieza del HTML que escribe el docente con el editor enriquecido: solo formato de texto y enlaces web.

Se aplica al recibir el recurso (adaptador HTTP) y otra vez al exportarlo, para que ningún script llegue a la
plataforma, al paquete SCORM ni al documento de la unidad.
"""

from __future__ import annotations

import nh3

ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "h1", "h2", "h3", "ul", "ol", "li", "a", "blockquote"}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
URL_SCHEMES = {"http", "https", "mailto"}


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    return nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer",
    ).strip()
