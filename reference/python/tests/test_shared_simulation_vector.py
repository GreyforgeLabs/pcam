import json
from dataclasses import replace
from pathlib import Path

import pytest

from pcam_runtime import PCAMError, RetainedRollbackHistory, TickInput
from pcam_runtime.vectors import rollback_vector, run_vector

ROOT = Path(__file__).resolve().parents[3]


def _document():
    return json.loads((ROOT / "tests/vectors/typed-strike.json").read_text(encoding="utf-8"))


def _parent_child_document():
    return json.loads((ROOT / "tests/vectors/parent-child.json").read_text(encoding="utf-8"))


def _contended_starts_document():
    return json.loads((ROOT / "tests/vectors/contended-starts.json").read_text(encoding="utf-8"))


def _presentation_document():
    return json.loads((ROOT / "tests/vectors/presentation-rollback.json").read_text(encoding="utf-8"))


def _fault_trigger_document():
    return json.loads((ROOT / "tests/vectors/fault-trigger-runtime.json").read_text(encoding="utf-8"))


def _transition_replacement_document():
    return json.loads((ROOT / "tests/vectors/transition-replacement.json").read_text(encoding="utf-8"))


def _interaction_runtime_document():
    return json.loads((ROOT / "tests/vectors/interaction-runtime.json").read_text(encoding="utf-8"))


def _parent_policies_document():
    return json.loads((ROOT / "tests/vectors/parent-policies.json").read_text(encoding="utf-8"))


def _child_termination_document():
    return json.loads(
        (ROOT / "tests/vectors/child-termination-policies.json").read_text(encoding="utf-8")
    )


def _nesting_runtime_document():
    return json.loads((ROOT / "tests/vectors/nesting-runtime.json").read_text(encoding="utf-8"))


def _pre_stage_arbitration_document():
    return json.loads(
        (ROOT / "tests/vectors/pre-stage-arbitration.json").read_text(encoding="utf-8")
    )


def _multi_transition_arbitration_document():
    return json.loads(
        (ROOT / "tests/vectors/multi-transition-arbitration.json").read_text(encoding="utf-8")
    )


def _post_stage_arbitration_document():
    return json.loads(
        (ROOT / "tests/vectors/post-stage-arbitration.json").read_text(encoding="utf-8")
    )


def _redirect_runtime_document():
    return json.loads((ROOT / "tests/vectors/redirect-runtime.json").read_text(encoding="utf-8"))


def test_python_typed_strike_matches_shared_full_state_identity_and_tick_digests():
    document = _document()
    expected = document["expected"]
    run = run_vector(document)

    definition = next(iter(run.executor.definitions_by_id.values()))
    assert definition.definition_hash == expected["definition_hash"]
    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert run.traces[0]["candidate_order"] == ["c1", "c2"]
    assert run.traces[0]["typed_effects_emitted"][0]["effect_id"] == "0:1:c1:materialize:0:0"
    assert run.traces[0]["decision_record_mutations"][1]["reason"] == "ONCE_PER_ACTION_INSTANCE"


def test_python_typed_strike_shared_rollback_matches_direct_execution():
    direct, corrected, traces = rollback_vector(_document())

    assert corrected.to_snapshot() == direct.to_snapshot()
    assert traces[-1]["state_digest"] == direct.state_hash()


def test_python_parent_child_matches_shared_result_event_lifecycle_digests():
    document = _parent_child_document()
    expected = document["expected"]
    run = run_vector(document)

    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    parent = run.final_state.action_instances["1"]
    child = run.final_state.action_instances["2"]
    assert (parent.current_node_id, parent.lifecycle_state, parent.transition_serial) == (
        "DONE",
        "TERMINATED",
        2,
    )
    assert child.extension_state["pcam.child_result_emitted"] is True
    assert run.final_state.pending_events == ()
    assert run.final_state.freeze_tokens == ()


def test_python_contended_starts_match_shared_arbitration_state_digest():
    document = _contended_starts_document()
    expected = document["expected"]
    run = run_vector(document)

    assert run.executor.definition_set_hash == expected["definition_set_hash"]
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == expected["definition_hashes"]
    assert [trace["state_digest"] for trace in run.traces] == expected["tick_state_digests"]
    assert run.final_state.state_hash() == expected["final_state_digest"]
    assert len(run.final_state.action_instances) == 1
    assert run.final_state.action_instances["1"].definition_hash == expected["definition_hashes"]["DODGE_A"]
    assert run.final_state.resource_banks["1"]["STAMINA"] == 3
    assert run.final_state.action_slots["1"]["FULL_BODY"] == {
        "capacity": 1,
        "instance_ids": [1],
        "usage": 1,
    }


