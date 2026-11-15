"""Exportador SCORM 1.2 multirrecurso para Chamilo, Canvas y cualquier LMS compatible con SCORM 1.2.

Cada recurso aprobado es un SCO: una página HTML propia, en el orden de la clase 5E, con sus archivos (gráficos SVG,
imágenes y audios) dentro del paquete y declarados en el manifiesto. Las páginas de contenido se marcan «completadas»
al abrirse; las preguntas y las actividades interactivas se califican en la página y envían el puntaje al LMS con la
API de SCORM 1.2. Todo va en la raíz del .zip, sin carpeta contenedora.

Gamificación (HU-051, ADR-012): los ítems de opción múltiple no van en páginas sueltas, sino juntos en un SCO
«Evaluación por niveles». Los niveles salen de la dificultad del pedido; el nivel siguiente se desbloquea al
responder el anterior, cada pregunta suma los puntos de su nivel, un cronómetro mide el tiempo y al final se
muestra la insignia. El LMS recibe el porcentaje de puntos, aprobado o desaprobado y el tiempo de la sesión.

Reto de predicción (HU-047, ADR-020): actividad de Enganchar. El estudiante elige una opción en cada pregunta y ve al
instante lo que dice el material y de dónde sale; suma puntos y racha, y al final recibe una insignia. Como es para
iniciar la clase, el LMS recibe el porcentaje de aciertos pero la actividad se marca «completada», no aprobada o
desaprobada.
"""
from __future__ import annotations

import html
import io
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile, UnitExporterPort
from platform5e.domain.generation.gamification import BADGES, PASSING_PERCENT, Level, by_level
from platform5e.domain.generation.resource_formats import AUDIO, IMAGE, INTERACTIVE, VISUAL, resource_format
from platform5e.infrastructure.exporters.visual_renderer import SvgVisualRenderer, can_render
from platform5e.infrastructure.html_sanitizer import clean_html

STAGE_ORDER = ("engage", "explore", "explain", "elaborate", "evaluate")
STAGE_LABELS = {
    "engage": "Para iniciar la clase",
    "explore": "Para explorar",
    "explain": "Para explicar",
    "elaborate": "Para aplicar",
    "evaluate": "Para evaluar",
}
# Quitar "descartado" cuando los valores guardados estén migrados al inglés.
DISCARDED = {"discarded", "descartado"}
LETTERS = "abcdefghij"
FIXED_DATE = (2026, 1, 1, 0, 0, 0)  # fecha fija en el zip: el mismo contenido da el mismo archivo
QUIZ_TITLE = "Evaluación por niveles"


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n{2,}", text or "") if p.strip()]
    return "".join(f"<p>{_esc(p).replace(chr(10), '<br>')}</p>" for p in parts)


def body_html(resource: Mapping) -> str:
    """El texto con formato del editor (limpio) o, si no se editó, los párrafos del texto generado."""
    formatted = clean_html(resource.get("bodyHtml"))
    return formatted or _paragraphs(resource.get("body", ""))


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def media_files(resource: Mapping, number: int) -> list[tuple[str, bytes]]:
    """Archivos del recurso dentro del paquete: el gráfico SVG o el archivo generado (imagen o audio)."""
    stored = resource.get("mediaFile")
    if stored:
        extension = str(stored.get("fileName", "")).rsplit(".", 1)[-1].lower() or "bin"
        return [(f"media/{number:02d}.{extension}", stored["content"])]
    kind = resource_format(resource.get("type", ""))
    if kind in (VISUAL, IMAGE) and can_render(resource.get("type", "")) and resource.get("structure"):
        return [(f"media/{number:02d}.svg", SvgVisualRenderer().render(resource).encode("utf-8"))]
    return []


def _media_block(resource: Mapping, files: list[tuple[str, bytes]]) -> str:
    kind = resource_format(resource.get("type", ""))
    structure = resource.get("structure") or {}
    if kind in (VISUAL, IMAGE) and files:
        alt = structure.get("alt") or resource.get("title")
        caption = structure.get("caption") if kind == IMAGE else ""
        figcaption = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
        return f'<figure class="visual"><img src="../{files[0][0]}" alt="{_esc(alt)}">{figcaption}</figure>'
    if kind == AUDIO:
        script = structure.get("script") or resource.get("body", "")
        player = (
            f'<audio controls preload="metadata" src="../{files[0][0]}"></audio>'
            if files
            else '<button type="button" class="speak" data-speak="script">Escuchar con la voz del navegador</button>'
        )
        return (
            f'<section class="audio">{player}'
            f'<details{" open" if not files else ""}><summary>Guion del audio</summary>'
            f'<p id="script">{_esc(script)}</p></details></section>'
        )
    if kind == INTERACTIVE:
        data = {"type": resource.get("type"), "structure": _with_item_sources(resource, structure)}
        if resource.get("type") == "reto_prediccion":
            data["badges"] = [{"min": threshold, "name": name} for threshold, name in BADGES]
        preparation = _preparation(structure) if resource.get("type") == "actividad_kinestesica" else ""
        return (
            f'{preparation}<form id="activity" class="activity"><div class="activity__items"></div>'
            '<button type="submit">Comprobar</button><p class="feedback" role="status" aria-live="polite"></p></form>'
            f'<script type="application/json" id="activity-data">{_json_for_script(data)}</script>'
        )
    return ""


# Actividades cuyos elementos citan su fragmento: tipo -> llave de la lista en la estructura.
SOURCED_LISTS = {
    "exploracion_guiada": "guidedSteps",
    "actividad_kinestesica": "guidedSteps",  # T059 (REV-01)
    "reto_prediccion": "predictions",
    "caso_aplicado": "criteria",
}


