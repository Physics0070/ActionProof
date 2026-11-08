"""Read console logins from keys/demo-logins.txt inside code only; never print the password."""
import re
from pathlib import Path
def logins():
    out = {}
    for l in (Path(__file__).resolve().parents[2] / "keys/demo-logins.txt").read_text().splitlines():
        m = re.match(r"\s*([\w-]+)\s*[:=\s]\s*(\S+)", l)
        if m: out[m.group(1)] = m.group(2)
    return out
