"""TA-010 (T067): corpus en carpeta, documentos por caso, unidades compartidas y casos que esperan «sin evidencia» en
evaluation/collect_samples.py.

Sin servidor ni red: el backend lo reemplaza un `httpx.MockTransport` que guarda cada llamada.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
import pytest

from tests.unit.test_collect_samples import collect  # noqa: F401 (fixture)

EVALUATION = Path(__file__).resolve().parents[2] / "evaluation"
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
NETWORK_FILES = [
    "Modelo OSI.txt", "Protocolo de datagramas de usuario.txt", "direccionamiento_ip_enrutamiento.pptx",
    "guia_laboratorio_wireshark.docx.pdf", "protocolos_tcp_udp.pdf",
]
T067_FILES = sorted([*NETWORK_FILES, "bases_datos_relacionales.txt"])


def corpus_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "b_tcp.txt").write_text("TCP confirma la entrega.", encoding="utf-8")
    (folder / "a_osi.pdf").write_bytes(b"%PDF-1.4 OSI")
    (folder / "c_ip.pptx").write_bytes(b"PK pptx")
    (folder / "doble.docx.pdf").write_bytes(b"%PDF-1.4 Wireshark")
    (folder / "README.md").write_text("# Corpus", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"\x00")
    (folder / "sub").mkdir()
    return folder


# Corpus: archivo o carpeta


def test_a_directory_corpus_takes_every_pdf_pptx_and_txt_with_its_content_type(collect, tmp_path):
    files = collect.corpus_files(corpus_dir(tmp_path))
    assert [f.name for f in files] == ["a_osi.pdf", "b_tcp.txt", "c_ip.pptx", "doble.docx.pdf"]
    assert [collect.content_type(f) for f in files] == ["application/pdf", "text/plain", PPTX_TYPE, "application/pdf"]


def test_a_single_file_corpus_is_used_as_today(collect):
    corpus = EVALUATION / "corpus" / "protocols.txt"
    assert collect.corpus_files(corpus) == [corpus]
    assert collect.content_type(corpus) == "text/plain"
    assert collect.build_parser().parse_args([]).corpus == corpus


@pytest.mark.parametrize("make", [lambda p: p / "no-existe", lambda p: (p / "vacia").mkdir() or p / "vacia"])
def test_a_missing_or_empty_corpus_is_an_error(collect, tmp_path, make):
    with pytest.raises(ValueError):
        collect.corpus_files(make(tmp_path))


# Subida y procesamiento


class Backend:
    """Backend falso de documentos: guarda lo subido (nombre y tipo de contenido) y lo procesado."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.documents: list[dict] = list(existing or [])
        self.uploads: list[tuple[str, str, str]] = []
        self.processed: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/v1/documents":
            return httpx.Response(200, json=self.documents)
        if request.method == "POST" and path == "/api/v1/documents":
            content = request.content.decode("latin-1")
            name, kind = re.search(r'filename="([^"]+)"\r\nContent-Type: ([^\r]+)', content).groups()
            unit_id = json.loads(re.search(r'name="context"\r\n\r\n(\{.*?\})\r\n', content, re.S).group(1))["unitId"]
            self.uploads.append((unit_id, name, kind))
            document = {"id": f"doc-{len(self.documents) + 1}", "unitId": unit_id, "fileName": name,
                        "status": "registrado"}
            self.documents.append(document)
            return httpx.Response(201, json=document)
        if request.method == "POST" and path.endswith("/process"):
            document_id = path.split("/")[-2]
            self.processed.append(document_id)
            return httpx.Response(200, json={"id": document_id, "status": "procesado"})
        raise AssertionError(f"llamada inesperada: {request.method} {path}")


def client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://evaluacion.test", transport=httpx.MockTransport(handler))


UNIT = {"id": "unidad-1", "title": "Redes", "outcomes": [{"id": "ra-1", "text": "Explica redes"}]}


def test_every_file_is_uploaded_with_its_content_type_and_processed(collect, tmp_path):
    backend = Backend()
    files = collect.corpus_files(corpus_dir(tmp_path))
    collect.ensure_materials(client(backend), {}, UNIT, files)
    assert backend.uploads == [
        ("unidad-1", "a_osi.pdf", "application/pdf"), ("unidad-1", "b_tcp.txt", "text/plain"),
        ("unidad-1", "c_ip.pptx", PPTX_TYPE), ("unidad-1", "doble.docx.pdf", "application/pdf"),
    ]
    assert backend.processed == ["doc-1", "doc-2", "doc-3", "doc-4"]