def _preparation(structure: Mapping) -> str:
    """T059 (REV-01): materiales, tiempo estimado y espacio de la actividad kinestésica, antes de sus pasos."""
    materials = [m for m in structure.get("materials") or [] if m]
    materials_html = (
        "<ul>" + "".join(f"<li>{_esc(m)}</li>" for m in materials) + "</ul>"
        if materials else "<p>Sin materiales especiales.</p>"
    )
    return (
        '<section class="preparation"><h2>Antes de empezar</h2>'
        f"<p><strong>Materiales:</strong></p>{materials_html}"
        f'<p><strong>Tiempo estimado:</strong> {_esc(structure.get("estimatedMinutes"))} minutos</p>'
        f'<p><strong>Espacio:</strong> {_esc(structure.get("space"))}</p></section>'
    )


def _with_item_sources(resource: Mapping, structure: Mapping) -> Mapping:
    """HU-048, HU-047 y HU-050: cada paso de la exploración guiada, cada predicción del reto y cada criterio del caso
    aplicado muestran de qué parte del material salen (documento y página)."""
    key = SOURCED_LISTS.get(resource.get("type", ""))
    if not key:
        return structure
    labels = {
        evidence.get("id"): ", ".join(x for x in (evidence.get("documentName"), evidence.get("location")) if x)
        for evidence in resource.get("evidence") or []
    }
    items = [
        {**item, "source": "; ".join(labels[f_id] for f_id in item.get("fragmentIds") or [] if labels.get(f_id))}
        for item in structure.get(key) or []
    ]
    return {**structure, key: items}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "unidad"


def _exported_options(resource: Mapping) -> list[Mapping]:
    """La clave y los distractores aceptados o editados; los descartados no se exportan."""
    return [o for o in (resource.get("options") or []) if o.get("isCorrect") or o.get("decision") not in DISCARDED]


def _sources(resource: Mapping) -> str:
    seen, items = set(), []
    for evidence in resource.get("evidence") or []:
        label = ", ".join(x for x in (evidence.get("documentName"), evidence.get("location")) if x)
        if label and label not in seen:
            seen.add(label)
            items.append(f"<li>{_esc(label)}</li>")
    return f'<footer><h2>Fuentes del material</h2><ul>{"".join(items)}</ul></footer>' if items else ""


def _question(options: list[Mapping]) -> str:
    choices = "".join(
        f'<label class="choice"><input type="radio" name="answer" value="{i}" '
        f'data-correct="{"true" if o.get("isCorrect") else "false"}" data-feedback="{_esc(o.get("feedback"))}"> '
        f"<span>{LETTERS[i]}) {_esc(o.get('text'))}</span></label>"
        for i, o in enumerate(options)
    )
    return (
        '<form id="question"><fieldset><legend>Elige una respuesta</legend>'
        f"{choices}</fieldset>"
        '<button type="submit">Comprobar</button><p class="feedback" role="status" aria-live="polite"></p></form>'
    )


def _sco_page(resource: Mapping, files: list[tuple[str, bytes]] | None = None) -> str:
    options = _exported_options(resource) if resource.get("options") else []
    is_activity = resource_format(resource.get("type", "")) == INTERACTIVE
    kind = "question" if options else "activity" if is_activity else "content"
    stage = STAGE_LABELS.get(resource.get("stage", ""), "")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(resource.get("title"))}</title>
<link rel="stylesheet" href="../shared/style.css">
<script src="../shared/scorm.js"></script>
<script src="../shared/activity.js"></script>
</head>
<body data-kind="{kind}">
<main>
<p class="stage">{_esc(stage)}</p>
<h1>{_esc(resource.get("title"))}</h1>
{body_html(resource)}
{_media_block(resource, files or [])}
{_question(options) if options else ""}
{_sources(resource)}
</main>
</body>
</html>
"""


@dataclass(frozen=True)
class LeveledQuiz:
    """Los ítems de opción múltiple de la unidad, que se exportan juntos como una evaluación por niveles."""

    items: tuple[Mapping, ...]


def is_quiz_item(resource: Mapping) -> bool:
    return bool(resource.get("options")) and bool(_exported_options(resource))


def _quiz_item(resource: Mapping, number: int, level: Level, locked: bool) -> str:
    off = " disabled" if locked else ""
    choices = "".join(
        f'<label class="choice"><input type="radio" name="q{number}" value="{i}"{off} '
        f'data-correct="{"true" if o.get("isCorrect") else "false"}" data-feedback="{_esc(o.get("feedback"))}"> '
        f"<span>{LETTERS[i]}) {_esc(o.get('text'))}</span></label>"
        for i, o in enumerate(_exported_options(resource))
    )
    return (
        f'<form class="quiz-item" data-points="{level.points}">'
        f'<h3>Pregunta {number}. {_esc(resource.get("title"))}</h3>{body_html(resource)}'
        f"<fieldset><legend>Elige una respuesta</legend>{choices}</fieldset>"
        f'<button type="submit"{off}>Comprobar</button>'
        '<p class="feedback" role="status" aria-live="polite"></p></form>'
    )


def _quiz_page(quiz: LeveledQuiz) -> str:
    groups = by_level(list(quiz.items))
    total = sum(level.points * len(items) for level, items in groups)
    sections, number = [], 0
    for index, (level, items) in enumerate(groups):
        locked = index > 0
        questions = ""
        for resource in items:
            number += 1
            questions += _quiz_item(resource, number, level, locked)
        sections.append(
            f'<section class="level{" level--locked" if locked else ""}" data-level="{index + 1}">'
            f'<h2>{_esc(level.title)} <span class="level__points">{level.points} puntos por pregunta</span></h2>'
            f'<p class="level__lock"{"" if locked else " hidden"}>Se desbloquea al responder el nivel anterior.</p>'
            f"{questions}</section>"
        )
    config = {"total": total, "passing": PASSING_PERCENT, "badges": [list(b) for b in BADGES]}
    evidence = {"evidence": [e for r in quiz.items for e in (r.get("evidence") or [])]}
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{QUIZ_TITLE}</title>
<link rel="stylesheet" href="../shared/style.css">
<script src="../shared/scorm.js"></script>
<script src="../shared/quiz.js"></script>
</head>
<body data-kind="quiz">
<main>
<p class="stage">{STAGE_LABELS["evaluate"]}</p>
<h1>{QUIZ_TITLE}</h1>
<p>Responde las preguntas de cada nivel para desbloquear el siguiente. Cada respuesta correcta suma los puntos de
su nivel; al terminar verás tu puntaje, tu tiempo y tu insignia.</p>
<div class="hud" aria-label="Progreso">
<p>Puntaje <strong id="quiz-score">0</strong> de {total}</p>
<p>Nivel <strong id="quiz-level">1</strong> de {len(groups)}</p>
<p>Tiempo <strong id="quiz-clock">00:00</strong></p>
</div>
<p id="quiz-status" class="quiz-status" role="status" aria-live="polite"></p>
{"".join(sections)}
<section id="quiz-result" class="result" hidden>
<h2>Resultado</h2>
<p class="result__badge"></p>
<p class="result__summary"></p>
<button type="button" id="quiz-retry">Intentar de nuevo</button>
</section>
<script type="application/json" id="quiz-data">{_json_for_script(config)}</script>
{_sources(evidence)}
</main>
</body>
</html>
"""


