"""Container HEALTHCHECK: GET /api/health on the console (200 only if the database answers)."""
import os
import sys
import urllib.request

try:
    url = f"http://127.0.0.1:{os.environ.get('CONSOLE_PORT', '8766')}/api/health"
    sys.exit(0 if urllib.request.urlopen(url, timeout=3).status == 200 else 1)
except Exception:
    sys.exit(1)
