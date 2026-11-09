"""REV-01 · ¿El archivo multimedia se generó con un texto que cambió? (REV-R8 · REV-C8).

Solo invalida el archivo el campo con que se generó: el `prompt` de una imagen o el `script` de un audio, normalizados.
Cambiar el texto alternativo o el pie de una imagen no lo invalida.
"""

from __future__ import annotations

import pytest

from platform5e.domain.review.media_change import media_source_changed

IMAGE = {
    "prompt": "Ilustración didáctica de la comunicación de extremo a extremo entre procesos.",
    "alt": "Ilustración sobre capa de transporte",
    "caption": "La capa de transporte comunica procesos de distintos equipos.",
}
SCRIPT = (
    "Escucha esta idea del material: el protocolo TCP confirma la entrega de los datos y retransmite lo que se pierde."
)


@pytest.mark.parametrize(
    ("new", "changed"),
    [
        pytest.param({**IMAGE, "prompt": "Ilustración de un datagrama UDP que viaja sin confirmación."}, True, id="prompt"),
        pytest.param({**IMAGE, "alt": "Dos computadoras conectadas"}, False, id="solo-alt"),
        pytest.param({**IMAGE, "caption": "UDP no garantiza la entrega."}, False, id="solo-caption"),
        pytest.param({**IMAGE, "alt": "Otra", "caption": "Otro pie"}, False, id="alt-y-caption"),
        pytest.param({**IMAGE, "prompt": "  " + IMAGE["prompt"].replace(" ", "   ") + "  "}, False, id="prompt-solo-espacios"),
        pytest.param(dict(IMAGE), False, id="sin-cambios"),
    ],
)
def test_an_image_file_is_invalidated_only_by_its_prompt(new, changed):
    assert media_source_changed("imagen_ilustrativa", IMAGE, new) is changed


@pytest.mark.parametrize(
    ("new_script", "changed"),
    [
        pytest.param("Guion editado: el protocolo UDP no confirma la entrega y por eso es más rápido en videollamadas.",
                     True, id="guion"),
        pytest.param("  " + SCRIPT.replace(" ", "  ") + " ", False, id="guion-solo-espacios"),
        pytest.param(SCRIPT, False, id="sin-cambios"),
    ],
)
def test_an_audio_file_is_invalidated_only_by_its_script(new_script, changed):
    assert media_source_changed("podcast_resumen", {"script": SCRIPT}, {"script": new_script}) is changed


def test_resources_without_a_generated_file_never_report_a_change():
    assert media_source_changed("mapa_conceptual", {"central": "TCP", "nodes": []}, {"central": "UDP", "nodes": []}) is False
    assert media_source_changed("explicacion", None, None) is False
