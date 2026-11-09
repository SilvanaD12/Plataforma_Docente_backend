"""Exportación por HTTP (SCORM y Moodle XML): solo recursos aprobados, archivo descargable y registro en el historial."""
import io
import json
import zipfile

import httpx

from tests.support.moodle_xml_validator import validate

MATERIAL = ('El protocolo TCP es orientado a la conexión y garantiza una entrega confiable. '
            'El protocolo UDP no confirma la entrega; por eso es más rápido e introduce menos retardo.').encode()


def test_exports_approved_resources_as_scorm_and_moodle_xml(server):
    with httpx.Client(base_url=server, timeout=60) as api:
        token = api.post('/api/v1/accounts', json={'name': 'Eva Ruiz', 'email': 'eva@correo.pe', 'password': 'clave-segura-1'}).json()['token']
        h = {'Authorization': f'Bearer {token}'}
        unit = api.post('/api/v1/courses', headers=h, json={'code': 'RED-301', 'name': 'Redes', 'term': '2026-II',
                          'units': [{'title': 'Transporte', 'outcomes': [{'text': 'Distingue TCP y UDP'}]}]}).json()['units'][0]
        context = {'unitId': unit['id'], 'outcomeIds': [unit['outcomes'][0]['id']],
                    'documentType': 'Separata o apuntes de clase', 'usePermission': True}
        document = api.post('/api/v1/documents', headers=h, files={'file': ('tcp.txt', MATERIAL)},
                             data={'context': json.dumps(context)}).json()
        api.post(f"/api/v1/documents/{document['id']}/process", headers=h)
        resource = api.post('/api/v1/generations', headers=h, json={
            'unitId': unit['id'], 'stage': 'evaluate', 'resourceType': 'item_opcion_multiple', 'quantity': 1,
            'optionCount': 4, 'modalities': ['Textual']}).json()['resources'][0]
        export_url = f"/api/v1/units/{unit['id']}/exports"

        assert api.post(export_url, json={'format': 'scorm_zip'}).status_code == 401
        assert api.post(export_url, headers=h, json={'format': 'scorm_zip'}).status_code == 422  # todavía no hay aprobados

        options = [{'id': o['id'], 'text': o['text'], 'feedback': o['feedback'],
                     'decision': 'pendiente' if o['isCorrect'] else 'aceptado'} for o in resource['options']]
        approved = api.put(f"/api/v1/units/{unit['id']}/resources/{resource['id']}", headers=h,
                           json={'title': resource['title'], 'body': resource['body'], 'status': 'aprobado', 'options': options,
                                 'expectedVersion': resource['version']})
        assert resource['approvalBlockers'] == ['Decide los 3 distractores pendientes para poder aprobar.']
        assert approved.status_code == 200
        assert approved.json()['approvalBlockers'] == []
        listed = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()
        assert listed[0]['approvalBlockers'] == []

        file_path = api.post(export_url, headers=h, json={'format': 'scorm_zip', 'resourceIds': [resource['id']]})
        assert file_path.status_code == 200 and file_path.headers['content-type'] == 'application/zip'
        assert 'red-301-unidad-1-scorm.zip' in file_path.headers['content-disposition']
        assert zipfile.ZipFile(io.BytesIO(file_path.content)).namelist()[0] == 'imsmanifest.xml'
        moodle = api.post(export_url, headers=h, json={'format': 'moodle_xml'})
        assert moodle.status_code == 200 and moodle.headers['content-type'].startswith('application/xml')
        assert 'red-301-unidad-1-moodle.xml' in moodle.headers['content-disposition']
        assert validate(moodle.content) == []
        html = api.post(export_url, headers=h, json={'format': 'documento', 'resourceIds': [resource['id']]})
        assert html.status_code == 200 and html.headers['content-type'].startswith('text/html')
        assert 'red-301-unidad-1-documento.html' in html.headers['content-disposition']
        assert '<h2>Para evaluar</h2>' in html.text and '1 recurso aprobado' in html.text
        assert resource['title'] in html.text
        assert api.post(export_url, json={'format': 'documento'}).status_code == 401
        assert api.post(export_url, headers=h, json={'format': 'documento', 'resourceIds': ['missing']}).status_code == 422
        history = api.get(f"/api/v1/units/{unit['id']}/downloads", headers=h).json()
        assert sorted(d['format'] for d in history) == ['documento', 'moodle_xml', 'scorm_zip']


