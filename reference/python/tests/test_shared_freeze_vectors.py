import json
from pathlib import Path

import pytest

from pcam_runtime import FreezeToken, add_token
from pcam_runtime.errors import PCAMError

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/freeze-stacking.json").read_text())


def _token(value):
    return FreezeToken(
        token_id=value["token_id"],
        source_id=value["source_id"],
        target_id=value["target_id"],
        activation_tick=value["activation_tick"],
        remaining_ticks=value["remaining_ticks"],
        domains=tuple(value["domains"]),
        accrual_policy=value["accrual_policy"],
        stack_group=value["stack_group"],
        stack_policy=value["stack_policy"],
        metadata=value["metadata"],
    )


def _projection(token):
    return {
        "token_id": token.token_id,
        "source_id": token.source_id,
        "target_id": token.target_id,
        "activation_tick": token.activation_tick,
        "remaining_ticks": token.remaining_ticks,
        "domains": list(token.domains),
        "accrual_policy": token.accrual_policy,
        "stack_group": token.stack_group,
        "stack_policy": token.stack_policy,
        "metadata": token.metadata,
    }


def test_python_freeze_stacking_matches_shared_vectors():
    for case in _vectors()["cases"]:
        tokens = tuple(_token(value) for value in case["tokens"])
        incoming = _token(case["incoming"])
        if "fault" in case:
            with pytest.raises(PCAMError) as raised:
                add_token(tokens, incoming)
            assert raised.value.fault.value == case["fault"], case["id"]
        else:
            actual = [_projection(token) for token in add_token(tokens, incoming)]
            assert actual == case["expected"], case["id"]
