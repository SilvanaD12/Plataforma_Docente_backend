"""
Cliente HTTP seguro para descargar páginas web públicas y extraer su texto limpio (MAT-P1 / Pedido P6 / Plan v2-H).
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from platform5e.application.ports.outbound.web_content_fetcher_port import WebContentFetcherPort
from platform5e.domain.materials.chunking import MaterialError

USER_AGENT_HEADER: str = (
    "Platform5E/1.0 (https://github.com/Yansete/plataforma-5e-taller-integrador; academic project UPAO) python-httpx"
)
MAX_WEB_TEXT_CHARS: int = 60000
MIN_WEB_TEXT_CHARS: int = 120
MAX_DOWNLOAD_BYTES: int = 2 * 1024 * 1024  # 2 MB máximo para HTML/texto
MAX_REDIRECTS: int = 5

_NOISE_CLASSES_OR_IDS: frozenset[str] = frozenset(
    {
        "mw-editsection",
        "navbox",
        "vertical-navbox",
        "reflist",
        "references",
        "toc",
        "catlinks",
        "mw-jump-link",
        "printfooter",
        "sistersitebox",
        "infobox",
    }
)

_TRAILING_WEB_SECTIONS: re.Pattern[str] = re.compile(
    r"\n\s*(?:Referencias|Bibliografía|Véase también|Enlaces externos|Notas|Fuentes)\s*\n",
    re.IGNORECASE,
)

_TITLE_SUFFIX_REGEX: re.Pattern[str] = re.compile(
    r"\s+[-|–—]\s+(?:Wikipedia.*|Wikilibros.*|Wikiversidad.*)$",
    re.IGNORECASE,
)


class _ReadableHTMLParser(HTMLParser):
    """Extrae el título (<title>) y el texto visible ignorando scripts, estilos, navegación y notas."""

    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "iframe", "sup"}
    _BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "br",
        "pre",
        "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    @staticmethod
    def _has_noise_attribute(attrs: list[tuple[str, str | None]]) -> bool:
        for attr_name, attr_val in attrs:
            if not attr_val:
                continue
            lower_name = attr_name.lower()
            if lower_name == "role" and attr_val.lower() in {"navigation", "banner", "contentinfo"}:
                return True
            if lower_name in {"id", "class"}:
                tokens = set(attr_val.lower().split())
                if tokens & _NOISE_CLASSES_OR_IDS:
                    return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if self._ignored_depth > 0:
            self._ignored_depth += 1
            return
        if lower in self._IGNORED_TAGS or self._has_noise_attribute(attrs):
            self._ignored_depth = 1
            return
        if lower == "title":
            self._in_title = True
        if lower in self._BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if lower == "title":
            self._in_title = False
        if lower in self._BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def _is_forbidden_ip(ip_str: str) -> bool:
    """Bloquea direcciones IP privadas, loopback, link-local o reservadas (protección SSRF)."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_public_http_url(raw_url: str) -> str:
    """Valida esquema HTTP/HTTPS y asegura que el host no resuelva a redes internas/privadas."""
    cleaned = (raw_url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise MaterialError("INVALID_URL", "Ingresa una URL válida que empiece con http:// o https://.", 422)

    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or hostname.endswith(".local"):
        raise MaterialError("FORBIDDEN_URL", "No se permiten direcciones locales o privadas.", 400)

    try:
        ipaddress.ip_address(hostname)
        if _is_forbidden_ip(hostname):
            raise MaterialError("FORBIDDEN_URL", "No se permiten direcciones IP privadas o internas.", 400)
        return cleaned
    except ValueError:
        pass

    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise MaterialError(
            "URL_UNREACHABLE",
            "No se pudo resolver el dominio de la URL. Verifica que esté bien escrita.",
            422,
        ) from exc

    if not addr_infos:
        raise MaterialError("URL_UNREACHABLE", "No se pudo conectar con la URL indicada.", 422)

    for info in addr_infos:
        resolved_ip = info[4][0]
        if _is_forbidden_ip(resolved_ip):
            raise MaterialError("FORBIDDEN_URL", "La URL apunta a una dirección de red interna no permitida.", 400)

    return cleaned


def clean_extracted_web_text(text: str) -> str:
    """Elimina marcas de edición, notas al pie entre corchetes y secciones finales de bibliografía."""
    cleaned = re.sub(r"\[editar\]", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*(?:nota\s*|cita requerida)?\d+\s*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*(?:cita requerida|editar)\s*\]", "", cleaned, flags=re.IGNORECASE)

    trailing_match = _TRAILING_WEB_SECTIONS.search(cleaned)
    if trailing_match:
        cleaned = cleaned[: trailing_match.start()]

    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    non_empty_lines = [line for line in lines if line]
    return "\n\n".join(non_empty_lines)[:MAX_WEB_TEXT_CHARS]


def extract_readable_text(raw_html: str, fallback_title: str) -> tuple[str, str]:
    """Convierte HTML en título limpio y texto legible sin ruido de navegación ni bibliografía."""
    parser = _ReadableHTMLParser()
    parser.feed(raw_html)
    parser.close()

    raw_title = " ".join("".join(parser.title_parts).split()).strip()
    unescaped_title = html.unescape(raw_title)
    clean_title = _TITLE_SUFFIX_REGEX.sub("", unescaped_title).strip()[:140]
    title = clean_title or fallback_title

    cleaned_text = clean_extracted_web_text("".join(parser.text_parts))
    return title, cleaned_text


class WebPageExtractor(WebContentFetcherPort):
    """Adaptador de infraestructura para descargar y extraer contenido textual desde URLs públicas."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(
            headers={
                "User-Agent": USER_AGENT_HEADER,
                "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout,
            follow_redirects=False,
        )

    def fetch(self, url: str) -> dict[str, Any]:
        current_url = validate_public_http_url(url)

        response: httpx.Response | None = None
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = self._client.get(current_url)
            except httpx.TimeoutException as exc:
                raise MaterialError(
                    "URL_TIMEOUT",
                    "La página tardó demasiado en responder. Intenta con otra URL.",
                    422,
                ) from exc
            except httpx.HTTPError as exc:
                raise MaterialError(
                    "URL_UNREACHABLE",
                    "No se pudo descargar el contenido de la URL proporcionada.",
                    422,
                ) from exc

            if response.is_redirect and "location" in response.headers:
                next_url = urljoin(current_url, response.headers["location"])
                current_url = validate_public_http_url(next_url)
                continue
            break
        else:
            raise MaterialError("TOO_MANY_REDIRECTS", "La URL tiene demasiadas redirecciones.", 422)

        assert response is not None
        if response.status_code >= 400:
            raise MaterialError(
                "URL_HTTP_ERROR",
                f"La página respondió con error HTTP {response.status_code} y no pudo leerse.",
                422,
            )

        content_type = (response.headers.get("content-type") or "").lower()
        if not any(allowed in content_type for allowed in ("text/html", "text/plain", "application/xhtml+xml")):
            raise MaterialError(
                "UNSUPPORTED_URL_CONTENT",
                "La URL debe apuntar a una página web HTML o texto plano.",
                422,
            )

        raw_bytes = response.content[:MAX_DOWNLOAD_BYTES]
        encoding = response.encoding or "utf-8"
        decoded = raw_bytes.decode(encoding, errors="replace")

        parsed_final = urlparse(current_url)
        fallback_title = parsed_final.hostname or "Página web"

        if "text/plain" in content_type and "html" not in content_type:
            title = fallback_title
            cleaned_text = clean_extracted_web_text(decoded)
        else:
            title, cleaned_text = extract_readable_text(decoded, fallback_title)

        if len(cleaned_text.strip()) < MIN_WEB_TEXT_CHARS:
            raise MaterialError(
                "NO_TEXT_IN_URL",
                "No se encontró suficiente texto legible en la página web proporcionada.",
                422,
            )

        return {
            "url": current_url,
            "title": title,
            "text": cleaned_text,
        }