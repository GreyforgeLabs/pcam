import json
from pathlib import Path

import pytest

from pcam_runtime import EventEnvelope, deliver_due, event_snapshot
from pcam_runtime.errors import PCAMError

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/events.json").read_text(encoding="utf-8"))


def _events(values):
    return tuple(EventEnvelope(**value) for value in values)


def test_python_event_delivery_matches_shared_order_freeze_and_continuation():
    for case in _vectors()["cases"]:
        delivered, pending = deliver_due(
            _events(case["events"]),
            case["tick"],
            frozenset(case["frozen_target_action_ids"]),
        )
        assert [event.event_id for event in delivered] == case["delivered_ids"], case["id"]
        assert [event_snapshot(event) for event in pending] == case["pending"], case["id"]
        if "continuation_tick" in case:
            continued, remaining = deliver_due(pending, case["continuation_tick"])
            assert [event.event_id for event in continued] == case["continuation_delivered_ids"]
            assert remaining == ()


def test_python_event_delivery_matches_shared_faults():
    for case in _vectors()["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            deliver_due(_events(case["events"]), case["tick"])
        assert raised.value.fault.value == case["fault"], case["id"]
