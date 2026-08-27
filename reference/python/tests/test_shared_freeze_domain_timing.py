import json
from pathlib import Path

from pcam_runtime import FreezeToken, expire_freeze_tokens, is_frozen

ROOT = Path(__file__).resolve().parents[3]


def test_python_all_core_freeze_domains_share_exact_timing_and_target_scope():
    vector = json.loads((ROOT / "tests/vectors/freeze-domain-timing.json").read_text())
    token = FreezeToken(**{**vector["token"], "domains": tuple(vector["token"]["domains"])})
    tokens = (token,)
    for expected in vector["expected"]:
        tick = expected["tick"]
        assert all(is_frozen(tokens, tick, 7, domain) == expected["target_frozen"] for domain in vector["domains"])
        assert all(is_frozen(tokens, tick, 8, domain) == expected["other_target_frozen"] for domain in vector["domains"])
        tokens = expire_freeze_tokens(tokens, tick)
        remaining = tokens[0].remaining_ticks if tokens else None
        assert remaining == expected["remaining_after_tick"]
