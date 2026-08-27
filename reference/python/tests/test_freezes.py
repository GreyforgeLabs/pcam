import pytest

from pcam_runtime import FreezeToken, add_token, expire_freeze_tokens, is_frozen, progression_accrual
from pcam_runtime.errors import PCAMError


def _token(token_id: int, creation_tick: int = 4, duration: int = 2, **kwargs) -> FreezeToken:
    return FreezeToken.created(
        token_id=token_id,
        source_id=10,
        target_id=20,
        creation_tick=creation_tick,
        duration=duration,
        domains=("PROGRESSION",),
        **kwargs,
    )


def test_freeze_activates_next_tick_for_exact_duration():
    token = _token(1)
    assert not is_frozen((token,), tick=4, target_id=20, domain="PROGRESSION")
    assert is_frozen((token,), tick=5, target_id=20, domain="PROGRESSION")
    after_first = expire_freeze_tokens((token,), tick=5)
    assert is_frozen(after_first, tick=6, target_id=20, domain="PROGRESSION")
    assert expire_freeze_tokens(after_first, tick=6) == ()


def test_hold_dominates_accrue_for_overlapping_progression_freezes():
    hold = _token(1, accrual_policy="HOLD")
    accrue = _token(2, accrual_policy="ACCRUE", stack_group="other")
    assert progression_accrual((accrue,), tick=5, target_id=20) == "ACCRUE"
    assert progression_accrual((accrue, hold), tick=5, target_id=20) == "HOLD"


def test_sum_duration_queues_compatible_group_and_replace_removes_old():
    first = _token(1, stack_policy="SUM_DURATION", duration=2)
    second = _token(2, stack_policy="SUM_DURATION", duration=3)
    tokens = add_token(add_token((), first), second)
    assert tokens[1].activation_tick == first.expiration_tick

    replacement = _token(3, stack_policy="REPLACE")
    replaced = add_token(tokens, replacement)
    assert replaced == (replacement,)


def test_incompatible_sum_group_faults():
    first = _token(1, stack_policy="SUM_DURATION")
    second = FreezeToken.created(
        token_id=2,
        source_id=10,
        target_id=20,
        creation_tick=4,
        duration=2,
        domains=("BUFFER_EXPIRY",),
        stack_policy="SUM_DURATION",
    )
    with pytest.raises(PCAMError):
        add_token((first,), second)
