"""HU-006: catálogo público por HTTP y contrato documentado en OpenAPI."""
import httpx


def test_catalog_is_public_and_documented(server):
    with httpx.Client(base_url=server, timeout=30) as api:
        response = api.get("/api/v1/resource-types")
        assert response.status_code == 200
        entries = response.json()
        assert len(entries) == 21
        assert entries[0]["id"] == "pregunta_detonante"
        assert entries[-1]["id"] == "completar_espacios"
        assert {entry["format"] for entry in entries} == {"text", "visual", "image", "audio", "interactive"}
        assert all("hasOptions" in entry and "has_options" not in entry for entry in entries)
        assert api.get("/api/v1/resource-types").json() == entries
        operation = api.get("/openapi.json").json()["paths"]["/api/v1/resource-types"]["get"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["type"] == "array"
        assert not operation.get("security")
