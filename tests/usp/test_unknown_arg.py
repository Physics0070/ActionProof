"""USP G1: an argument the tool does not declare is a fail-closed DENY (invariant 1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "fixtures"))
import hero  # noqa: E402

from actionproof.verify import verify_request  # noqa: E402


def test_unknown_argument_denied():
    req = hero.hero_request()
    d = req.model_dump(mode="json")
    d["args"]["destination_account"] = {"value": "attacker", "claim": "ASSERTED", "taint": "doc"}
    from actionproof.contracts import parse_request

    r = verify_request(parse_request(d), hero.load_docs(), hero.hero_sor())
    assert not r.ok and any("unknown argument" in x.msg and x.guarantee == "G1" for x in r.reasons)


def test_hero_still_ok():
    assert verify_request(hero.hero_request(), hero.load_docs(), hero.hero_sor()).ok