def test_a_file_already_in_the_unit_is_not_uploaded_again(collect, tmp_path):
    backend = Backend([
        {"id": "doc-a", "unitId": "unidad-1", "fileName": "A_OSI.pdf", "status": "procesado"},
        {"id": "doc-b", "unitId": "unidad-1", "fileName": "b_tcp.txt", "status": "registrado"},
        {"id": "doc-c", "unitId": "otra", "fileName": "c_ip.pptx", "status": "procesado"},
    ])
    files = collect.corpus_files(corpus_dir(tmp_path))
    collect.ensure_materials(client(backend), {}, UNIT, files)
    assert [name for _, name, _ in backend.uploads] == ["c_ip.pptx", "doble.docx.pdf"]
    assert backend.processed == ["doc-b", "doc-4", "doc-5"]


def test_the_single_file_upload_is_the_same_as_before(collect):
    backend = Backend()
    collect.ensure_material(client(backend), {}, UNIT, EVALUATION / "corpus" / "protocols.txt")
    assert backend.uploads == [("unidad-1", "protocols.txt", "text/plain")]


def test_other_documents_already_in_the_unit_are_reported(collect, tmp_path):
    backend = Backend([
        {"id": "doc-x", "unitId": "unidad-1", "fileName": "viejo.txt", "status": "procesado"},
        {"id": "doc-w", "unitId": "unidad-1", "fileName": "TCP (Wikipedia).txt", "status": "procesado",
         "origin": {"topic": "TCP"}},
    ])
    extra = collect.ensure_materials(client(backend), {}, UNIT, collect.corpus_files(corpus_dir(tmp_path))[:1])
    assert extra == ["viejo.txt"]  # los temas de --topic se piden aparte y no cuentan


# Documentos por caso


def test_a_case_without_documents_uses_the_whole_corpus(collect, tmp_path):
    files = collect.corpus_files(corpus_dir(tmp_path))
    available = {f.name: f for f in files}
    assert collect.case_documents({"id": "c1"}, available) == files
    picked = collect.case_documents({"id": "c2", "documents": ["c_ip.pptx", "a_osi.pdf", "c_ip.pptx"]}, available)
    assert [f.name for f in picked] == ["c_ip.pptx", "a_osi.pdf"]


@pytest.mark.parametrize("documents", [[], ["no-existe.txt"], "a_osi.pdf", [""], ["README.md"]])
def test_unknown_or_malformed_documents_make_the_case_invalid(collect, tmp_path, documents):
    available = {f.name: f for f in collect.corpus_files(corpus_dir(tmp_path))}
    with pytest.raises(ValueError) as invalid:
        collect.validate_case({"id": "c-doc", "resourceType": "explicacion", "instructions": "x",
                               "documents": documents}, available)
    assert "c-doc" in str(invalid.value)


def test_cases_with_the_same_unit_title_share_one_unit_with_the_union_of_their_documents(collect, tmp_path):
    files = collect.corpus_files(corpus_dir(tmp_path))
    available = {f.name: f for f in files}
    base = {"resourceType": "explicacion", "instructions": "x"}
    cases = [
        {**base, "id": "c1", "unitTitle": "Redes", "outcomeText": "Explica", "documents": ["c_ip.pptx"]},
        {**base, "id": "c2", "unitTitle": "Redes", "outcomeText": "Explica", "documents": ["a_osi.pdf", "c_ip.pptx"]},
        {**base, "id": "c3", "unitTitle": "Otra", "outcomeText": "Explica", "documents": ["b_tcp.txt"]},
        {**base, "id": "c4", "unitTitle": "Otra", "outcomeText": "Explica", "documents": ["no-existe.txt"]},  # inválido
        {**base, "id": "c5"},  # la unidad de evaluación de siempre, con todo el corpus
    ]
    union = collect.unit_documents(cases, available)
    assert [f.name for f in union[("Redes", "Explica")]] == ["a_osi.pdf", "c_ip.pptx"]
    assert [f.name for f in union[("Otra", "Explica")]] == ["b_tcp.txt"]
    assert union[None] == files


# Expectativa «sin evidencia»


CASE = {"id": "C-06", "instructions": "¿Cómo se estructuran las tablas?", "expect": "no_evidence",
        "reference": "No hay evidencia suficiente."}


def status(state: str, steps: list[dict], failure: dict | None = None) -> dict:
    return {"id": "gen-req-6", "status": state, "steps": steps, "failure": failure}


def test_a_rejected_step_meets_the_expectation(collect):
    rejected = [{"position": 1, "resourceIds": [],
                 "rejections": [{"kind": "grounding", "title": "Tablas", "reason": "Sin respaldo en el material."}]}]
    record = collect.check_no_evidence(CASE, status("failed", rejected, {"code": "INSUFFICIENT_EVIDENCE",
                                                                         "message": "Sin evidencia."}), None, {}, 3.0)
    assert record["outcome"] == "pass" and record["resources"] == []
    assert record["case_id"] == "C-06" and record["expect"] == "no_evidence" and record["request_id"] == "gen-req-6"
    assert record["reference"] == "No hay evidencia suficiente." and "Sin respaldo en el material." in record["reason"]


