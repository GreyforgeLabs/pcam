use pcam_independent::simulation::{RetainedRollbackHistory, SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/typed-strike.json")).expect("shared typed strike vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn parent_child_vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/parent-child.json")).expect("shared parent-child vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn contended_starts_vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/contended-starts.json"))
        .expect("shared contended starts vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn presentation_vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/presentation-rollback.json"))
        .expect("shared presentation rollback vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_simulation_matches_typed_strike_full_state_digests() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let restored = SimulationState::restore(&initial.snapshot().unwrap()).unwrap();
    assert_eq!(restored, initial);
    assert_eq!(
        initial.definition_set_hash,
        vector["expected"]["definition_set_hash"].as_str().unwrap()
    );

    let mut state = initial;
    let mut snapshots = Vec::new();
    let mut traces = Vec::new();
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        snapshots.push(state.snapshot().unwrap());
        let (next, trace) = runtime.tick(&state, tick).unwrap();
        assert_eq!(
            trace.state_digest,
            vector["expected"]["tick_state_digests"][index]
                .as_str()
                .unwrap(),
            "tick {index}"
        );
        state = next;
        traces.push(trace);
    }
    assert_eq!(
        state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(
        state.action_instances[0].definition_hash,
        vector["expected"]["definition_hash"].as_str().unwrap()
    );
    assert_eq!(state.resource_banks["2"]["hp"], 70);
    assert_eq!(state.interaction_ledgers.len(), 1);
    assert_eq!(traces[0].candidate_order, ["c1", "c2"]);
    assert_eq!(traces[0].effects[0].effect_id, "0:1:c1:materialize:0:0");
    assert_eq!(traces[0].receipts[1]["reason"], "ONCE_PER_ACTION_INSTANCE");

    let mut continued = SimulationState::restore(&snapshots[1]).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (continued, _) = runtime.tick(&continued, tick).unwrap();
    }
    assert_eq!(continued, state);
}

#[test]
fn independent_simulation_rollback_correction_matches_direct_execution() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let initial_snapshot = initial.snapshot().unwrap();
    let mut predicted_tick = vector["ticks"][0].clone();
    predicted_tick["inputs"] = Value::Array(Vec::new());
    let (mut predicted, _) = runtime.tick(&initial, &predicted_tick).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (predicted, _) = runtime.tick(&predicted, tick).unwrap();
    }
    assert_eq!(predicted.resource_banks["2"]["hp"], 100);

    let mut corrected = SimulationState::restore(&initial_snapshot).unwrap();
    for tick in vector["ticks"].as_array().unwrap() {
        (corrected, _) = runtime.tick(&corrected, tick).unwrap();
    }
    assert_eq!(
        corrected.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_ne!(corrected, predicted);
}

#[test]
fn independent_retained_history_corrects_atomically_and_enforces_window() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let mut predicted_tick = vector["ticks"][0].clone();
    predicted_tick["inputs"] = Value::Array(Vec::new());
    let mut manager = RetainedRollbackHistory::new(runtime.clone(), 8).unwrap();
    let (mut state, _, _) = manager.advance(&initial, &predicted_tick).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (state, _, _) = manager.advance(&state, tick).unwrap();
    }
    assert_eq!(state.resource_banks["2"]["hp"], 100);

    let before_frames = manager.frame_snapshots();
    let before_head = manager.head_state().unwrap().clone();
    let mut invalid = vector["ticks"][0].clone();
    invalid["inputs"][0]["action_definition_id"] = Value::String("UNKNOWN".to_owned());
    assert!(manager.correct_and_resimulate(0, &invalid).is_err());
    assert_eq!(manager.frame_snapshots(), before_frames);
    assert_eq!(manager.head_state(), Some(&before_head));

    let correction = manager
        .correct_and_resimulate(0, &vector["ticks"][0])
        .unwrap();
    assert_eq!(correction.rewind_ticks, 3);
    assert_eq!(
        correction.state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert!(correction.presentation_emit.is_empty());
    assert!(correction.presentation_invalidated.is_empty());
    assert!(correction.presentation_suppressed.is_empty());

    let mut bounded = RetainedRollbackHistory::new(runtime, 2).unwrap();
    let (mut bounded_state, _, _) = bounded.advance(&initial, &predicted_tick).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (bounded_state, _, _) = bounded.advance(&bounded_state, tick).unwrap();
    }
    assert!(
        bounded
            .correct_and_resimulate(0, &vector["ticks"][0])
            .is_err()
    );
}

