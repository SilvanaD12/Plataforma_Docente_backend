"""
Dibuja como SVG los recursos visuales a partir de su estructura: mapa conceptual, infografía y diagrama de proceso.

También dibuja la tarjeta de respaldo de una imagen ilustrativa cuando el modelo de imágenes no está disponible.
Todo el texto se escapa: el SVG se puede incrustar en la plataforma, en el paquete SCORM y en el documento.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from html import escape
from typing import Any

from platform5e.application.ports.outbound.media_port import VisualRendererPort

INK = "#1a211e"
MUTED = "#4a544f"
ACCENT = "#1f5c4a"
ACCENT_SOFT = "#e3efe9"
LINE = "#c9d3ce"
PAPER = "#ffffff"
FONT = "font-family=\"system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif\""


def _esc(value: object) -> str:
    return escape(str(value or ""), quote=True)


def wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Corta el texto en líneas de hasta `width` caracteres; la última termina en «…» si no cabe."""
    words, lines, current = (text or "").split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = lines[-1][: max(0, width - 1)].rstrip() + "…"
    return lines


def _text(x: float, y: float, lines: list[str], size: int, color: str = INK, weight: int = 400, anchor: str = "start", gap: float = 1.35) -> str:
    spans = "".join(
        f'<tspan x="{x:.0f}" dy="{0 if i == 0 else size * gap:.1f}">{_esc(line)}</tspan>' for i, line in enumerate(lines)
    )
    return f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}" {FONT}>{spans}</text>'


def _svg(width: int, height: int, title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{_esc(title)}"><title>{_esc(title)}</title>'
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>{body}</svg>'
    )