def test_insufficient_evidence_before_drafting_meets_the_expectation(collect):
    failed = status("failed", [{"position": 1, "resourceIds": [],
                                "error": {"code": "INSUFFICIENT_EVIDENCE", "message": "Poca evidencia."}}],
                    {"code": "INSUFFICIENT_EVIDENCE", "message": "Poca evidencia."})
    assert collect.check_no_evidence(CASE, failed, None, {}, 1.0)["outcome"] == "pass"


def test_a_delivered_resource_breaks_the_expectation_and_is_kept(collect):
    delivered = status("succeeded", [{"position": 1, "resourceIds": ["rec-1"], "rejections": []}])
    stored = {"rec-1": {"id": "rec-1", "title": "Tablas y llaves", "body": "Una tabla tiene una llave primaria."}}
    record = collect.check_no_evidence(CASE, delivered, None, stored, 2.0)
    assert record["outcome"] == "fail"
    assert record["resources"] == [{"id": "rec-1", "title": "Tablas y llaves",
                                    "body": "Una tabla tiene una llave primaria."}]


@pytest.mark.parametrize(
    ("final", "failure"),
    [
        (None, {"code": "TIMEOUT", "message": "el pedido no terminó en 5 s"}),
        (status("failed", [{"position": 1, "resourceIds": [], "error": {"code": "GENERATION_FAILED",
                                                                         "message": "La IA no respondió."}}],
                {"code": "GENERATION_FAILED", "message": "La IA no respondió."}), None),
        (status("interrupted", [{"position": 1, "resourceIds": []}]), None),
    ],
)
def test_a_technical_failure_is_inconclusive(collect, final, failure):
    record = collect.check_no_evidence(CASE, final, failure, {}, 1.0)
    assert record["outcome"] == "error" and record["resources"] == []


def test_an_unknown_expectation_makes_the_case_invalid(collect):
    with pytest.raises(ValueError) as invalid:
        collect.validate_case({**CASE, "resourceType": "explicacion", "expect": "sin_recursos"}, {})
    assert "C-06" in str(invalid.value)


# Archivos de casos


def test_the_old_cases_still_validate_and_send_the_same_body(collect):
    corpus = EVALUATION / "corpus" / "protocols.txt"
    available = {f.name: f for f in collect.corpus_files(corpus)}
    for case in json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))["cases"]:
        collect.validate_case(case, available)
        assert collect.case_documents(case, available) == [corpus]
        assert collect.case_expectation(case) is None and collect.unit_spec(case) is None
    assert collect.unit_documents(json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))["cases"],
                                  available) == {None: [corpus]}


def test_the_t067_cases_use_their_documents_and_two_units(collect):
    available = {f.name: f for f in collect.corpus_files(EVALUATION / "corpus_t067")}
    assert sorted(available) == T067_FILES
    cases = json.loads((EVALUATION / "cases_t067.json").read_text(encoding="utf-8"))["cases"]
    assert [case["id"] for case in cases] == ["C-01", "C-02", "C-03", "C-04", "C-05", "C-06"]
    for case in cases:
        collect.validate_case(case, available)
        assert case["resourceType"] == "explicacion" and case["stage"] == "explain"
        assert case["quantity"] == 1 and case["topK"] == 8 and case["reference"].strip()
    *answered, distractor = cases
    assert all(collect.case_expectation(case) is None and sorted(case["documents"]) == T067_FILES
               for case in answered)
    assert collect.case_expectation(distractor) == "no_evidence"
    assert sorted(distractor["documents"]) == sorted(NETWORK_FILES)
    units = collect.unit_documents(cases, available)
    assert len(units) == 2 and collect.unit_spec(distractor) != collect.unit_spec(answered[0])


# La corrida completa contra un backend falso


