"""DO-009: every published operation has usable documentation in Swagger and the snapshot."""
from pathlib import Path
import json

from platform5e.main import create_application

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def operations(schema):
    return {
        (method, path): operation
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def test_published_operations_have_descriptions_and_call_examples():
    published = operations(create_application().openapi())
    assert published
    for (method, path), operation in published.items():
        description = operation.get("description", "")
        label = f"{method.upper()} {path}"
        assert description.split("Example (Bash/cURL).")[0].strip(), label
        assert "```bash\ncurl " in description, label
        assert "$BASE_URL" in description, label
        assert f"-X {method.upper()} " in description, label


def test_versioned_operation_documentation_matches_swagger():
    repository = Path(__file__).resolve().parents[3]
    versioned = operations(json.loads((repository / "docs/api/openapi.json").read_text(encoding="utf-8")))
    published = operations(create_application().openapi())
    assert versioned.keys() == published.keys()
    for key in published:
        assert versioned[key].get("description") == published[key].get("description"), key
