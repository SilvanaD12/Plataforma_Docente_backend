"""CC-C9: una descarga registrada debe sobrevivir al borrado del curso."""

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_generation_repository as generations,
    sqlalchemy_resource_repository as resources,
)


def test_deleting_course_preserves_its_download_record(tmp_path, monkeypatch, request):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "t008.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    generation_repository = generations.SQLAlchemyGenerationRepository()
    account_repository = accounts.SQLAlchemyAccountRepository(generation_repository)
    service = AccountService(account_repository, "", "")
    downloads = resources.SQLAlchemyResourceRepository()
    teacher_id = "docente@example.com"
    course = service.save_course(
        teacher_id,
        {
            "code": "RED-301",
            "name": "Redes",
            "term": "2026-II",
            "units": [{"title": "Protocolos de transporte"}],
        },
    )
    unit_id = course["units"][0]["id"]
    download = {
        "id": "descarga-t008",
        "unitId": unit_id,
        "format": "moodle_xml",
        "fileName": "redes.xml",
        "resourceCount": 1,
        "createdAt": "2026-11-08T12:00:00Z",
    }
    downloads.save_download(teacher_id, unit_id, download)
    assert service.list_courses(teacher_id) == [course]
    assert downloads.get_downloads(teacher_id, unit_id) == [download]

    service.delete_course(teacher_id, course["id"])

    assert service.list_courses(teacher_id) == []
    with sessions() as session:
        stored_download = session.get(accounts.DownloadORM, download["id"])
        assert stored_download is not None, "El registro de descarga desapareció al borrar el curso."
        assert stored_download.teacher_id == teacher_id
