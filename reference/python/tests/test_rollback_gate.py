from dataclasses import replace
import json
from pathlib import Path

import pytest

from pcam_runtime import (
    ActionDefinition,
    Contact,
    Effect,
    EffectTemplate,
    FactBinding,
    FreezeToken,
    HitPolicy,
    HostSnapshot,
    InteractionRule,
    NodeDefinition,
    PCG32Stream,
    PredicateDefinition,
    RetainedRollbackHistory,
    RuleOperation,
    SemanticFact,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)
from pcam_runtime.errors import PCAMError

ROOT = Path(__file__).resolve().parents[3]


def _run(executor, state, history, until_tick):
    traces = []
    while state.tick < until_tick:
        inputs, host = history.get(state.tick, ((), HostSnapshot()))
        state, trace = executor.tick(state, inputs, host)
        traces.append(trace)
    return state, traces


def test_late_mispredicted_action_start_and_multitick_rewind_match_direct_execution():
    idle = ActionDefinition("IDLE", 1, 0, (NodeDefinition("RUN"),))
    attack = ActionDefinition("ATTACK", 1, 1, (NodeDefinition("RUN"),))
    executor = TickExecutor((idle, attack))
    manager = RetainedRollbackHistory(executor, retained_history_ticks=8)
    state = executor.initial_state()
    predicted = TickInput("predicted", 1, 0, "START", 1, action_definition_id="IDLE")
    corrected = TickInput("authoritative", 1, 0, "START", 1, action_definition_id="ATTACK")
    for tick in range(6):
        inputs = (predicted,) if tick == 1 else ()
        state, _, _ = manager.advance(state, inputs)

    baseline = executor.restore(manager.frames[1].snapshot)
    direct, _ = _run(executor, baseline, {1: ((corrected,), HostSnapshot())}, 6)
    result = manager.correct_and_resimulate(1, (corrected,))

    assert result.rewind_ticks == 5
    assert result.state.to_snapshot() == direct.to_snapshot()
    assert result.state.action_instances["1"].definition_hash == attack.definition_hash
    assert result.traces[-1]["state_digest"] == direct.state_hash()


def test_hit_stop_state_survives_rewind_and_expires_on_the_same_tick():
    definition = ActionDefinition("HITSTOP", 1, 1, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,))
    state = executor.initial_state()
    start = TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id)
    state, _ = executor.tick(state, (start,))
    token = FreezeToken.created(1, 99, 1, creation_tick=0, duration=2, domains=("PROGRESSION",))
    state = replace(state, freeze_tokens=(token,), next_freeze_token_id=2)
    manager = RetainedRollbackHistory(executor, retained_history_ticks=8)
    for _ in range(4):
        state, _, _ = manager.advance(state)
    direct = state

    result = manager.correct_and_resimulate(1, ())
    assert result.state.to_snapshot() == direct.to_snapshot()
    assert result.state.freeze_tokens == ()
    assert result.traces[0]["progression_quanta"]["1"] == 0
    assert result.traces[1]["progression_quanta"]["1"] == 0
    assert result.state.action_instances["1"].local_step == 3


def test_child_action_started_inside_rewind_preserves_identity_and_relationship():
    child = ActionDefinition("CHILD", 1, 0, (NodeDefinition("RUN"),))
    parent = ActionDefinition(
        "PARENT",
        1,
        0,
        (NodeDefinition("RUN"),),
        transitions=(
            TransitionDefinition(
                "launch",
                "RUN",
                "PRE_ADVANCE",
                10,
                target_kind="CHILD_ACTION",
                target_action="CHILD",
                child_slot_id="SUB",
                parent_policy="FREEZE_PROGRESSION",
                input_command="LAUNCH",
            ),
        ),
        child_slot_capacities={"SUB": 1},
        child_termination_policies={"SUB": "TERMINATE_CHILD"},
    )
    executor = TickExecutor((parent, child))
    manager = RetainedRollbackHistory(executor, retained_history_ticks=8)
    state = executor.initial_state()
    state, _, _ = manager.advance(
        state,
        (TickInput("parent", 1, 0, "START", 0, action_definition_id="PARENT"),),
    )
    for _ in range(3):
        state, _, _ = manager.advance(state)
    launch = TickInput("launch", 1, 1, "LAUNCH", 1)

    baseline = executor.restore(manager.frames[1].snapshot)
    direct, _ = _run(executor, baseline, {1: ((launch,), HostSnapshot())}, 4)
    result = manager.correct_and_resimulate(1, (launch,))

    assert result.state.to_snapshot() == direct.to_snapshot()
    parent_state = result.state.action_instances["1"]
    child_state = result.state.action_instances["2"]
    assert parent_state.child_instance_ids == (2,)
    assert child_state.parent_instance_id == 1
    assert child_state.parent_slot_id == "SUB"


def test_rng_draw_effect_during_rewind_reproduces_stream_state_and_value():
    definition = ActionDefinition(
        "RANDOM",
        1,
        0,
        (NodeDefinition("RUN"),),
        transitions=(
            TransitionDefinition(
                "draw",
                "RUN",
                "PRE_ADVANCE",
                10,
                target_node="RUN",
                input_command="DRAW",
                effects=(Effect("draw-main", kind="RNG_DRAW", resource="main"),),
            ),
        ),
    )
    executor = TickExecutor((definition,))
    stream = PCG32Stream.seeded(42, 54)
    manager = RetainedRollbackHistory(executor, retained_history_ticks=8)
    state = executor.initial_state(rng_streams={"main": stream.to_snapshot()})
    state, _, _ = manager.advance(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id="RANDOM"),),
    )
    for _ in range(3):
        state, _, _ = manager.advance(state)
    draw = TickInput("draw", 1, 1, "DRAW", 1)

    baseline = executor.restore(manager.frames[1].snapshot)
    direct, direct_traces = _run(executor, baseline, {1: ((draw,), HostSnapshot())}, 4)
    result = manager.correct_and_resimulate(1, (draw,))

    assert result.state.to_snapshot() == direct.to_snapshot()
    assert result.state.rng_streams["main"]["draw_count"] == 1
    assert result.traces[0]["effect_reduction"] == direct_traces[0]["effect_reduction"]
    assert result.traces[0]["effect_reduction"][0]["effect_type"] == "pcam.rng.draw"