def _advance_document(manager, state, run, document, tick_zero_inputs=None):
    for tick_index in range(len(document["ticks"])):
        inputs = run.input_history[tick_index]
        if tick_index == 0 and tick_zero_inputs is not None:
            inputs = tick_zero_inputs
        state, _, _ = manager.advance(state, inputs, run.host_history[tick_index])
    return state


def test_python_presentation_reconciliation_matches_shared_emit_suppress_and_invalidate():
    document = _presentation_document()
    run = run_vector(document)
    expected = document["expected"]
    expected_id = expected["presentation_effect_id"]
    initial = run.executor.restore(run.initial_snapshot)

    actual = RetainedRollbackHistory(run.executor, 4)
    state = _advance_document(actual, initial, run, document)
    assert state.state_hash() == expected["final_state_digest"]
    replayed = actual.correct_and_resimulate(0, run.input_history[0])
    assert replayed.presentation_suppressed == (expected_id,)
    assert replayed.presentation_emit == ()
    assert replayed.presentation_invalidated == ()

    removed = RetainedRollbackHistory(run.executor, 4)
    _advance_document(removed, initial, run, document)
    correction = removed.correct_and_resimulate(0, ())
    assert correction.presentation_invalidated == (expected_id,)
    assert correction.presentation_emit == ()
    assert correction.presentation_suppressed == ()

    predicted = RetainedRollbackHistory(run.executor, 4)
    _advance_document(predicted, initial, run, document, tick_zero_inputs=())
    correction = predicted.correct_and_resimulate(0, run.input_history[0])
    assert correction.presentation_emit == (expected_id,)
    assert correction.presentation_invalidated == ()
    assert correction.presentation_suppressed == ()


def test_python_fault_trigger_discards_tick_work_and_applies_shared_policy():
    vector = _fault_trigger_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["runtime_profile"]["fault_policy"] = case["policy"]
        run = run_vector(document)
        actions = {
            key: replace(action, current_rate_units=document["rate_overrides"][key])
            for key, action in run.final_state.action_instances.items()
        }
        before = replace(run.final_state, action_instances=actions)
        assert before.state_hash() == case["pre_fault_digest"], case["policy"]

        if case["policy"] == "ABORT_SIMULATION":
            with pytest.raises(PCAMError) as raised:
                run.executor.tick(before)
            assert raised.value.fault.value == case["fault"]
            assert before.state_hash() == case["pre_fault_digest"]
            continue

        state, trace = run.executor.tick(before)
        summary = {
            "tick": state.tick,
            "lifecycle": {
                key: action.lifecycle_state for key, action in state.action_instances.items()
            },
            "local_steps": {key: action.local_step for key, action in state.action_instances.items()},
            "fault_records": {
                key: action.fault_record for key, action in state.action_instances.items()
            },
            "entity_fault_owners": sorted(
                int(key) for key, record in state.entity_records.items() if "fault_record" in record
            ),
            "trace_faults": trace["faults"],
            "trace_effects": trace["typed_effects_emitted"],
        }
        assert summary == case["expected"], case["policy"]
        assert state.state_hash() == case["final_state_digest"], case["policy"]


def test_python_transition_replacement_matches_shared_atomic_outcomes():
    vector = _transition_replacement_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["initial_state"]["resource_banks"]["1"]["STAMINA"] = case["stamina"]
        run = run_vector(document)
        state = run.final_state
        summary = {
            "tick": state.tick,
            "lifecycle": {
                key: action.lifecycle_state for key, action in state.action_instances.items()
            },
            "definitions": {
                key: action.definition_hash for key, action in state.action_instances.items()
            },
            "transition_serials": {
                key: action.transition_serial for key, action in state.action_instances.items()
            },
            "stamina": state.resource_banks["1"]["STAMINA"],
            "slot": state.action_slots["1"]["FULL_BODY"],
            "next_action_instance_id": state.next_action_instance_id,
        }
        assert [trace["state_digest"] for trace in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"], case["id"]
        assert summary == case["expected"], case["id"]


def test_python_interaction_rules_match_shared_complete_tick_outcomes():
    vector = _interaction_runtime_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][1]["semantic_facts"][0]["fact"]["tags"] = case[
            "defense_tags"
        ]
        run = run_vector(document)
        trace = run.traces[0]
        summary = {
            "resources": run.final_state.resource_banks["2"],
            "ledger_count": len(run.final_state.interaction_ledgers),
            "effects": [
                [effect["effect_class"], effect["effect_id"], effect["payload"]]
                for effect in trace["typed_effects_emitted"]
            ],
            "decision": trace["decision_record_mutations"],
            "reduced": trace["effect_reduction"],
        }
        assert [item["state_digest"] for item in run.traces] == case["tick_state_digests"]
        assert summary == case["expected"], case["id"]