class FullBackend(Backend):
    """Cuentas, cursos, documentos y pedidos: el caso «with-resource» entrega un recurso y los demás, según su
    nombre, se rechazan por falta de evidencia."""

    def __init__(self) -> None:
        super().__init__()
        self.courses: list[dict] = []
        self.requests: dict[str, dict] = {}
        self.resources: dict[str, list[dict]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None
        if path == "/api/v1/accounts":
            return httpx.Response(201, json={"token": "token-falso"})
        if path == "/api/v1/courses":
            if method == "GET":
                return httpx.Response(200, json=self.courses)
            number = len(self.courses) + 1
            course = {**body, "id": f"curso-{number}", "units": [
                {**unit, "id": f"unidad-{number}", "outcomes": [{"id": f"ra-{number}", **o} for o in unit["outcomes"]]}
                for unit in body["units"]
            ]}
            self.courses.append(course)
            return httpx.Response(201, json=course)
        if path == "/api/v1/generation-requests" and method == "POST":
            request_id = f"gen-req-{len(self.requests) + 1}"
            delivers = "con recurso" in body["instructions"]
            resource_ids = [f"rec-{request_id}"] if delivers else []
            if delivers:
                self.resources.setdefault(body["unitId"], []).append({
                    "id": resource_ids[0], "title": "Explicación", "body": f"Sobre: {body['instructions']}",
                    "evidence": [{"text": "TCP confirma la entrega."}], "citations": [{"fragmentIds": ["f1"]}],
                })
            rejections = [] if delivers else [{"kind": "grounding", "title": "x", "reason": "Sin respaldo."}]
            self.requests[request_id] = {
                "id": request_id, "status": "succeeded" if delivers else "failed",
                "steps": [{"position": 1, "stage": "explain", "resourceType": "explicacion",
                           "resourceIds": resource_ids, "rejections": rejections,
                           "generator": {"description": "reglas", "usesAi": False, "fallback": False}}],
                "failure": None if delivers else {"code": "INSUFFICIENT_EVIDENCE", "message": "Sin evidencia."},
            }
            return httpx.Response(202, json={"id": request_id, "status": "queued", "steps": []})
        if path.startswith("/api/v1/generation-requests/") and path.endswith("/evidence"):
            return httpx.Response(200, json={"requestId": path.split("/")[-2], "retrievalMode": "bm25_fallback",
                                             "limit": 8, "retrievedAt": "2026-11-13T00:00:00Z",
                                             "fragments": [{"text": "TCP confirma la entrega."}]})
        if path.startswith("/api/v1/generation-requests/"):
            return httpx.Response(200, json=self.requests[path.split("/")[-1]])
        if path.startswith("/api/v1/units/") and path.endswith("/resources"):
            return httpx.Response(200, json=self.resources.get(path.split("/")[-2], []))
        return super().__call__(request)


def test_a_run_uploads_each_unit_once_and_writes_expectations_apart_from_samples(collect, tmp_path, monkeypatch,
                                                                                capsys):
    corpus = corpus_dir(tmp_path)
    common = {"unitTitle": "Redes", "outcomeText": "Explica", "resourceType": "explicacion", "stage": "explain"}
    cases = [
        {**common, "id": "C-01", "documents": ["a_osi.pdf"], "instructions": "Pregunta con recurso.",
         "reference": "Respuesta."},
        {**common, "id": "C-02", "documents": ["b_tcp.txt", "a_osi.pdf"], "instructions": "Otra con recurso."},
        {**common, "id": "C-03", "unitTitle": "Sin bases", "documents": ["b_tcp.txt"],
         "instructions": "Pregunta fuera del tema.", "expect": "no_evidence", "reference": "No hay evidencia."},
        {**common, "id": "C-04", "unitTitle": "Sin bases", "documents": ["b_tcp.txt"],
         "instructions": "Pregunta fuera del tema con recurso.", "expect": "no_evidence"},
    ]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    out = tmp_path / "results" / "samples.jsonl"
    backend = FullBackend()
    real_client = httpx.Client
    monkeypatch.setattr(collect.httpx, "Client",
                        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(backend)))
    monkeypatch.setenv("EVAL_EMAIL", "evaluacion@correo.pe")
    monkeypatch.setenv("EVAL_PASSWORD", "clave-segura-9")
    monkeypatch.setattr(sys, "argv", ["collect_samples.py", "--cases", str(cases_path), "--corpus", str(corpus),
                                      "--out", str(out), "--poll", "0", "--timeout", "5", "--retries", "0"])
    collect.main()

    # Una unidad por título, con la unión de sus documentos, subidos una sola vez.
    assert sorted(backend.uploads) == [("unidad-1", "a_osi.pdf", "application/pdf"),
                                       ("unidad-1", "b_tcp.txt", "text/plain"),
                                       ("unidad-2", "b_tcp.txt", "text/plain")]
    samples = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [s["case_id"] for s in samples] == ["C-01", "C-02"] and samples[0]["reference"] == "Respuesta."
    expectations = [json.loads(line) for line in (out.parent / "expectations.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert [(e["case_id"], e["outcome"]) for e in expectations] == [("C-03", "pass"), ("C-04", "fail")]
    assert expectations[1]["resources"][0]["body"] == "Sobre: Pregunta fuera del tema con recurso."
    assert (out.parent / "failures.jsonl").read_text(encoding="utf-8") == ""
    printed = capsys.readouterr().out
    assert re.search(r"C-03 · no_evidence: cumple", printed) and re.search(r"C-04 · no_evidence: NO cumple", printed)