def _presentation_executor():
    fact = FactBinding(
        SemanticFact(
            "strike",
            "OFFENSE",
            effect_templates=(
                EffectTemplate("combat.damage", "DAMAGE", 10, "SUM"),
                EffectTemplate("presentation.spark", "PRESENTATION", {"spark": True}, authoritative=False),
            ),
        ),
        "ACTIVE",
        HitPolicy("ONCE_PER_ACTION_INSTANCE", "ON_IMPACT"),
    )
    definition = ActionDefinition(
        "PRESENT",
        1,
        0,
        (NodeDefinition("RUN"),),
        predicates=(PredicateDefinition("ACTIVE", node_ids=("RUN",)),),
        semantic_facts=(fact,),
    )
    rule = InteractionRule(
        "materialize",
        "MATERIALIZATION",
        1,
        {"literal": True},
        (RuleOperation("MATERIALIZE"),),
    )
    return TickExecutor((definition,), interaction_rules=(rule,)), definition


def test_ledger_restore_and_stable_presentation_effect_reconciliation():
    executor, definition = _presentation_executor()
    manager = RetainedRollbackHistory(executor, retained_history_ticks=8)
    state = executor.initial_state(resource_banks={"2": {"hp": 100}})
    state, _, _ = manager.advance(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id),),
    )
    contact = Contact("contact", 1, 2, "strike", source_entity_id=1, contact_id="contact")
    state, _, presented = manager.advance(state, host=HostSnapshot(contacts=(contact,)))
    state, _, _ = manager.advance(state)
    original = state.to_snapshot()
    original_ledger = dict(state.interaction_ledgers)
    assert len(presented) == 1

    replay = manager.correct_and_resimulate(1, ())
    assert replay.state.to_snapshot() == original
    assert replay.state.interaction_ledgers == original_ledger
    assert replay.presentation_emit == ()
    assert replay.presentation_suppressed == presented
    assert replay.presentation_invalidated == ()

    removed = manager.correct_and_resimulate(1, (), corrected_host=HostSnapshot())
    assert removed.state.resource_banks["2"]["hp"] == 100
    assert removed.state.interaction_ledgers == {}
    assert removed.presentation_invalidated == presented
    assert removed.presentation_suppressed == ()


def test_retained_history_fails_closed_outside_the_correction_window():
    definition = ActionDefinition("BOUNDED", 1, 0, (NodeDefinition("RUN"),))
    executor = TickExecutor((definition,))
    manager = RetainedRollbackHistory(executor, retained_history_ticks=2)
    state = executor.initial_state()
    for _ in range(4):
        state, _, _ = manager.advance(state)
    assert tuple(manager.frames) == (2, 3)
    with pytest.raises(ValueError, match="outside retained history"):
        manager.correct_and_resimulate(1, ())


def test_faulting_correction_is_atomic_and_wrong_tick_input_is_rejected():
    definition = ActionDefinition(
        "FAULT_ATOMIC",
        1,
        0,
        (NodeDefinition("RUN"),),
        transitions=(
            TransitionDefinition(
                "draw-missing",
                "RUN",
                "PRE_ADVANCE",
                1,
                target_node="RUN",
                input_command="DRAW",
                effects=(Effect("draw-missing", kind="RNG_DRAW", resource="missing"),),
            ),
        ),
    )
    executor = TickExecutor((definition,))
    manager = RetainedRollbackHistory(executor, retained_history_ticks=4)
    state = executor.initial_state()
    state, _, _ = manager.advance(
        state,
        (TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id),),
    )
    state, _, _ = manager.advance(state)
    before_frames = {tick: frame.snapshot for tick, frame in manager.frames.items()}
    before_head = manager.head_state.to_snapshot()

    wrong_tick = TickInput("wrong", 1, 1, "DRAW", 0)
    with pytest.raises(ValueError, match="assigned_tick"):
        manager.correct_and_resimulate(1, (wrong_tick,))

    duplicate = TickInput("duplicate", 1, 1, "DRAW", 1)
    with pytest.raises(ValueError, match="duplicate input_id"):
        manager.correct_and_resimulate(1, (duplicate, duplicate))

    draw = TickInput("draw", 1, 1, "DRAW", 1)
    with pytest.raises(PCAMError):
        manager.correct_and_resimulate(1, (draw,))
    assert {tick: frame.snapshot for tick, frame in manager.frames.items()} == before_frames
    assert manager.head_state.to_snapshot() == before_head


def test_rollback_gate_manifest_names_every_required_case():
    manifest = json.loads((ROOT / "tests/rollback/coverage.json").read_text())
    assert manifest["spec_section"] == "45.6"
    assert set(manifest["requirements"]) == {
        "late_input",
        "mispredicted_input",
        "multi_tick_rewind",
        "action_start",
        "hit_stop",
        "child_action",
        "rng",
        "interaction_ledger_restoration",
        "presentation_event_deduplication",
    }
    assert all(item["state"] == "PASS" and item["evidence"] for item in manifest["requirements"].values())