#[test]
fn independent_simulation_matches_parent_child_result_event_lifecycle() {
    let vector = parent_child_vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    assert_eq!(
        state.definition_set_hash,
        vector["expected"]["definition_set_hash"].as_str().unwrap()
    );
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        (state, _) = runtime.tick(&state, tick).unwrap();
        assert_eq!(
            state.digest().unwrap(),
            vector["expected"]["tick_state_digests"][index]
                .as_str()
                .unwrap(),
            "tick {index}"
        );
    }
    assert_eq!(state.action_instances.len(), 2);
    assert_eq!(state.action_instances[0].current_node_id, "DONE");
    assert_eq!(state.action_instances[0].lifecycle_state, "TERMINATED");
    assert_eq!(state.action_instances[0].transition_serial, 2);
    assert_eq!(state.action_instances[1].parent_instance_id, Some(1));
    assert_eq!(state.action_instances[1].lifecycle_state, "TERMINATED");
    assert_eq!(
        state.action_instances[1].extension_state["pcam.child_result_emitted"],
        true
    );
    assert!(state.pending_events.is_empty());
    assert!(state.freeze_tokens.is_empty());
    assert_eq!(state.next_action_instance_id, 3);
    assert_eq!(state.next_freeze_token_id, 2);
    assert_eq!(
        SimulationState::restore(&state.snapshot().unwrap()).unwrap(),
        state
    );
}

