"""Container launcher for the review console: python scripts/serve_console.py

actionproof.console binds 127.0.0.1 (hard-coded), which a published container port cannot reach. This wrapper
changes ONLY the bind host (CONSOLE_BIND_HOST, default 0.0.0.0) and then runs console.main() unchanged.
# ponytail: monkeypatch of uvicorn.run, upgrade path is a CONSOLE_BIND_HOST setting in console.py.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

_run, _host = uvicorn.run, os.environ.get("CONSOLE_BIND_HOST", "0.0.0.0")
uvicorn.run = lambda app, **kw: _run(app, **{**kw, "host": _host})

from actionproof import console  # noqa: E402

if __name__ == "__main__":
    sys.exit(console.main())
