use pcam_independent::canonical_hash_json;
use pcam_independent::extension::{ExtensionError, run_tick_counter, verify_implementation};
use serde::Deserialize;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    implementation_path: String,
    implementation_sha256: String,
    payload: Payload,
    ticks: usize,
    expected_counters: Vec<u64>,
    rollback: Rollback,
}

#[derive(Deserialize)]
struct Payload {
    increment: u64,
}

#[derive(Deserialize)]
struct Rollback {
    restore_tick: usize,
    expected_counter_after_two_ticks: u64,
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn independent_tick_counter_matches_shared_vector_and_restore_continuation() {
    let root = repository_root();
    let vector_source = fs::read(root.join("tests/vectors/extension-tick-counter.json"))
        .expect("shared extension vector");
    let vector: VectorFile = serde_json::from_slice(&vector_source).expect("extension vector JSON");
    assert_eq!(
        canonical_hash_json(&vector_source).unwrap(),
        "e0342685389e4f101c0b24300ee918077b675ed53c71c406542aaa88b969ec7f"
    );
    let implementation =
        fs::read(root.join(vector.implementation_path)).expect("extension module source");
    verify_implementation(&implementation, &vector.implementation_sha256).unwrap();

    let direct = run_tick_counter(0, vector.payload.increment, vector.ticks).unwrap();
    assert_eq!(direct, vector.expected_counters);
    let restored_counter = direct[vector.rollback.restore_tick - 1];
    let continued = run_tick_counter(restored_counter, vector.payload.increment, 2).unwrap();
    assert_eq!(
        *continued.last().unwrap(),
        vector.rollback.expected_counter_after_two_ticks
    );
}

#[test]
fn independent_tick_counter_fails_closed_on_hash_mismatch_and_overflow() {
    assert_eq!(
        verify_implementation(b"tampered", &"0".repeat(64)),
        Err(ExtensionError::ImplementationHashMismatch)
    );
    assert_eq!(
        run_tick_counter(u64::MAX, 1, 1),
        Err(ExtensionError::IntegerOverflow)
    );
}