#[test]
fn independent_parent_child_mid_child_restore_preserves_identity_freeze_and_future_digests() {
    let vector = parent_child_vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut uninterrupted = runtime.initial_state(&vector).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[..2] {
        (uninterrupted, _) = runtime.tick(&uninterrupted, tick).unwrap();
    }

    let parent = uninterrupted
        .action_instances
        .iter()
        .find(|action| action.instance_id == 1)
        .unwrap();
    let child = uninterrupted
        .action_instances
        .iter()
        .find(|action| action.instance_id == 2)
        .unwrap();
    assert_eq!(parent.child_instance_ids, [2]);
    assert_eq!(parent.freeze_token_references, [1]);
    assert_eq!(child.parent_instance_id, Some(1));
    assert_eq!(child.parent_slot_id.as_deref(), Some("SUB"));
    assert_eq!(child.lifecycle_state, "RUNNING");
    assert_eq!(uninterrupted.freeze_tokens.len(), 1);
    assert_eq!(uninterrupted.freeze_tokens[0]["source_id"], 2);
    assert_eq!(uninterrupted.freeze_tokens[0]["target_id"], 1);
    assert_eq!(
        uninterrupted.freeze_tokens[0]["domains"],
        serde_json::json!(["PROGRESSION"])
    );

    let mut restored = SimulationState::restore(&uninterrupted.snapshot().unwrap()).unwrap();
    assert_eq!(restored, uninterrupted);
    for (offset, tick) in vector["ticks"].as_array().unwrap()[2..].iter().enumerate() {
        let left_trace;
        let right_trace;
        (uninterrupted, left_trace) = runtime.tick(&uninterrupted, tick).unwrap();
        (restored, right_trace) = runtime.tick(&restored, tick).unwrap();
        assert_eq!(left_trace.state_digest, right_trace.state_digest);
        assert_eq!(
            left_trace.state_digest,
            vector["expected"]["tick_state_digests"][offset + 2]
                .as_str()
                .unwrap()
        );
    }
    assert_eq!(restored, uninterrupted);
    assert_eq!(
        restored.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
}

#[test]
fn independent_simulation_matches_contended_start_arbitration_state() {
    let vector = contended_starts_vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let (state, _) = runtime.tick(&initial, &vector["ticks"][0]).unwrap();

    assert_eq!(
        state.definition_set_hash,
        vector["expected"]["definition_set_hash"].as_str().unwrap()
    );
    assert_eq!(
        state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(state.action_instances.len(), 1);
    assert_eq!(
        state.action_instances[0].definition_hash,
        vector["expected"]["definition_hashes"]["DODGE_A"]
            .as_str()
            .unwrap()
    );
    assert_eq!(state.resource_banks["1"]["STAMINA"], 3);
    assert_eq!(state.action_slots["1"]["FULL_BODY"]["usage"], 1);
    assert_eq!(
        state.action_slots["1"]["FULL_BODY"]["instance_ids"],
        serde_json::json!([1])
    );
    assert_eq!(state.next_action_instance_id, 2);

    let mut reversed_vector = vector.clone();
    reversed_vector["ticks"][0]["inputs"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let reversed_runtime = SimulationRuntime::from_vector(&reversed_vector).unwrap();
    let reversed_initial = reversed_runtime.initial_state(&reversed_vector).unwrap();
    let (reversed_state, reversed_trace) = reversed_runtime
        .tick(&reversed_initial, &reversed_vector["ticks"][0])
        .unwrap();
    assert_eq!(reversed_state, state);
    assert_eq!(
        reversed_trace.state_digest,
        vector["expected"]["tick_state_digests"][0]
            .as_str()
            .unwrap()
    );
}

#[test]
fn independent_presentation_reconciliation_matches_emit_suppress_and_invalidate() {
    let vector = presentation_vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let expected_id = vector["expected"]["presentation_effect_id"]
        .as_str()
        .unwrap();

    let mut actual = RetainedRollbackHistory::new(runtime.clone(), 4).unwrap();
    let (state, first_trace, presented) = actual.advance(&initial, &vector["ticks"][0]).unwrap();
    assert_eq!(presented, [expected_id]);
    assert_eq!(first_trace.effects.len(), 2);
    assert_eq!(first_trace.reduced.len(), 1);
    let (state, _, _) = actual.advance(&state, &vector["ticks"][1]).unwrap();
    assert_eq!(
        state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    let replayed = actual
        .correct_and_resimulate(0, &vector["ticks"][0])
        .unwrap();
    assert_eq!(replayed.presentation_suppressed, [expected_id]);
    assert!(replayed.presentation_emit.is_empty());
    assert!(replayed.presentation_invalidated.is_empty());

    let mut removed = RetainedRollbackHistory::new(runtime.clone(), 4).unwrap();
    let (state, _, _) = removed.advance(&initial, &vector["ticks"][0]).unwrap();
    let (_state, _, _) = removed.advance(&state, &vector["ticks"][1]).unwrap();
    let mut no_start = vector["ticks"][0].clone();
    no_start["inputs"] = Value::Array(Vec::new());
    let correction = removed.correct_and_resimulate(0, &no_start).unwrap();
    assert_eq!(correction.presentation_invalidated, [expected_id]);
    assert!(correction.presentation_emit.is_empty());
    assert!(correction.presentation_suppressed.is_empty());

    let mut predicted = RetainedRollbackHistory::new(runtime, 4).unwrap();
    let (state, _, _) = predicted.advance(&initial, &no_start).unwrap();
    let (_state, _, _) = predicted.advance(&state, &vector["ticks"][1]).unwrap();
    let correction = predicted
        .correct_and_resimulate(0, &vector["ticks"][0])
        .unwrap();
    assert_eq!(correction.presentation_emit, [expected_id]);
    assert!(correction.presentation_invalidated.is_empty());
    assert!(correction.presentation_suppressed.is_empty());
}
