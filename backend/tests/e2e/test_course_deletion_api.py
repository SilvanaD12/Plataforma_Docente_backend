"""CC-C9: borrar un curso limpia su multimedia y conserva su registro de descarga."""

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    DownloadORM,
    TeacherResourceORM,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_media_repository import MediaAssetORM


def test_deleting_course_removes_its_media_and_retains_its_download(server, e2e_database_url, request):
    engine = create_engine(e2e_database_url)
    request.addfinalizer(engine.dispose)
    teacher_id = "docente.t008@example.com"

    with httpx.Client(base_url=server) as api:
        registration = api.post("/api/v1/accounts", json={
            "name": "Docente de prueba",
            "email": teacher_id,
            "password": "clave-segura-1",
        })
        assert registration.status_code == 201, registration.text
        api.headers["Authorization"] = "Bearer " + registration.json()["token"]
        courses = {}
        for code, name in (("RED-301", "Redes"), ("PRO-301", "Programación")):
            response = api.post("/api/v1/courses", json={
                "code": code,
                "name": name,
                "term": "2026-II",
                "units": [{"title": "Introducción"}],
            })
            assert response.status_code == 201, response.text
            courses[code] = response.json()

        course = courses["RED-301"]
        other_course = courses["PRO-301"]
        unit_id = course["units"][0]["id"]
        other_unit_id = other_course["units"][0]["id"]
        created_at = "2026-11-08T12:00:00Z"
        with Session(engine) as session, session.begin():
            session.add_all([
                TeacherResourceORM(id="recurso-redes", teacher_id=teacher_id, unit_id=unit_id,
                                   created_at=created_at, resource_data={"id": "recurso-redes"}),
                TeacherResourceORM(id="recurso-programacion", teacher_id=teacher_id, unit_id=other_unit_id,
                                   created_at=created_at, resource_data={"id": "recurso-programacion"}),
                MediaAssetORM(id="imagen-redes", teacher_id=teacher_id, resource_id="recurso-redes",
                              details={"kind": "image"}, content=b"imagen de prueba"),
                MediaAssetORM(id="audio-redes", teacher_id=teacher_id, resource_id="recurso-redes",
                              details={"kind": "audio"}, content=b"audio de prueba"),
                MediaAssetORM(id="imagen-programacion", teacher_id=teacher_id, resource_id="recurso-programacion",
                              details={"kind": "image"}, content=b"imagen de otro curso"),
                DownloadORM(id="descarga-redes", teacher_id=teacher_id, unit_id=unit_id,
                            created_at=created_at, download_data={"id": "descarga-redes", "fileName": "redes.xml"}),
            ])

        deleted = api.delete(f"/api/v1/courses/{course['id']}")
        assert deleted.status_code == 204, deleted.text
        remaining = api.get("/api/v1/courses")
        assert remaining.status_code == 200, remaining.text
        assert [item["id"] for item in remaining.json()] == [other_course["id"]]

    with Session(engine) as session:
        assert session.get(TeacherResourceORM, "recurso-redes") is None
        assert session.get(MediaAssetORM, "imagen-redes") is None, "La imagen quedó guardada después del borrado."
        assert session.get(MediaAssetORM, "audio-redes") is None, "El audio quedó guardado después del borrado."
        assert session.get(MediaAssetORM, "imagen-programacion") is not None
        retained = session.get(DownloadORM, "descarga-redes")
        assert retained is not None
        assert retained.teacher_id == teacher_id
        assert retained.unit_id == unit_id