def concept_map(structure: Mapping[str, Any], title: str) -> str:
    nodes = list(structure.get("nodes") or [])[:10]
    width, height = 1100, 820
    cx, cy = width / 2, height / 2
    central = wrap(structure.get("central") or title, 20, 3)
    parts: list[str] = []
    boxes: list[str] = []
    for index, node in enumerate(nodes):
        angle = -math.pi / 2 + 2 * math.pi * index / max(1, len(nodes))
        x, y = cx + 380 * math.cos(angle), cy + 285 * math.sin(angle)
        label = wrap(node.get("label", ""), 20, 2)
        detail = wrap(node.get("detail", ""), 28, 4)
        box_h = 34 + 26 * len(label) + 22 * len(detail)
        left, top = x - 150, y - box_h / 2
        parts.append(f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{x:.0f}" y2="{y:.0f}" stroke="{LINE}" stroke-width="2.5"/>')
        boxes.append(
            f'<rect x="{left:.0f}" y="{top:.0f}" width="300" height="{box_h:.0f}" rx="14" fill="{PAPER}" stroke="{ACCENT}" stroke-width="2"/>'
            + _text(x, top + 32, label, 21, ACCENT, 700, "middle")
            + _text(x, top + 36 + 26 * len(label), detail, 17, MUTED, 400, "middle")
        )
    central_h = 36 + 30 * len(central)
    center = (
        f'<rect x="{cx - 150:.0f}" y="{cy - central_h / 2:.0f}" width="300" height="{central_h:.0f}" rx="18" fill="{ACCENT}"/>'
        + _text(cx, cy - central_h / 2 + 42, central, 25, PAPER, 700, "middle")
    )
    return _svg(width, height, title, "".join(parts) + center + "".join(boxes))


def infographic(structure: Mapping[str, Any], title: str) -> str:
    points = list(structure.get("points") or [])[:8]
    width, card_w, card_h, gap = 1000, 470, 200, 20
    rows = math.ceil(len(points) / 2)
    headline = wrap(structure.get("headline") or title, 60, 2)
    top = 40 + 34 * len(headline) + 30
    height = top + rows * (card_h + gap) + 20
    body = [
        f'<rect x="0" y="0" width="{width}" height="{top - 20}" fill="{ACCENT}"/>',
        _text(30, 52, headline, 28, PAPER, 700),
    ]
    for index, point in enumerate(points):
        col, row = index % 2, index // 2
        x, y = 20 + col * (card_w + gap), top + row * (card_h + gap)
        body.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="14" fill="{ACCENT_SOFT}"/>')
        body.append(f'<circle cx="{x + 34}" cy="{y + 36}" r="20" fill="{ACCENT}"/>')
        body.append(_text(x + 34, y + 43, [str(index + 1)], 18, PAPER, 700, "middle"))
        body.append(_text(x + 66, y + 44, wrap(point.get("title", ""), 28, 1), 21, INK, 700))
        body.append(_text(x + 24, y + 88, wrap(point.get("text", ""), 42, 4), 18, INK))
    return _svg(width, height, title, "".join(body))


def process_diagram(structure: Mapping[str, Any], title: str) -> str:
    steps = list(structure.get("steps") or [])[:10]
    width, box_w, left = 860, 760, 50
    body: list[str] = []
    y = 30
    for index, step in enumerate(steps):
        text = wrap(step.get("text", ""), 72, 3)
        box_h = 60 + 23 * len(text)
        body.append(f'<rect x="{left}" y="{y}" width="{box_w}" height="{box_h}" rx="12" fill="{PAPER}" stroke="{ACCENT}" stroke-width="1.5"/>')
        body.append(f'<rect x="{left}" y="{y}" width="56" height="{box_h}" rx="12" fill="{ACCENT}"/>')
        body.append(_text(left + 28, y + box_h / 2 + 8, [str(index + 1)], 22, PAPER, 700, "middle"))
        body.append(_text(left + 76, y + 32, wrap(step.get("title", ""), 56, 1), 20, INK, 700))
        body.append(_text(left + 76, y + 60, text, 17, MUTED))
        y += box_h
        if index < len(steps) - 1:
            mid = left + box_w / 2
            body.append(
                f'<path d="M{mid:.0f} {y + 4} L{mid:.0f} {y + 26}" stroke="{ACCENT}" stroke-width="2.5"/>'
                f'<path d="M{mid - 8:.0f} {y + 18} L{mid:.0f} {y + 28} L{mid + 8:.0f} {y + 18}" fill="none" stroke="{ACCENT}" stroke-width="2.5"/>'
            )
            y += 34
    return _svg(width, y + 30, title, "".join(body))


def illustration_card(structure: Mapping[str, Any], title: str) -> str:
    """Respaldo de la imagen ilustrativa: la descripción de la escena en una tarjeta 16:9."""
    width, height = 960, 540
    description = wrap(structure.get("prompt", ""), 70, 7)
    body = (
        f'<rect x="24" y="24" width="{width - 48}" height="{height - 48}" rx="20" fill="{ACCENT_SOFT}" stroke="{LINE}" stroke-width="2"/>'
        f'<circle cx="110" cy="112" r="34" fill="{ACCENT}"/>'
        f'<path d="M88 128 L104 106 L116 120 L124 112 L136 128 Z" fill="{PAPER}"/><circle cx="122" cy="98" r="6" fill="{PAPER}"/>'
        + _text(168, 104, wrap(title, 50, 2), 26, INK, 700)
        + _text(80, 200, description, 19, MUTED)
        + _text(80, height - 60, ["Descripción de la ilustración (sin imagen generada)."], 14, MUTED)
    )
    return _svg(width, height, title, body)


RENDERERS = {
    "mapa_conceptual": concept_map,
    "infografia": infographic,
    "diagrama_proceso": process_diagram,
    "imagen_ilustrativa": illustration_card,
}


class SvgVisualRenderer(VisualRendererPort):
    """Adaptador del puerto VisualRendererPort."""

    def render(self, resource: Mapping[str, Any]) -> str:
        renderer = RENDERERS.get(resource.get("type", ""))
        if renderer is None:
            raise ValueError(f"El tipo {resource.get('type')} no tiene gráfico.")
        return renderer(resource.get("structure") or {}, resource.get("title", ""))


def can_render(resource_type: str) -> bool:
    return resource_type in RENDERERS
