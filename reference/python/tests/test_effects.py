import pytest

from pcam_runtime import EffectEnvelope, reduce_effects
from pcam_runtime.errors import PCAMError


def _effect(effect_id: str, payload: object, reducer: str = "SUM", priority: int = 0) -> EffectEnvelope:
    return EffectEnvelope(
        effect_id=effect_id,
        effect_type="combat.damage",
        effect_class="DAMAGE",
        source_entity_id=1,
        target_entity_id=2,
        source_action_instance_id=3,
        origin_tick=4,
        priority=priority,
        payload=payload,
        reducer=reducer,  # type: ignore[arg-type]
    )


def test_sum_and_set_union_reducers_are_canonical():
    reduced, rejected = reduce_effects((_effect("b", 2), _effect("a", 3)))
    assert reduced[0].value == 5
    assert rejected == ()

    tags = (
        EffectEnvelope("b", "status.tags", "STATUS", 2, 1, 2, 0, 0, ["B", "A"], "SET_UNION"),
        EffectEnvelope("a", "status.tags", "STATUS", 1, 1, 1, 0, 0, ["C", "A"], "SET_UNION"),
    )
    reduced, _ = reduce_effects(tags)
    assert reduced[0].value == ("A", "B", "C")


def test_exclusive_reducer_keeps_highest_priority_and_traces_losers():
    reduced, rejected = reduce_effects(
        (_effect("low", "LOW", "EXCLUSIVE", priority=1), _effect("high", "HIGH", "EXCLUSIVE", priority=10))
    )
    assert reduced[0].value == "HIGH"
    assert rejected[0].effect_id == "low"


def test_mixed_or_unregistered_reducer_faults():
    with pytest.raises(PCAMError):
        reduce_effects((_effect("a", 1, "SUM"), _effect("b", 2, "MAX")))
    with pytest.raises(PCAMError):
        reduce_effects((_effect("a", 1, "CUSTOM_DETERMINISTIC"),))
