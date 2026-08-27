use pcam_independent::networking::{
    LockstepCoordinator, NetworkError, ServerAuthoritativeCorrectionPlanner,
};
use pcam_independent::simulation::{RetainedRollbackHistory, SimulationRuntime, SimulationState};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

fn load(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn documents() -> (Value, Value) {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let network = load(&root.join("tests/vectors/network-services.json"));
    let runtime = load(&root.join(network["runtime_vector"].as_str().unwrap()));
    (network, runtime)
}

fn coordinator(network: &Value, profile_name: &str) -> LockstepCoordinator {
    let profile = &network["lockstep"][profile_name];
    LockstepCoordinator::new(
        network["lockstep"]["required_peers"]
            .as_array()
            .unwrap()
            .iter()
            .map(|peer| peer.as_str().unwrap().to_owned())
            .collect(),
        network["expected"]["definition_set_hash"]
            .as_str()
            .unwrap()
            .to_owned(),
        profile["input_availability_policy"].as_str().unwrap(),
        profile["digest_interval_ticks"].as_u64().unwrap(),
        profile["desynchronization_policy"].as_str().unwrap(),
        profile.get("predictor_id").and_then(Value::as_str),
    )
    .unwrap()
}

#[test]
fn independent_lockstep_waits_merges_and_exchanges_matching_digests() {
    let (network, vector) = documents();
    let definition_hash = network["expected"]["definition_set_hash"].as_str().unwrap();
    let tick = &vector["ticks"][0];
    let mut lockstep = coordinator(&network, "wait_profile");
    lockstep
        .submit(
            "peer.a",
            0,
            definition_hash,
            tick["inputs"].as_array().unwrap(),
            tick["contacts"].as_array().unwrap(),
        )
        .unwrap();
    let waiting = lockstep.advance().unwrap();
    assert_eq!(waiting.status, "WAITING");
    assert_eq!(waiting.missing_peers, ["peer.b"]);
    assert_eq!(lockstep.next_tick, 0);
    assert_eq!(
        lockstep.submit(
            "peer.b",
            0,
            network["lockstep"]["bad_definition_set_hash"]
                .as_str()
                .unwrap(),
            &[],
            tick["contacts"].as_array().unwrap(),
        ),
        Err(NetworkError::DefinitionMismatch)
    );
    lockstep
        .submit(
            "peer.b",
            0,
            definition_hash,
            &[],
            tick["contacts"].as_array().unwrap(),
        )
        .unwrap();
    let ready = lockstep.advance().unwrap();
    assert_eq!(ready.tick_document.as_ref().unwrap(), tick);
    assert!(ready.digest_due);

    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let (_, trace) = runtime
        .tick(&initial, ready.tick_document.as_ref().unwrap())
        .unwrap();
    let digest = trace.state_digest;
    assert_eq!(digest, network["expected"]["tick_state_digests"][0]);
    assert_eq!(
        lockstep
            .submit_digest("peer.a", 0, &digest, &digest)
            .unwrap()
            .status,
        "WAITING"
    );
    assert_eq!(
        lockstep
            .submit_digest("peer.b", 0, &digest, &digest)
            .unwrap()
            .status,
        "MATCH"
    );
}

#[test]
fn independent_lockstep_prediction_host_mismatch_and_desync_fail_closed() {
    let (network, vector) = documents();
    let definition_hash = network["expected"]["definition_set_hash"].as_str().unwrap();
    let mut predicted = coordinator(&network, "predict_profile");
    predicted
        .submit("peer.a", 0, definition_hash, &[], &[])
        .unwrap();
    let result = predicted.advance().unwrap();
    assert_eq!(result.predicted_peers, ["peer.b"]);
    assert_eq!(
        result.tick_document.unwrap(),
        serde_json::json!({"inputs": [], "contacts": []})
    );
    assert!(!result.digest_due);

    let mut mismatch = coordinator(&network, "wait_profile");
    mismatch
        .submit(
            "peer.a",
            0,
            definition_hash,
            &[],
            vector["ticks"][0]["contacts"].as_array().unwrap(),
        )
        .unwrap();
    mismatch
        .submit("peer.b", 0, definition_hash, &[], &[])
        .unwrap();
    assert!(matches!(
        mismatch.advance(),
        Err(NetworkError::HostMismatch)
    ));
    assert_eq!(mismatch.next_tick, 0);

    let mut aborted = coordinator(&network, "wait_profile");
    let tick = &vector["ticks"][0];
    aborted
        .submit(
            "peer.a",
            0,
            definition_hash,
            tick["inputs"].as_array().unwrap(),
            tick["contacts"].as_array().unwrap(),
        )
        .unwrap();
    aborted
        .submit(
            "peer.b",
            0,
            definition_hash,
            &[],
            tick["contacts"].as_array().unwrap(),
        )
        .unwrap();
    aborted.advance().unwrap();
    let digest = network["expected"]["tick_state_digests"][0]
        .as_str()
        .unwrap();
    aborted.submit_digest("peer.a", 0, digest, digest).unwrap();
    let resolution = aborted
        .submit_digest(
            "peer.b",
            0,
            network["lockstep"]["bad_state_digest"].as_str().unwrap(),
            digest,
        )
        .unwrap();
    assert_eq!(resolution.status, "ABORTED");
    assert_eq!(resolution.mismatched_peers, ["peer.b"]);
    assert_eq!(aborted.advance(), Err(NetworkError::Aborted));
}

#[test]
fn independent_server_resimulation_and_replace_discard_match_server_state() {
    let (network, vector) = documents();
    let runtime = SimulationRuntime::from_vector(&vector).unwrap();
    let initial = runtime.initial_state(&vector).unwrap();
    let mut direct = initial.clone();
    for tick in vector["ticks"].as_array().unwrap() {
        (direct, _) = runtime.tick(&direct, tick).unwrap();
    }

    let mut manager = RetainedRollbackHistory::new(runtime.clone(), 8).unwrap();
    let mut predicted = initial.clone();
    for (index, tick) in vector["ticks"].as_array().unwrap().iter().enumerate() {
        let mut document = tick.clone();
        if index == 0 {
            document["inputs"] = Value::Array(Vec::new());
        }
        (predicted, _, _) = manager.advance(&predicted, &document).unwrap();
    }
    assert_ne!(predicted, direct);

    let resimulate = &network["server_authoritative"]["resimulate"];
    let planner = ServerAuthoritativeCorrectionPlanner::new(
        resimulate["correction_policy"].as_str().unwrap(),
        resimulate["max_latency_compensation_ticks"]
            .as_u64()
            .unwrap(),
    )
    .unwrap();
    let plan = planner.plan(predicted.tick, 0, false).unwrap();
    assert_eq!(plan.operation, "RESTORE_AND_RESIMULATE");
    let correction = manager
        .correct_and_resimulate(0, &vector["ticks"][0])
        .unwrap();
    assert_eq!(correction.state, direct);
    assert_eq!(
        correction.state.digest().unwrap(),
        network["expected"]["final_state_digest"]
    );

    let (authoritative_tick_one, _) = runtime.tick(&initial, &vector["ticks"][0]).unwrap();
    let replace = &network["server_authoritative"]["replace_discard"];
    let replace_planner = ServerAuthoritativeCorrectionPlanner::new(
        replace["correction_policy"].as_str().unwrap(),
        replace["max_latency_compensation_ticks"].as_u64().unwrap(),
    )
    .unwrap();
    let replace_plan = replace_planner.plan(predicted.tick, 1, true).unwrap();
    assert_eq!(replace_plan.operation, "REPLACE_AND_DISCARD");
    assert_eq!(replace_plan.discard_prediction_ticks, 2);
    let mut replaced =
        SimulationState::restore(&authoritative_tick_one.snapshot().unwrap()).unwrap();
    for tick in &vector["ticks"].as_array().unwrap()[1..] {
        (replaced, _) = runtime.tick(&replaced, tick).unwrap();
    }
    assert_eq!(replaced, direct);
    assert_eq!(
        replace_planner.plan(predicted.tick, 1, false),
        Err(NetworkError::CompleteStateRequired)
    );
    assert_eq!(
        replace_planner.plan(predicted.tick, predicted.tick + 1, true),
        Err(NetworkError::InvalidCorrection)
    );
    let bounded = ServerAuthoritativeCorrectionPlanner::new(
        replace["correction_policy"].as_str().unwrap(),
        1,
    )
    .unwrap();
    assert_eq!(
        bounded.plan(predicted.tick, 1, true),
        Err(NetworkError::CorrectionWindowExceeded)
    );
}
