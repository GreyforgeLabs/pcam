import json
from pathlib import Path

from pcam_runtime.vectors import run_vector

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/event-delivery-runtime.json").read_text(encoding="utf-8")
    )


def _event_ids(values):
    return [value["event_id"] for value in values]


def test_python_complete_tick_routes_and_clears_every_core_event_mode():
    vector = _vector()
    first_tick = json.loads(json.dumps(vector))
    first_tick["ticks"] = first_tick["ticks"][:1]
    before = run_vector(first_tick)

    delivered, delivered_ids = before.executor._deliver_events(before.final_state)
    routes = {
        "action_1": _event_ids(delivered.action_instances["1"].event_inbox),
        "entity_1": _event_ids(delivered.entity_records["1"]["event_inbox"]),
        "entity_2": _event_ids(delivered.entity_records["2"]["event_inbox"]),
    }
    assert delivered_ids == vector["expected"]["delivered_ids"]
    assert routes == vector["expected"]["delivery_routes"]

    run = run_vector(vector)
    action = run.final_state.action_instances["1"]
    assert [trace["state_digest"] for trace in run.traces] == vector["expected"]["tick_state_digests"]
    assert run.traces[1]["events_delivered"] == vector["expected"]["delivered_ids"]
    assert action.current_node_id == vector["expected"]["final_node"]
    assert action.transition_serial == vector["expected"]["final_transition_serial"]
    assert action.event_inbox == ()
    assert all(record["event_inbox"] == [] for record in run.final_state.entity_records.values())
    assert run.final_state.pending_events == ()