def _file_tags(names: list[str]) -> str:
    return "".join('<file href="' + name + '"/>' for name in names)


def _manifest(package_id: str, title: str, pages: list[tuple[str, str]], files: list[list[str]] | None = None) -> str:
    files = files or [[] for _ in pages]
    items = "".join(
        f'\n      <item identifier="ITEM_{n}" identifierref="RES_{n}" isvisible="true"><title>{_esc(t)}</title></item>'
        for n, (_, t) in enumerate(pages, start=1)
    )
    resources = "".join(
        f'\n    <resource identifier="RES_{n}" type="webcontent" adlcp:scormtype="sco" href="{href}">'
        f'<file href="{href}"/>{_file_tags(extra)}<dependency identifierref="SHARED"/></resource>'
        for n, ((href, _), extra) in enumerate(zip(pages, files), start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{package_id}" version="1.0"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
  <organizations default="ORG_1">
    <organization identifier="ORG_1">
      <title>{_esc(title)}</title>{items}
    </organization>
  </organizations>
  <resources>{resources}
    <resource identifier="SHARED" type="webcontent" adlcp:scormtype="asset">
      <file href="shared/scorm.js"/><file href="shared/style.css"/><file href="shared/activity.js"/><file href="shared/quiz.js"/>
    </resource>
  </resources>
</manifest>
"""


SCORM_JS = r"""/* API de SCORM 1.2: busca el objeto API que expone el LMS en las ventanas superiores. */
(function () {
  'use strict';
  function findApi(win) {
    for (var i = 0; win && i < 10; i++) {
      if (win.API) return win.API;
      if (win.parent === win) break;
      win = win.parent;
    }
    return null;
  }
  var api = findApi(window) || (window.opener ? findApi(window.opener) : null);
  var finished = false;

  function setValue(name, value) { if (api) api.LMSSetValue(name, String(value)); }

  function report(percent) {
    setValue('cmi.core.score.min', 0);
    setValue('cmi.core.score.max', 100);
    setValue('cmi.core.score.raw', Math.round(percent));
    setValue('cmi.core.lesson_status', percent >= 60 ? 'passed' : 'failed');
    if (api) api.LMSCommit('');
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  // cmi.core.session_time (CMITimespan de SCORM 1.2): HH:MM:SS.
  function reportTime(seconds) {
    setValue('cmi.core.session_time', pad(Math.floor(seconds / 3600)) + ':' + pad(Math.floor((seconds % 3600) / 60)) + ':' + pad(seconds % 60));
  }
  // HU-047: actividad para iniciar la clase; se registra el puntaje, pero no se aprueba ni se desaprueba.
  function complete(percent) {
    setValue('cmi.core.score.min', 0);
    setValue('cmi.core.score.max', 100);
    setValue('cmi.core.score.raw', Math.round(percent));
    setValue('cmi.core.lesson_status', 'completed');
    if (api) api.LMSCommit('');
  }
  window.scorm5e = { report: report, complete: complete, time: reportTime };

  function speak(button) {
    var target = document.getElementById(button.getAttribute('data-speak'));
    if (!target || !window.speechSynthesis) { button.textContent = 'Este navegador no puede leer el guion en voz alta.'; return; }
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(target.textContent);
    utterance.lang = 'es-ES';
    window.speechSynthesis.speak(utterance);
  }

  function start() {
    if (!api) return; // fuera del LMS (vista previa local) la página funciona igual
    api.LMSInitialize('');
    var status = api.LMSGetValue('cmi.core.lesson_status');
    if (document.body.getAttribute('data-kind') === 'content') setValue('cmi.core.lesson_status', 'completed');
    else if (!status || status === 'not attempted') setValue('cmi.core.lesson_status', 'incomplete');
    api.LMSCommit('');
  }

  function finish() {
    if (!api || finished) return;
    finished = true;
    api.LMSCommit('');
    api.LMSFinish('');
  }

  function grade(event) {
    event.preventDefault();
    var form = event.currentTarget;
    var chosen = form.querySelector('input[name="answer"]:checked');
    var out = form.querySelector('.feedback');
    if (!chosen) { out.textContent = 'Elige una alternativa.'; return; }
    var correct = chosen.getAttribute('data-correct') === 'true';
    // La retroalimentación puede empezar con «Correcto.» o «Incorrecto.»: se quita para no repetirlo.
    var note = (chosen.getAttribute('data-feedback') || '').replace(/^\s*(in)?correcto[.:,]?\s*/i, '');
    out.textContent = (correct ? 'Correcto. ' : 'Incorrecto. ') + note;
    out.className = 'feedback ' + (correct ? 'is-correct' : 'is-wrong');
    setValue('cmi.core.score.min', 0);
    setValue('cmi.core.score.max', 100);
    setValue('cmi.core.score.raw', correct ? 100 : 0);
    setValue('cmi.core.lesson_status', correct ? 'passed' : 'failed');
    if (api) api.LMSCommit('');
  }

  window.addEventListener('load', function () {
    start();
    var form = document.getElementById('question');
    if (form) form.addEventListener('submit', grade);
    var buttons = document.querySelectorAll('[data-speak]');
    for (var i = 0; i < buttons.length; i++) buttons[i].addEventListener('click', function (e) { speak(e.currentTarget); });
  });
  window.addEventListener('pagehide', finish);
  window.addEventListener('beforeunload', finish);
})();
"""

STYLE_CSS = """body{margin:0;font-family:Georgia,'Times New Roman',serif;color:#1f2328;background:#fff;line-height:1.6}
main{max-width:46rem;margin:0 auto;padding:1.5rem 1rem 3rem}
h1{font-size:1.6rem;line-height:1.25;margin:.25rem 0 1rem}
.stage{margin:0;font:600 .8rem/1.4 system-ui,sans-serif;text-transform:uppercase;letter-spacing:.06em;color:#5b6470}
fieldset{border:1px solid #d0d7de;border-radius:8px;padding:1rem;margin:1.5rem 0 1rem}
legend{font:600 .95rem system-ui,sans-serif;padding:0 .25rem}
.choice{display:flex;gap:.5rem;align-items:flex-start;padding:.4rem 0;cursor:pointer}
button{font:600 1rem system-ui,sans-serif;padding:.6rem 1.2rem;border:0;border-radius:6px;background:#1f5fae;color:#fff;cursor:pointer}
.feedback{min-height:1.5rem;font-family:system-ui,sans-serif}
.is-correct{color:#1a7f37}.is-wrong{color:#b42318}
footer{margin-top:2.5rem;border-top:1px solid #d0d7de;font:.85rem/1.5 system-ui,sans-serif;color:#5b6470}
footer h2{font-size:.85rem;margin:1rem 0 .25rem}
figure.visual{margin:1.5rem 0}figure.visual img{max-width:100%;height:auto;border:1px solid #d0d7de;border-radius:8px}
figcaption{font:.9rem/1.4 system-ui,sans-serif;color:#5b6470;margin-top:.5rem}
.audio{margin:1.5rem 0}.audio audio{width:100%}.audio summary{cursor:pointer;font:600 .95rem system-ui,sans-serif}
.speak{margin-bottom:.75rem}
.activity__items{display:grid;gap:.75rem;margin:1.5rem 0 1rem}
.row{border:1px solid #d0d7de;border-radius:8px;padding:.75rem;font-family:system-ui,sans-serif}
.row select,.row input[type=text]{font:1rem system-ui,sans-serif;padding:.35rem;margin-top:.35rem;max-width:100%}
.row .note{display:block;font-size:.9rem;margin-top:.35rem}
.row--ok{border-color:#1a7f37}.row--bad{border-color:#b42318}
.step textarea{width:100%;box-sizing:border-box;margin-top:.35rem;font:inherit}.step .source{font-size:.85rem;color:#555}
.prediction .option{display:inline-block;margin:.35rem .5rem 0 0;background:#eef2f6;color:#1f2328;font-weight:500}
.prediction .option--right{background:#1a7f37;color:#fff}.prediction .option--wrong{background:#b42318;color:#fff}
.prediction .option:disabled{cursor:default;opacity:1}.prediction .reveal{margin:.6rem 0 0}.prediction .source{display:block;font-size:.85rem;color:#555}
.case{margin:1rem 0;padding:1rem;border-left:4px solid #1f5fae;background:#f3f6f9;font-family:system-ui,sans-serif}
.case p{margin:.4rem 0}.case textarea{width:100%;box-sizing:border-box;margin-top:.35rem;font:inherit}
.criterion label{display:flex;gap:.5rem;align-items:flex-start}
.criterion .source{display:block;font-size:.85rem;color:#555}
.order{display:flex;gap:.5rem;align-items:center}.order span{flex:1}
.order button{padding:.2rem .6rem;background:#eef2f6;color:#1f2328}
h2,h3{font-family:system-ui,sans-serif}
.hud{position:sticky;top:0;z-index:1;display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;margin:1rem 0;padding:.6rem 1rem;background:#f3f6f9;border:1px solid #d0d7de;border-radius:8px;font:1rem system-ui,sans-serif}
.hud p{margin:0}.hud strong{font-variant-numeric:tabular-nums}
.quiz-status{margin:0;font:600 1rem system-ui,sans-serif;color:#1a7f37}.quiz-status:empty{display:none}
.level{margin:1.5rem 0}.level h2{font-size:1.15rem;display:flex;flex-wrap:wrap;align-items:center;gap:.5rem}
.level__points{font:600 .8rem system-ui,sans-serif;padding:.15rem .6rem;border-radius:999px;background:#ddf4ff;color:#0a3069}
.level__lock{font:.95rem system-ui,sans-serif;color:#5b6470}
.level--locked .quiz-item{opacity:.5}
.quiz-item{border:1px solid #d0d7de;border-radius:8px;padding:1rem;margin:1rem 0}
.quiz-item h3{font-size:1rem;margin:0 0 .5rem}.quiz-item fieldset{margin:1rem 0 .75rem}
.quiz-item.is-answered button{display:none}.quiz-item .feedback{margin:.5rem 0 0}.quiz-item .feedback:empty{display:none}
button:disabled{background:#d0d7de;color:#57606a;cursor:not-allowed}
.result{margin:2rem 0;padding:1.25rem;border:2px solid #1f5fae;border-radius:8px;font-family:system-ui,sans-serif}
.result h2{margin-top:0}.result__badge{font:700 1.4rem system-ui,sans-serif;margin:.25rem 0}
.badge--oro{color:#7a5300}.badge--plata{color:#424a53}.badge--bronce{color:#8a3c0c}.badge--none{color:#5b6470}
"""

ACTIVITY_JS = r"""/* Actividades interactivas: emparejar, verdadero o falso, completar, ordenar, exploración guiada,
   actividad kinestésica, reto de predicción y caso aplicado.
   Envían el puntaje con scorm5e. */
(function () {
  'use strict';
  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    for (var key in attrs) node.setAttribute(key, attrs[key]);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function shuffle(list) {
    var copy = list.slice();
    for (var i = copy.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = copy[i]; copy[i] = copy[j]; copy[j] = t; }
    return copy;
  }
  function norm(text) {
    return String(text || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9ñ ]/g, ' ').replace(/\s+/g, ' ').trim();
  }
  function mark(row, ok, note) {
    row.className = 'row ' + (ok ? 'row--ok' : 'row--bad');
    var out = row.querySelector('.note') || row.appendChild(el('span', { 'class': 'note' }));
    out.textContent = (ok ? 'Correcto. ' : 'Revisa: ') + (note || '');
  }

  var builders = {
    emparejamiento: function (s, box) {
      var definitions = shuffle(s.pairs.map(function (p) { return p.definition; }));
      return s.pairs.map(function (pair, i) {
        var row = el('div', { 'class': 'row' });
        var id = 'm' + i;
        row.appendChild(el('label', { 'for': id }, pair.term));
        var select = el('select', { id: id });
        select.appendChild(el('option', { value: '' }, 'Elige la descripción…'));
        definitions.forEach(function (d) { select.appendChild(el('option', { value: d }, d)); });
        row.appendChild(select);
        box.appendChild(row);
        return function () { var ok = select.value === pair.definition; mark(row, ok, ok ? '' : pair.definition); return ok; };
      });
    },
    verdadero_falso: function (s, box) {
      return s.statements.map(function (st, i) {
        var row = el('fieldset', { 'class': 'row' });
        row.appendChild(el('legend', {}, st.text));
        ['Verdadero', 'Falso'].forEach(function (label, k) {
          var wrap = el('label', { 'class': 'choice' });
          wrap.appendChild(el('input', { type: 'radio', name: 't' + i, value: k === 0 ? 'true' : 'false' }));
          wrap.appendChild(el('span', {}, label));
          row.appendChild(wrap);
        });
        box.appendChild(row);
        return function () {
          var chosen = row.querySelector('input:checked');
          var ok = !!chosen && (chosen.value === 'true') === st.isTrue;
          mark(row, ok, st.feedback || (st.isTrue ? 'Es verdadera.' : 'Es falsa.'));
          return ok;
        };
      });
    },
    completar_espacios: function (s, box) {
      return s.blanks.map(function (b, i) {
        var row = el('div', { 'class': 'row' });
        var id = 'c' + i;
        row.appendChild(el('label', { 'for': id }, b.sentence));
        var input = el('input', { type: 'text', id: id, autocomplete: 'off' });
        row.appendChild(input);
        box.appendChild(row);
        return function () { var ok = norm(input.value) === norm(b.answer); mark(row, ok, ok ? '' : 'La respuesta es «' + b.answer + '».'); return ok; };
      });
    },
    exploracion_guiada: function (s, box) {
      // HU-048: no hay respuesta correcta; el paso cuenta cuando el estudiante registra lo que encontró.
      return s.guidedSteps.map(function (step, i) {
        var row = el('fieldset', { 'class': 'row step' });
        row.appendChild(el('legend', {}, 'Paso ' + (i + 1) + '. ' + step.title));
        row.appendChild(el('p', {}, step.instruction));
        if (step.source) row.appendChild(el('p', { 'class': 'source' }, 'Fuente: ' + step.source));
        var id = 'g' + i;
        row.appendChild(el('label', { 'for': id }, step.question));
        var answer = el('textarea', { id: id, rows: '3' });
        row.appendChild(answer);
        box.appendChild(row);
        return function () {
          var ok = answer.value.trim().split(/\s+/).length >= 3;
          row.className = 'row step ' + (ok ? 'row--ok' : 'row--bad');
          var out = row.querySelector('.note') || row.appendChild(el('span', { 'class': 'note' }));
          out.textContent = ok ? 'Registro guardado.' : 'Escribe al menos una idea con tus palabras.';
          return ok;
        };
      });
    },
    actividad_kinestesica: function (s, box) {
      // T059 (REV-01): actividad con el cuerpo en el aula. Cada paso con su consigna, la pregunta si la tiene, la
      // fuente, la casilla «Lo hicimos» y un campo opcional para anotar lo observado. El paso cuenta al marcarlo.
      return s.guidedSteps.map(function (step, i) {
        var row = el('fieldset', { 'class': 'row step' });
        row.appendChild(el('legend', {}, 'Paso ' + (i + 1) + '. ' + step.title));
        row.appendChild(el('p', {}, step.instruction));
        if (step.question) row.appendChild(el('p', { 'class': 'question' }, step.question));
        if (step.source) row.appendChild(el('p', { 'class': 'source' }, 'Fuente: ' + step.source));
        var doneLabel = el('label', { 'class': 'choice' });
        var done = el('input', { type: 'checkbox', id: 'k' + i });
        doneLabel.appendChild(done);
        doneLabel.appendChild(el('span', {}, 'Lo hicimos'));
        row.appendChild(doneLabel);
        var id = 'ko' + i;
        row.appendChild(el('label', { 'for': id }, '¿Qué observaron? (opcional)'));
        row.appendChild(el('textarea', { id: id, rows: '2' }));
        box.appendChild(row);
        return function () {
          var ok = done.checked;
          row.className = 'row step ' + (ok ? 'row--ok' : 'row--bad');
          var out = row.querySelector('.note') || row.appendChild(el('span', { 'class': 'note' }));
          out.textContent = ok ? 'Paso hecho.' : 'Marquen «Lo hicimos» cuando terminen este paso.';
          return ok;
        };
      });
    },
    reto_prediccion: function (s, box, activity) {
      // HU-047: el estudiante predice; al elegir ve al instante lo que dice el material y suma puntos y racha.
      var POINTS = 100, STREAK_BONUS = 50;
      var form = box.parentNode;
      var submit = form.querySelector('button[type=submit]');
      if (submit) submit.hidden = true;
      var hud = el('div', { 'class': 'hud', role: 'status', 'aria-live': 'polite' });
      var scoreOut = el('strong', {}, '0');
      var streakOut = el('strong', {}, '0');
      var pointsP = el('p', {}, 'Puntos: '); pointsP.appendChild(scoreOut);
      var streakP = el('p', {}, 'Racha: '); streakP.appendChild(streakOut);
      hud.appendChild(pointsP); hud.appendChild(streakP);
      box.parentNode.insertBefore(hud, box);
      var score = 0, streak = 0, answered = 0, hits = 0;
      var total = s.predictions.length;
      var maxScore = POINTS * total + STREAK_BONUS * Math.max(0, total - 1);
      function finish() {
        var percent = total ? (100 * hits) / total : 0;
        var badge = null;
        (activity.badges || []).forEach(function (b) { if (!badge && percent >= b.min) badge = b.name; });
        var out = form.querySelector('.feedback');
        out.className = 'feedback result';
        out.textContent = '';
        out.appendChild(el('strong', {}, hits + ' de ' + total + ' predicciones acertadas · ' + score + ' de ' + maxScore + ' puntos. '));
        out.appendChild(el('span', { 'class': 'result__badge' }, badge ? 'Insignia: ' + badge + '. ' : ''));
        out.appendChild(el('span', {}, 'No se trata de acertar: compara tus predicciones con lo que verás en la clase.'));
        if (window.scorm5e && window.scorm5e.complete) window.scorm5e.complete(percent);
      }
      return s.predictions.map(function (pr, i) {
        var row = el('fieldset', { 'class': 'row prediction' });
        row.appendChild(el('legend', {}, (i + 1) + '. ' + pr.question));
        var options = shuffle([pr.correctOption, pr.otherOption, pr.extraOption].filter(function (o) { return o; }));
        var buttons = options.map(function (option) {
          var button = el('button', { type: 'button', 'class': 'option' }, option);
          row.appendChild(button);
          return button;
        });
        var reveal = el('p', { 'class': 'reveal', hidden: 'hidden' });
        row.appendChild(reveal);
        box.appendChild(row);
        var hit = false, done = false;
        buttons.forEach(function (button) {
          button.addEventListener('click', function () {
            if (done) return;
            done = true;
            hit = button.textContent === pr.correctOption;
            buttons.forEach(function (b) {
              b.disabled = true;
              if (b.textContent === pr.correctOption) b.className = 'option option--right';
            });
            if (!hit) button.className = 'option option--wrong';
            if (hit) { streak += 1; hits += 1; score += POINTS + (streak > 1 ? STREAK_BONUS : 0); } else { streak = 0; }
            scoreOut.textContent = String(score);
            streakOut.textContent = String(streak);
            reveal.hidden = false;
            reveal.textContent = (hit ? '¡Acertaste! +' + (POINTS + (streak > 1 ? STREAK_BONUS : 0)) + '. ' : 'Era «' + pr.correctOption + '». ') + pr.reveal;
            if (pr.source) reveal.appendChild(el('span', { 'class': 'source' }, ' Fuente: ' + pr.source));
            row.className = 'row prediction ' + (hit ? 'row--ok' : 'row--bad');
            answered += 1;
            if (answered === total) finish();
          });
        });
        return function () { return hit; };
      });
    },
    caso_aplicado: function (s, box) {
      // HU-050: el estudiante escribe su solución y la revisa con los criterios de logro; la califica el docente.
      var card = el('section', { 'class': 'case' });
      card.appendChild(el('p', {}, s.scenario));
      var task = el('p', {});
      task.appendChild(el('strong', {}, 'Consigna: '));
      task.appendChild(document.createTextNode(s.task));
      card.appendChild(task);
      card.appendChild(el('label', { 'for': 'case-solution' }, 'Tu solución'));
      var solution = el('textarea', { id: 'case-solution', rows: '8' });
      card.appendChild(solution);
      var note = el('span', { 'class': 'note' });
      card.appendChild(note);
      box.parentNode.insertBefore(card, box);
      box.appendChild(el('p', {}, 'Criterios de logro: marca los que cumple tu solución.'));
      function written() { return solution.value.trim().split(/\s+/).length >= 15; }
      return s.criteria.map(function (c, i) {
        var row = el('div', { 'class': 'row criterion' });
        var id = 'c' + i;
        var label = el('label', { 'for': id });
        var check = el('input', { type: 'checkbox', id: id });
        label.appendChild(check);
        label.appendChild(el('span', {}, c.criterion));
        row.appendChild(label);
        if (c.source) row.appendChild(el('span', { 'class': 'source' }, 'Fuente: ' + c.source));
        box.appendChild(row);
        return function () {
          var ok = written() && check.checked;
          note.textContent = written() ? '' : 'Escribe tu solución antes de revisarla con los criterios.';
          row.className = 'row criterion ' + (ok ? 'row--ok' : 'row--bad');
          return ok;
        };
      });
    },
    ordenar_pasos: function (s, box) {
      var list = el('ol', { 'class': 'activity__order' });
      shuffle(s.sequence).forEach(function (step) {
        var li = el('li', { 'class': 'row order' });
        li.appendChild(el('span', {}, step));
        var up = el('button', { type: 'button', 'aria-label': 'Subir' }, '↑');
        var down = el('button', { type: 'button', 'aria-label': 'Bajar' }, '↓');
        up.addEventListener('click', function () { if (li.previousSibling) list.insertBefore(li, li.previousSibling); });
        down.addEventListener('click', function () { if (li.nextSibling) list.insertBefore(li.nextSibling, li); });
        li.appendChild(up); li.appendChild(down);
        list.appendChild(li);
      });
      box.appendChild(list);
      return [function () {
        var items = list.querySelectorAll('li');
        var ok = true;
        for (var i = 0; i < items.length; i++) {
          var right = items[i].querySelector('span').textContent === s.sequence[i];
          items[i].className = 'row order ' + (right ? 'row--ok' : 'row--bad');
          ok = ok && right;
        }
        return ok;
      }];
    }
  };

  window.addEventListener('load', function () {
    var form = document.getElementById('activity');
    var data = document.getElementById('activity-data');
    if (!form || !data) return;
    var activity = JSON.parse(data.textContent);
    var build = builders[activity.type];
    if (!build) return;
    var checks = build(activity.structure, form.querySelector('.activity__items'), activity);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var right = checks.filter(function (check) { return check(); }).length;
      var percent = checks.length ? (100 * right) / checks.length : 0;
      var out = form.querySelector('.feedback');
      var selfAssessed = activity.type === 'caso_aplicado';
      if (activity.type === 'actividad_kinestesica') {
        // T059 (REV-01): se completa cuando todos los pasos están marcados; mientras tanto queda «incompleta».
        out.textContent = right + ' de ' + checks.length + ' pasos hechos.';
        out.className = 'feedback ' + (right === checks.length ? 'is-correct' : 'is-wrong');
        if (right === checks.length && window.scorm5e && window.scorm5e.complete) window.scorm5e.complete(100);
        return;
      }
      out.textContent = activity.type === 'exploracion_guiada'
        ? right + ' de ' + checks.length + ' pasos registrados.'
        : selfAssessed
          ? right + ' de ' + checks.length + ' criterios de logro según tu revisión. Tu docente valorará la solución.'
          : right + ' de ' + checks.length + ' correctas (' + Math.round(percent) + ' %).';
      out.className = 'feedback ' + (percent >= 60 ? 'is-correct' : 'is-wrong');
      // HU-050: el caso aplicado se registra como completado; no se aprueba ni se desaprueba con la autoevaluación.
      if (selfAssessed && window.scorm5e && window.scorm5e.complete) window.scorm5e.complete(percent);
      else if (window.scorm5e) window.scorm5e.report(percent);
    });
  });
})();
"""


QUIZ_JS = r"""/* Evaluación por niveles (HU-051): puntaje, niveles que se desbloquean, cronómetro e insignia. */
(function () {
  'use strict';
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(seconds) { return pad(Math.floor(seconds / 60)) + ':' + pad(seconds % 60); }

  window.addEventListener('load', function () {
    var data = document.getElementById('quiz-data');
    if (!data) return;
    var config = JSON.parse(data.textContent);
    var levels = Array.prototype.slice.call(document.querySelectorAll('.level'));
    var scoreOut = document.getElementById('quiz-score');
    var levelOut = document.getElementById('quiz-level');
    var clockOut = document.getElementById('quiz-clock');
    var status = document.getElementById('quiz-status');
    var result = document.getElementById('quiz-result');
    var started = Date.now();
    var score = 0;
    function elapsed() { return Math.round((Date.now() - started) / 1000); }
    var timer = setInterval(function () { clockOut.textContent = clock(elapsed()); }, 1000);

    function unlock(level) {
      level.classList.remove('level--locked');
      var lock = level.querySelector('.level__lock');
      if (lock) lock.hidden = true;
      var controls = level.querySelectorAll('input, button');
      for (var i = 0; i < controls.length; i++) controls[i].disabled = false;
    }

    function badgeFor(percent) {
      for (var i = 0; i < config.badges.length; i++) if (percent >= config.badges[i][0]) return config.badges[i][1];
      return null;
    }

    function finish() {
      clearInterval(timer);
      var seconds = elapsed();
      clockOut.textContent = clock(seconds);
      var percent = config.total ? (100 * score) / config.total : 0;
      var badge = badgeFor(percent);
      var badgeOut = result.querySelector('.result__badge');
      badgeOut.textContent = badge ? 'Insignia de ' + badge.toLowerCase() : 'Sin insignia esta vez: ¡inténtalo de nuevo!';
      badgeOut.className = 'result__badge badge--' + (badge ? badge.toLowerCase() : 'none');
      result.querySelector('.result__summary').textContent = score + ' de ' + config.total + ' puntos (' +
        Math.round(percent) + ' %) en un tiempo de ' + clock(seconds) + '. ' +
        (percent >= config.passing ? 'Aprobaste la evaluación.' : 'Necesitas ' + config.passing + ' % para aprobar.');
      result.hidden = false;
      status.textContent = '¡Terminaste la evaluación!';
      if (window.scorm5e) { window.scorm5e.time(seconds); window.scorm5e.report(percent); }
    }

    function grade(event) {
      event.preventDefault();
      var form = event.currentTarget;
      var chosen = form.querySelector('input[type="radio"]:checked');
      var out = form.querySelector('.feedback');
      if (!chosen) { out.textContent = 'Elige una alternativa.'; return; }
      var correct = chosen.getAttribute('data-correct') === 'true';
      var points = Number(form.getAttribute('data-points')) || 0;
      // La retroalimentación puede empezar con «Correcto.» o «Incorrecto.»: se quita para no repetirlo.
      var note = (chosen.getAttribute('data-feedback') || '').replace(/^\s*(in)?correcto[.:,]?\s*/i, '');
      if (correct) score += points;
      out.textContent = (correct ? 'Correcto, +' + points + ' puntos. ' : 'Incorrecto, 0 puntos. ') + note;
      out.className = 'feedback ' + (correct ? 'is-correct' : 'is-wrong');
      var controls = form.querySelectorAll('input, button');
      for (var i = 0; i < controls.length; i++) controls[i].disabled = true;
      form.classList.add('is-answered');
      scoreOut.textContent = score;

      var level = form.closest('.level');
      if (level.querySelectorAll('.quiz-item:not(.is-answered)').length) return;
      var next = levels[levels.indexOf(level) + 1];
      if (next) {
        unlock(next);
        levelOut.textContent = levels.indexOf(next) + 1;
        status.textContent = '¡' + next.querySelector('h2').firstChild.textContent.trim() + ' desbloqueado!';
      } else {
        finish();
      }
    }

    var forms = document.querySelectorAll('.quiz-item');
    for (var i = 0; i < forms.length; i++) forms[i].addEventListener('submit', grade);
    document.getElementById('quiz-retry').addEventListener('click', function () { window.location.reload(); });
  });
})();
"""


class ScormPackageExporter(UnitExporterPort):
    """Implementa ResourceExporterPort para el formato SCORM 1.2 (.zip)."""

    format = "scorm_zip"
    media_type = "application/zip"

    def supports(self, resource: Mapping) -> bool:
        return True  # cada recurso aprobado es una página de la lección

    def export(self, resources: Sequence[Mapping], course: Mapping, unit: Mapping) -> ExportedFile:
        ordered = sorted(
            resources,
            key=lambda r: (STAGE_ORDER.index(r["stage"]) if r.get("stage") in STAGE_ORDER else 99, r.get("createdAt", "")),
        )
        entries = _with_leveled_quiz(ordered)
        number = unit.get("number", "")
        title = f"{course.get('code', '')} · Unidad {number}: {unit.get('title', '')}".strip()
        pages = [
            (f"sco/{n:02d}.html", QUIZ_TITLE if isinstance(e, LeveledQuiz) else e.get("title") or f"Recurso {n}")
            for n, e in enumerate(entries, start=1)
        ]
        files = [[] if isinstance(e, LeveledQuiz) else media_files(e, n) for n, e in enumerate(entries, start=1)]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
            def add(name: str, content: str | bytes) -> None:
                data = content.encode("utf-8") if isinstance(content, str) else content
                package.writestr(zipfile.ZipInfo(name, FIXED_DATE), data, zipfile.ZIP_DEFLATED)

            package_id = f"PKG_{_slug(course.get('code', ''))}_U{number}".replace("-", "_")
            add("imsmanifest.xml", _manifest(package_id, title, pages, [[name for name, _ in f] for f in files]))
            add("shared/scorm.js", SCORM_JS)
            add("shared/style.css", STYLE_CSS)
            add("shared/activity.js", ACTIVITY_JS)
            add("shared/quiz.js", QUIZ_JS)
            for (href, _), entry, resource_files in zip(pages, entries, files):
                add(href, _quiz_page(entry) if isinstance(entry, LeveledQuiz) else _sco_page(entry, resource_files))
                for name, content in resource_files:
                    add(name, content)
        file_name = f"{_slug(course.get('code', ''))}-unidad-{number}-scorm.zip"
        return ExportedFile(file_name, self.media_type, buffer.getvalue())


def _with_leveled_quiz(ordered: list[Mapping]) -> list[Mapping | LeveledQuiz]:
    """Junta los ítems de opción múltiple en una sola evaluación por niveles, donde iba el primero de ellos."""
    items = tuple(r for r in ordered if is_quiz_item(r))
    entries: list[Mapping | LeveledQuiz] = []
    for resource in ordered:
        if not is_quiz_item(resource):
            entries.append(resource)
        elif resource is items[0]:
            entries.append(LeveledQuiz(items))
    return entries