def test_python_parent_policies_match_shared_domain_specific_outcomes():
    vector = _parent_policies_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][0]["transitions"][0]["parent_policy"] = case["policy"]
        run = run_vector(document)
        state = run.final_state
        parent = state.action_instances["1"]
        child = state.action_instances["2"]
        summary = {
            "parent_lifecycle": parent.lifecycle_state,
            "parent_node": parent.current_node_id,
            "parent_local_step": parent.local_step,
            "parent_transition_serial": parent.transition_serial,
            "parent_children": list(parent.child_instance_ids),
            "child_lifecycle": child.lifecycle_state,
            "child_parent": child.parent_instance_id,
            "freeze_domains": [list(token.domains) for token in state.freeze_tokens],
            "freeze_remaining": [token.remaining_ticks for token in state.freeze_tokens],
            "next_freeze_token_id": state.next_freeze_token_id,
        }
        assert [item["state_digest"] for item in run.traces] == case["tick_state_digests"]
        assert summary == case["expected"], case["policy"]


def test_python_child_termination_policies_match_shared_atomic_outcomes():
    vector = _child_termination_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][0]["child_termination_policies"]["SUB"] = case["policy"]
        if case["policy"] == "FAULT_IF_OCCUPIED":
            stop = document["ticks"][2]["inputs"][0]
            document["ticks"] = document["ticks"][:2]
            run = run_vector(document)
            assert run.final_state.state_hash() == case["pre_fault_digest"]
            tick_input = TickInput(
                stop["input_id"],
                stop["source_entity_id"],
                stop["sequence"],
                stop["command_id"],
                stop["assigned_tick"],
            )
            with pytest.raises(PCAMError) as raised:
                run.executor.tick(run.final_state, (tick_input,))
            assert raised.value.fault.value == case["fault"]
            assert run.final_state.state_hash() == case["pre_fault_digest"]
            continue
        run = run_vector(document)
        state = run.final_state
        parent = state.action_instances["1"]
        child = state.action_instances["2"]
        summary = {
            "parent_lifecycle": parent.lifecycle_state,
            "parent_children": list(parent.child_instance_ids),
            "child_lifecycle": child.lifecycle_state,
            "child_parent": child.parent_instance_id,
            "child_slot": child.parent_slot_id,
            "pending_event_types": [event["event_type"] for event in state.pending_events],
            "child_result_emitted": child.extension_state.get("pcam.child_result_emitted", False),
        }
        assert [item["state_digest"] for item in run.traces] == case["tick_state_digests"]
        assert summary == case["expected"], case["policy"]


def test_python_nesting_limit_matches_shared_success_and_atomic_fault():
    vector = _nesting_runtime_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["runtime_profile"]["limits"]["max_action_nesting_depth"] = case["max_depth"]
        if case["max_depth"] == 2:
            last = document["ticks"][2]["inputs"][0]
            document["ticks"] = document["ticks"][:2]
            run = run_vector(document)
            assert run.final_state.state_hash() == case["pre_fault_digest"]
            tick_input = TickInput(
                last["input_id"],
                last["source_entity_id"],
                last["sequence"],
                last["command_id"],
                last["assigned_tick"],
            )
            with pytest.raises(PCAMError) as raised:
                run.executor.tick(run.final_state, (tick_input,))
            assert raised.value.fault.value == case["fault"]
            assert run.final_state.state_hash() == case["pre_fault_digest"]
            continue
        run = run_vector(document)
        state = run.final_state
        summary = {
            "next_action_instance_id": state.next_action_instance_id,
            "parents": {
                key: action.parent_instance_id for key, action in state.action_instances.items()
            },
            "children": {
                key: list(action.child_instance_ids) for key, action in state.action_instances.items()
            },
            "lifecycle": {
                key: action.lifecycle_state for key, action in state.action_instances.items()
            },
        }
        assert [item["state_digest"] for item in run.traces] == case["tick_state_digests"]
        assert summary == case["expected"]


