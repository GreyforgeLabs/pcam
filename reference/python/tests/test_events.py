import pytest

from pcam_runtime import EventEnvelope, canonical_events, deliver_due, event_from_snapshot, event_snapshot
from pcam_runtime.errors import PCAMError


def _event(event_id: str, target: int = 2) -> EventEnvelope:
    return EventEnvelope.next_tick(event_id, "CHILD_RESULT", 1, target, 4, {"result": "OK"}, "PARENT")


def test_events_deliver_only_on_declared_tick_in_canonical_order():
    later_id = _event("z")
    earlier_id = _event("a")
    delivered, pending = deliver_due((later_id, earlier_id), tick=5)
    assert [item.event_id for item in delivered] == ["a", "z"]
    assert pending == ()
    with pytest.raises(PCAMError):
        deliver_due((_event("late"),), tick=6)


def test_event_delivery_freeze_defers_explicitly_one_tick():
    event = _event("frozen")
    delivered, pending = deliver_due((event,), tick=5, frozen_target_action_ids=frozenset({2}))
    assert delivered == ()
    assert pending[0].delivery_tick == 6
    delivered, pending = deliver_due(pending, tick=6)
    assert delivered[0].event_id == "frozen"
    assert pending == ()


def test_event_snapshot_round_trip_and_duplicate_rejection():
    event = _event("one")
    assert event_from_snapshot(event_snapshot(event)) == event
    with pytest.raises(PCAMError):
        canonical_events((event, event))