def _approved_item(api: httpx.Client, email: str) -> tuple[dict, dict, dict]:
    """Cuenta, curso «Redes» con la unidad «Transporte» y un ítem aprobado, listo para exportar."""
    token = api.post('/api/v1/accounts', json={'name': 'Docente', 'email': email, 'password': 'clave-segura-1'}).json()['token']
    h = {'Authorization': f'Bearer {token}'}
    unit = api.post('/api/v1/courses', headers=h, json={'code': 'RED-301', 'name': 'Redes', 'term': '2026-II',
                      'units': [{'title': 'Transporte', 'outcomes': [{'text': 'Distingue TCP y UDP'}]}]}).json()['units'][0]
    context = {'unitId': unit['id'], 'outcomeIds': [unit['outcomes'][0]['id']],
               'documentType': 'Separata o apuntes de clase', 'usePermission': True}
    document = api.post('/api/v1/documents', headers=h, files={'file': ('tcp.txt', MATERIAL)},
                        data={'context': json.dumps(context)}).json()
    api.post(f"/api/v1/documents/{document['id']}/process", headers=h)
    resource = api.post('/api/v1/generations', headers=h, json={
        'unitId': unit['id'], 'stage': 'evaluate', 'resourceType': 'item_opcion_multiple', 'quantity': 1,
        'optionCount': 4, 'modalities': ['Textual']}).json()['resources'][0]
    options = [{'id': o['id'], 'text': o['text'], 'feedback': o['feedback'],
                'decision': 'pendiente' if o['isCorrect'] else 'aceptado'} for o in resource['options']]
    approved = api.put(f"/api/v1/units/{unit['id']}/resources/{resource['id']}", headers=h, json={
        'title': resource['title'], 'body': resource['body'], 'status': 'aprobado', 'options': options,
        'expectedVersion': resource['version']})
    assert approved.status_code == 200, approved.text
    return h, unit, approved.json()


def test_the_teacher_history_keeps_course_and_unit_and_is_isolated(server):
    """REV-C9 y REV-R9: historial por docente con curso y unidad; otra cuenta no lo ve (constitución IV)."""
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit, _ = _approved_item(api, 'historial@correo.pe')
        assert api.post(f"/api/v1/units/{unit['id']}/exports", headers=h, json={'format': 'scorm_zip'}).status_code == 200

        history = api.get('/api/v1/downloads', headers=h)
        assert history.status_code == 200
        [record] = history.json()
        assert {k: record[k] for k in ('format', 'fileName', 'courseName', 'unitName', 'unitNumber', 'unitId')} == {
            'format': 'scorm_zip', 'fileName': 'red-301-unidad-1-scorm.zip', 'courseName': 'Redes',
            'unitName': 'Transporte', 'unitNumber': 1, 'unitId': unit['id'],
        }
        assert record['createdAt'] and record['courseId']

        other_token = api.post('/api/v1/accounts', json={'name': 'Otra', 'email': 'otra-historial@correo.pe',
                                                         'password': 'clave-segura-1'}).json()['token']
        assert api.get('/api/v1/downloads', headers={'Authorization': f'Bearer {other_token}'}).json() == []
        assert api.get('/api/v1/downloads').status_code == 401


def test_the_history_survives_the_deletion_of_the_course(server):
    """REV-C9 y T036: al borrar el curso, el docente sigue viendo la descarga con la fecha, el formato, el archivo,
    el curso y la unidad. Se conserva solo el registro, no el archivo."""
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit, _ = _approved_item(api, 'borrado@correo.pe')
        assert api.post(f"/api/v1/units/{unit['id']}/exports", headers=h, json={'format': 'moodle_xml'}).status_code == 200
        [before] = api.get('/api/v1/downloads', headers=h).json()

        assert api.delete(f"/api/v1/courses/{unit['courseId']}", headers=h).status_code == 204
        assert api.get('/api/v1/courses', headers=h).json() == []
        assert api.get(f"/api/v1/units/{unit['id']}/downloads", headers=h).status_code == 404  # la unidad ya no existe

        [after] = api.get('/api/v1/downloads', headers=h).json()
        assert after == before
        assert {k: after[k] for k in ('format', 'fileName', 'courseName', 'unitName', 'unitNumber')} == {
            'format': 'moodle_xml', 'fileName': 'red-301-unidad-1-moodle.xml', 'courseName': 'Redes',
            'unitName': 'Transporte', 'unitNumber': 1,
        }
        assert after['createdAt'] and after['courseId'] == unit['courseId']
