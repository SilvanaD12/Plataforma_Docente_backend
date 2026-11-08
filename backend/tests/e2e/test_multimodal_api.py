"""Por HTTP: recursos visuales, de audio e interactivos, su archivo, la edición con formato y el SCORM multirrecurso."""
import io
import json
import zipfile

import httpx

MATERIAL = (
    'El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los datos. '
    'El protocolo UDP no establece conexión ni confirma la entrega; por eso es más rápido. '
    'El protocolo IP se encarga del direccionamiento y del enrutamiento de los paquetes. '
    'El protocolo DNS traduce nombres de dominio en direcciones IP. '
    'La encapsulación es el proceso por el cual cada capa agrega su propio encabezado a los datos.'
).encode()


def setup(api: httpx.Client):
    token = api.post('/api/v1/accounts', json={'name': 'Eva Ruiz', 'email': 'eva@correo.pe', 'password': 'clave-segura-1'}).json()['token']
    h = {'Authorization': f'Bearer {token}'}
    unit = api.post('/api/v1/courses', headers=h, json={'code': 'RED-301', 'name': 'Redes', 'term': '2026-II',
                    'units': [{'title': 'Protocolos de transporte', 'outcomes': [{'text': 'Distingue TCP y UDP'}]}]}).json()['units'][0]
    context = {'unitId': unit['id'], 'outcomeIds': [unit['outcomes'][0]['id']],
               'documentType': 'Separata o apuntes de clase', 'usePermission': True}
    document = api.post('/api/v1/documents', headers=h, files={'file': ('tcp.txt', MATERIAL)},
                        data={'context': json.dumps(context)}).json()
    api.post(f"/api/v1/documents/{document['id']}/process", headers=h)
    return h, unit


def generate(api, h, unit, stage, resource_type):
    response = api.post('/api/v1/generations', headers=h, json={
        'unitId': unit['id'], 'stage': stage, 'resourceType': resource_type, 'quantity': 1})
    assert response.status_code == 200, response.text
    return response.json()['resources'][0]


def test_multimodal_resources_from_generation_to_scorm(server):
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit = setup(api)
        base = f"/api/v1/units/{unit['id']}/resources"
        concept_map = generate(api, h, unit, 'explain', 'mapa_conceptual')
        podcast = generate(api, h, unit, 'explain', 'podcast_resumen')
        illustration = generate(api, h, unit, 'explore', 'imagen_ilustrativa')
        matching = generate(api, h, unit, 'elaborate', 'emparejamiento')

        assert concept_map['format'] == 'visual' and len(concept_map['structure']['nodes']) >= 3
        graphic = api.get(f"{base}/{concept_map['id']}/media", headers=h)
        assert graphic.status_code == 200 and graphic.headers['content-type'].startswith('image/svg+xml')
        assert api.get(f"{base}/{concept_map['id']}/media").status_code == 401

        # Sin clave de Gemini: el audio queda con la voz del navegador y la imagen con su tarjeta descriptiva.
        assert podcast['media']['status'] == 'fallback' and podcast['structure']['script']
        assert api.get(f"{base}/{podcast['id']}/media", headers=h).json()['error']['code'] == 'NO_MEDIA'
        assert api.get(f"{base}/{illustration['id']}/media", headers=h).headers['content-type'].startswith('image/svg+xml')

        # Edición con formato: el HTML se limpia y los elementos de la actividad se validan.
        pairs = matching['structure']['pairs']
        edited = api.put(f"{base}/{matching['id']}", headers=h, json={
            'title': matching['title'], 'body': 'Relaciona cada término.', 'status': 'pendiente', 'edited': True,
            'bodyHtml': '<h2>Consigna</h2><p onclick="x()">Relaciona <strong>cada</strong> término.</p><script>alert(1)</script>',
            'structure': {'pairs': [{**pairs[0], 'term': 'TCP (editado)'}, *pairs[1:]]}})
        assert edited.status_code == 200, edited.text
        saved = edited.json()
        assert saved['bodyHtml'] == '<h2>Consigna</h2><p>Relaciona <strong>cada</strong> término.</p>'
        assert saved['structure']['pairs'][0]['term'] == 'TCP (editado)'
        too_few = api.put(f"{base}/{matching['id']}", headers=h, json={
            'title': matching['title'], 'body': 'x', 'status': 'pendiente', 'structure': {'pairs': pairs[:1]}})
        assert too_few.status_code == 422 and too_few.json()['error']['code'] == 'INVALID_STRUCTURE'

        for resource in (concept_map, podcast, illustration, saved):
            approved = api.put(f"{base}/{resource['id']}", headers=h, json={
                'title': resource['title'], 'body': resource['body'], 'status': 'aprobado'})
            assert approved.status_code == 200, approved.text
            assert approved.json().get('bodyHtml') == resource.get('bodyHtml')  # aprobar no borra el formato

        package = api.post(f"/api/v1/units/{unit['id']}/exports", headers=h, json={'format': 'scorm_zip'})
        archive = zipfile.ZipFile(io.BytesIO(package.content))
        names = archive.namelist()
        assert sum(name.endswith('.svg') for name in names) == 2 and 'shared/activity.js' in names
        pages = [archive.read(n).decode() for n in names if n.startswith('sco/')]
        assert len(pages) == 4 and any('<strong>cada</strong>' in p for p in pages)
        assert any('data-speak="script"' in p for p in pages)  # audio sin archivo: voz del navegador

        document = api.post(f"/api/v1/units/{unit['id']}/exports", headers=h, json={'format': 'documento'})
        assert document.status_code == 200 and '<svg' in document.text and 'Clave de respuestas' in document.text
