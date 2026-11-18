"""Write the API's OpenAPI schema to ``docs/openapi.json``.

    uv run python -m waffle_pos.openapi           # regenerate after changing an endpoint
    uv run python -m waffle_pos.openapi --check   # exit 1 if docs/openapi.json is out of date (CI)

The app is built against a throwaway data folder and never started, so no database is touched.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from waffle_pos.app import create_app
from waffle_pos.config import PROJECT_ROOT, AppConfig

OPENAPI_PATH = PROJECT_ROOT / "docs" / "openapi.json"


def render() -> str:
    """The OpenAPI schema as stable, diff-friendly JSON text."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(AppConfig(data_dir=Path(tmp), start_sync_loop=False))
        schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m waffle_pos.openapi", description="Write docs/openapi.json."
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the file is stale instead of writing it"
    )
    parser.add_argument("--output", type=Path, default=OPENAPI_PATH, help="default: %(default)s")
    args = parser.parse_args(argv)

    text = render()
    out: Path = args.output
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"{out} is out of date. Run: uv run python -m waffle_pos.openapi", file=sys.stderr)
            return 1
        print(f"{out} is up to date.")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
