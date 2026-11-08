"""Evaluation harness. Puts src/ on the path so `python -m eval.run` works like pytest does (pythonpath = src)."""
import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
