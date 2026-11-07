import os
from pathlib import Path

# Dev default for the Tesseract binary, taken from .env.example (no secrets there).
for line in (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8").splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() == "TESSERACT_CMD":
        os.environ.setdefault("TESSERACT_CMD", value.strip())
