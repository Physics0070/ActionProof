"""Write the console's OpenAPI document to web/openapi.json (the UI's types are generated from it; invariant 7).

    python scripts/gen_openapi.py           # (re)write web/openapi.json
    python scripts/gen_openapi.py --check   # exit 1 if web/openapi.json is stale

Needs no database, key or env: the app is built with placeholder wiring and only its schema is read.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from actionproof import console  # noqa: E402

OUT = ROOT / "web" / "openapi.json"


def generate() -> str:
    app = console.create_app(None, None, None, console.ConsoleSettings(web_origin="http://localhost:5173"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv) -> int:
    text = generate()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("web/openapi.json is stale: run python scripts/gen_openapi.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
