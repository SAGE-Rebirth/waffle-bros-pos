"""The committed OpenAPI schema (docs/openapi.json) must match the code, and every route is documented."""

import json
from pathlib import Path

import pytest

from waffle_pos import openapi

HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


def test_docs_openapi_json_is_up_to_date() -> None:
    assert openapi.OPENAPI_PATH.read_text(encoding="utf-8") == openapi.render(), (
        "docs/openapi.json is stale. Run: uv run python -m waffle_pos.openapi"
    )


def test_every_operation_has_a_summary_description_and_tag() -> None:
    schema = json.loads(openapi.render())
    tags = {t["name"] for t in schema["tags"]}
    ops = [(m, p, op) for p, item in schema["paths"].items() for m, op in item.items() if m in HTTP_METHODS]
    assert ops
    for method, path, op in ops:
        assert op.get("summary"), f"{method.upper()} {path} has no summary="
        assert op.get("description"), f"{method.upper()} {path} has no docstring"
        assert set(op.get("tags", [])) <= tags and op.get("tags"), f"{method.upper()} {path} tag"


def test_check_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "openapi.json"
    assert openapi.main(["--check", "--output", str(out)]) == 1  # missing
    assert openapi.main(["--output", str(out)]) == 0
    assert openapi.main(["--check", "--output", str(out)]) == 0
    out.write_text("{}\n", encoding="utf-8")
    assert openapi.main(["--check", "--output", str(out)]) == 1
    assert "out of date" in capsys.readouterr().err
