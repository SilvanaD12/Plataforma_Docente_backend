"""El HTML conserva las secciones, la evidencia y el escape del documento anterior."""
from copy import deepcopy

from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from tests.unit.test_moodle_xml_exporter import QUESTION

COURSE = {"code": "Comunicación & Redes", "name": "Redes <avanzadas>", "term": "2026-II"}
UNIT = {"number": 1, "title": "Transporte", "outcomes": [{"id": "ra1", "code": "RA1", "text": "Distingue TCP < UDP"}]}


def test_document_preserves_sections_options_and_safe_evidence():
    question = {**deepcopy(QUESTION), "type": "item_opcion_multiple", "edited": True, "outcomeId": "ra1",
                "evidence": [{"id": "f1", "text": "UDP < TCP " + "x" * 450, "documentName": "Apuntes <1>",
                              "location": "p. 2", "sourceUrl": 'https://example.org/?a=1&b="2"', "license": "CC BY-SA"}]}
    explanation = {"type": "explicacion", "title": "Tema", "body": "Primer párrafo.\nLínea dos.\n\nSegundo <párrafo>."}
    exporter = UnitDocumentExporter()
    file = exporter.export([question, explanation], COURSE, UNIT)
    html = file.content.decode()
    assert file.file_name == "comunicacion-redes-unidad-1-documento.html" and file.media_type == "text/html"
    assert html.index('<h2>Para explicar</h2>') < html.index('<h2>Para evaluar</h2>')
    assert '<p>Primer párrafo.<br>Línea dos.</p><p>Segundo &lt;párrafo&gt;.</p>' in html
    assert "TCP &amp; UDP" in html and 'Redes &lt;avanzadas&gt;' in html
    assert '(respuesta correcta)' in html and 'DNS' not in html
    assert 'editado por el docente' in html and 'RA1' in html
    assert 'Apuntes &lt;1&gt;, p. 2' in html and '…»' in html
    assert 'href="https://example.org/?a=1&amp;b=&quot;2&quot;"' in html
    assert 'CC BY-SA' in html and 'su enlace y su licencia' in html
    assert '2 recursos aprobados' in html and exporter.supports(explanation)


def test_document_does_not_embed_unsafe_links_or_unresolved_citations():
    resource = {"type": "glosario", "title": "<script>alert(1)</script>", "body": "Texto", "options": [],
                "citations": [{"claim": "TCP", "fragmentIds": ["f1", "missing"]}, {"claim": "Omitida", "fragmentIds": ["missing"]}],
                "evidence": [{"id": "f1", "text": "TCP", "sourceUrl": "javascript:alert(1)"}]}
    html = UnitDocumentExporter().export([resource], {"code": "***"}, {"number": 2}).content.decode()
    assert 'javascript:' not in html and '<script>' not in html and 'Omitida' not in html
    assert '&lt;script&gt;' in html and '1 recurso aprobado' in html
    assert 'su licencia' not in html and 'Material de la unidad' in html
