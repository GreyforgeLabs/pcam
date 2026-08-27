use pcam_independent::simulation::{RetainedRollbackHistory, SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/mixed-stage-runtime.json"))
        .expect("shared mixed-stage runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

#[test]
fn independent_mixed_stage_runtime_matches_exact_pipeline_evidence() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut state = runtime.initial_state(&vector).unwrap();
    let mut traces = Vec::new();
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        let trace;
        (state, trace) = runtime.tick(&state, tick).unwrap();
        assert_eq!(
            state.digest().unwrap(),
            vector["expected"]["tick_state_digests"][index]
                .as_str()
                .unwrap(),
            "tick {index}"
        );
        traces.push(trace);
    }
    assert_eq!(
        state.definition_set_hash,
        vector["expected"]["definition_set_hash"].as_str().unwrap()
    );
    assert_eq!(
        state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
    assert_eq!(state.resource_banks["2"]["hp"], 43);
    assert_eq!(state.interaction_ledgers.len(), 1);
    assert_eq!(state.action_instances[0].lifecycle_state, "TERMINATED");
    assert_eq!(state.action_instances[1].lifecycle_state, "RUNNING");
    assert_eq!(state.action_instances[2].lifecycle_state, "TERMINATED");
    assert_eq!(
        state.action_instances[0].definition_hash,
        vector["expected"]["definition_hashes"]["PARENT"]
            .as_str()
            .unwrap()
    );
    assert_eq!(
        state.action_instances[1].definition_hash,
        vector["expected"]["definition_hashes"]["DEFENDER"]
            .as_str()
            .unwrap()
    );
    assert_eq!(
        state.action_instances[2].definition_hash,
        vector["expected"]["definition_hashes"]["CHILD"]
            .as_str()
            .unwrap()
    );
    assert_eq!(traces[1].candidate_order, ["child-strike"]);
    assert_eq!(traces[3].events_delivered, ["child-result:3:1"]);

    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let (tick_zero, _) = runtime.tick(&initial, &vector["ticks"][0]).unwrap();
    let (tick_one, interaction) = runtime.tick(&tick_zero, &vector["ticks"][1]).unwrap();
    assert_eq!(
        tick_one.digest().unwrap(),
        vector["expected"]["mid_state_digest"]
    );
    assert_eq!(interaction.candidate_order, ["child-strike"]);
    assert_eq!(interaction.effects.len(), 1);
    assert_eq!(interaction.effects[0].effect_class, "DAMAGE");
    assert_eq!(interaction.effects[0].payload, 7);
    assert_eq!(interaction.receipts[0]["receipt_written"], true);
    assert_eq!(interaction.reduced[0].value, 7);
}

#[test]
fn independent_mixed_stage_snapshot_restores_and_continues_exactly() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut uninterrupted = runtime.initial_state(&vector).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[..2] {
        (uninterrupted, _) = runtime.tick(&uninterrupted, tick).unwrap();
    }
    assert_eq!(
        uninterrupted.digest().unwrap(),
        vector["expected"]["mid_state_digest"].as_str().unwrap()
    );
    assert_eq!(uninterrupted.resource_banks["2"]["hp"], 43);
    assert_eq!(uninterrupted.interaction_ledgers.len(), 1);
    assert_eq!(uninterrupted.next_action_instance_id, 4);
    assert_eq!(uninterrupted.next_freeze_token_id, 2);
    assert_eq!(uninterrupted.action_instances[0].child_instance_ids, [3]);
    assert_eq!(
        uninterrupted.action_instances[2].parent_instance_id,
        Some(1)
    );
    assert_eq!(uninterrupted.freeze_tokens.len(), 1);

    let mut restored = SimulationState::restore(&uninterrupted.snapshot().unwrap()).unwrap();
    assert_eq!(restored, uninterrupted);
    for tick in &vector["ticks"].as_array().unwrap()[2..] {
        let left_trace;
        let right_trace;
        (uninterrupted, left_trace) = runtime.tick(&uninterrupted, tick).unwrap();
        (restored, right_trace) = runtime.tick(&restored, tick).unwrap();
        assert_eq!(left_trace.state_digest, right_trace.state_digest);
        assert_eq!(left_trace.effects, right_trace.effects);
    }
    assert_eq!(restored, uninterrupted);
    assert_eq!(
        restored.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
}

#[test]
fn independent_mixed_stage_retained_correction_matches_direct_execution() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let mut history = RetainedRollbackHistory::new(runtime.clone(), 8).unwrap();
    let mut predicted = initial.clone();
    for tick in vector["ticks"].as_array().unwrap() {
        (predicted, _, _) = history.advance(&predicted, tick).unwrap();
    }
    assert_eq!(
        predicted.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );

    let corrected_tick = vector["expected"]["corrected_tick"].as_u64().unwrap();
    let mut corrected_document = vector["ticks"][corrected_tick as usize].clone();
    corrected_document["inputs"] = Value::Array(Vec::new());
    let correction = history
        .correct_and_resimulate(corrected_tick, &corrected_document)
        .unwrap();
    assert_eq!(
        serde_json::to_value(
            correction
                .traces
                .iter()
                .map(|trace| trace.state_digest.clone())
                .collect::<Vec<_>>()
        )
        .unwrap(),
        vector["expected"]["corrected_tick_state_digests"]
    );
    assert_eq!(
        correction.state.digest().unwrap(),
        vector["expected"]["corrected_final_state_digest"]
            .as_str()
            .unwrap()
    );

    let mut direct = initial;
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        let actual = if index as u64 == corrected_tick {
            &corrected_document
        } else {
            tick
        };
        (direct, _) = runtime.tick(&direct, actual).unwrap();
    }
    assert_eq!(correction.state, direct);
    assert_eq!(correction.state.resource_banks["2"]["hp"], 50);
    assert!(correction.state.interaction_ledgers.is_empty());
    assert_eq!(correction.state.action_instances.len(), 2);
}

#[test]
fn independent_mixed_stage_raw_start_order_is_invariant() {
    let vector = vector();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let mut direct = runtime.initial_state(&vector).unwrap();
    for tick in vector["ticks"].as_array().unwrap() {
        (direct, _) = runtime.tick(&direct, tick).unwrap();
    }

    let mut reversed = vector.clone();
    reversed["ticks"][0]["inputs"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let reversed_runtime = SimulationRuntime::from_vector(&reversed).unwrap();
    let mut reversed_state = reversed_runtime.initial_state(&reversed).unwrap();
    for tick in reversed["ticks"].as_array().unwrap() {
        (reversed_state, _) = reversed_runtime.tick(&reversed_state, tick).unwrap();
    }
    assert_eq!(reversed_state, direct);
    assert_eq!(
        reversed_state.digest().unwrap(),
        vector["expected"]["final_state_digest"].as_str().unwrap()
    );
}
