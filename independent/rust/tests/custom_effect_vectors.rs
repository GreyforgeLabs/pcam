use pcam_independent::canonical_hash_json;
use pcam_independent::effects::{
    CustomEffectRegistration, EffectEnvelope, EffectError, custom_registry,
    reduce_effects_with_registry,
};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

const VECTOR_HASH: &str = "cd14a75292221115aa6b05fe3a5331d9cb81a79f42a845e9365edbff6da9332d";

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn vector() -> (Vec<u8>, Value) {
    let source = fs::read(root().join("tests/vectors/custom-effect-ordered-fold.json"))
        .expect("shared custom effect vector");
    let document = serde_json::from_slice(&source).expect("custom effect vector JSON");
    (source, document)
}

fn registration(document: &Value) -> CustomEffectRegistration {
    serde_json::from_value(serde_json::json!({
        "effect_type": document["effect_type"],
        "implementation_id": "greyforge.effect.ordered-i64-fold.v1",
        "implementation_hash": document["implementation_sha256"],
        "implementation_path": document["implementation_path"],
        "payload_schema": document["payload_schema"],
        "determinism_vectors": [VECTOR_HASH],
        "reducer": "CUSTOM_DETERMINISTIC",
        "runtime_semantics_id": "pcam.runtime.custom.ordered-i64-fold.v1",
        "ordering_id": "pcam.order.canonical-effect.v1",
        "overflow_behavior_id": "pcam.overflow.checked-i64.v1",
        "save_restore_id": "pcam.save.stateless.v1",
        "rollback_behavior_id": "pcam.rollback.snapshot-restore.v1"
    }))
    .expect("custom effect registration")
}

fn effects(value: &Value) -> Vec<EffectEnvelope> {
    serde_json::from_value(value.clone()).expect("effect envelopes")
}

#[test]
fn independent_custom_effect_is_hash_bound_ordered_and_permutation_invariant() {
    let (source, document) = vector();
    assert_eq!(canonical_hash_json(&source).unwrap(), VECTOR_HASH);
    let registry = custom_registry(vec![registration(&document)]).unwrap();
    for permutation in document["permutations"].as_array().unwrap() {
        let (reduced, rejected) =
            reduce_effects_with_registry(&effects(permutation), &registry).unwrap();
        assert!(rejected.is_empty());
        assert_eq!(
            serde_json::to_value(&reduced[0]).unwrap(),
            document["expected"]
        );
    }
}

#[test]
fn independent_custom_effect_payload_overflow_and_registration_fail_closed() {
    let (_, document) = vector();
    let registry = custom_registry(vec![registration(&document)]).unwrap();
    for case in document["fault_cases"].as_array().unwrap() {
        let error = reduce_effects_with_registry(&effects(&case["effects"]), &registry)
            .expect_err("custom fault case must reject");
        let actual = match error {
            EffectError::IntegerOverflow => "INTEGER_OVERFLOW",
            EffectError::UnknownEffect | EffectError::InvalidRegistration => "UNKNOWN_EFFECT",
        };
        assert_eq!(actual, case["fault"], "{}", case["id"]);
    }

    let mut tampered = registration(&document);
    tampered.implementation_hash = "0".repeat(64);
    assert_eq!(
        custom_registry(vec![tampered]).unwrap_err(),
        EffectError::InvalidRegistration
    );
}