def test_python_pre_stage_arbitrates_transitions_and_direct_starts_together():
    vector = _pre_stage_arbitration_document()
    for case in vector["cases"]:
        document = json.loads(json.dumps(vector))
        document["definitions"][0]["transitions"][0]["priority"] = case[
            "transition_priority"
        ]
        run = run_vector(document)
        state = run.final_state
        summary = {
            "tick": state.tick,
            "lifecycle": {
                key: action.lifecycle_state for key, action in state.action_instances.items()
            },
            "definitions": {
                key: action.definition_hash for key, action in state.action_instances.items()
            },
            "transition_serials": {
                key: action.transition_serial for key, action in state.action_instances.items()
            },
            "stamina": state.resource_banks["1"]["STAMINA"],
            "slot": state.action_slots["1"]["FULL_BODY"],
            "next_action_instance_id": state.next_action_instance_id,
        }
        assert {
            identifier: definition.definition_hash
            for identifier, definition in run.executor.definitions_by_id.items()
        } == case["definition_hashes"]
        assert run.executor.definition_set_hash == case["definition_set_hash"]
        assert [item["state_digest"] for item in run.traces] == case["tick_state_digests"]
        assert state.state_hash() == case["final_state_digest"]
        assert summary == case["expected"], case["id"]


def test_python_pre_stage_arbitrates_simultaneous_transitions_together():
    document = _multi_transition_arbitration_document()
    run = run_vector(document)
    state = run.final_state
    summary = {
        "tick": state.tick,
        "lifecycle": {
            key: action.lifecycle_state for key, action in state.action_instances.items()
        },
        "definitions": {
            key: action.definition_hash for key, action in state.action_instances.items()
        },
        "transition_serials": {
            key: action.transition_serial for key, action in state.action_instances.items()
        },
        "stamina": state.resource_banks["1"]["STAMINA"],
        "slot": state.action_slots["1"]["FULL_BODY"],
        "next_action_instance_id": state.next_action_instance_id,
    }
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == document["definition_hashes"]
    assert run.executor.definition_set_hash == document["definition_set_hash"]
    assert [item["state_digest"] for item in run.traces] == document["tick_state_digests"]
    assert state.state_hash() == document["final_state_digest"]
    assert summary == document["expected"]


def test_python_post_stage_arbitrates_transitions_and_defers_target_progression():
    document = _post_stage_arbitration_document()
    run = run_vector(document)
    state = run.final_state
    target_steps = []
    for trace in run.traces:
        target = next(
            (
                action
                for action in trace["state_changes"]["action_instances"]
                if action["instance_id"] == 3
            ),
            None,
        )
        target_steps.append(None if target is None else target["local_step"])
    summary = {
        "tick": state.tick,
        "lifecycle": {
            key: action.lifecycle_state for key, action in state.action_instances.items()
        },
        "definitions": {
            key: action.definition_hash for key, action in state.action_instances.items()
        },
        "transition_serials": {
            key: action.transition_serial for key, action in state.action_instances.items()
        },
        "local_steps": {key: action.local_step for key, action in state.action_instances.items()},
        "stamina": state.resource_banks["1"]["STAMINA"],
        "slot": state.action_slots["1"]["FULL_BODY"],
        "next_action_instance_id": state.next_action_instance_id,
    }
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == document["definition_hashes"]
    assert run.executor.definition_set_hash == document["definition_set_hash"]
    assert [item["state_digest"] for item in run.traces] == document["tick_state_digests"]
    assert target_steps == document["target_steps_after_each_tick"]
    assert state.state_hash() == document["final_state_digest"]
    assert summary == document["expected"]


def test_python_redirect_rebinds_each_target_defense_and_commits_to_final_target():
    document = _redirect_runtime_document()
    run = run_vector(document)
    state = run.final_state
    trace = run.traces[0]
    summary = {
        "resources": state.resource_banks,
        "ledger_count": len(state.interaction_ledgers),
        "effects": [
            [
                effect["effect_class"],
                effect["effect_id"],
                effect["payload"],
                effect["target_entity_id"],
            ]
            for effect in trace["typed_effects_emitted"]
        ],
        "decision": trace["decision_record_mutations"],
        "reduced": trace["effect_reduction"],
    }
    assert {
        identifier: definition.definition_hash
        for identifier, definition in run.executor.definitions_by_id.items()
    } == document["definition_hashes"]
    assert run.executor.definition_set_hash == document["definition_set_hash"]
    assert [item["state_digest"] for item in run.traces] == document["tick_state_digests"]
    assert state.state_hash() == document["final_state_digest"]
    assert summary == document["expected"]
