use pcam_independent::effects::{EffectEnvelope, EffectError, reduce_effects};
use serde::Deserialize;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
    fault_cases: Vec<FaultCase>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    effects: Vec<EffectEnvelope>,
    reduced: Vec<Value>,
    rejected: Vec<Value>,
}

#[derive(Deserialize)]
struct FaultCase {
    id: String,
    effects: Vec<EffectEnvelope>,
    fault: String,
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/effects.json")).expect("shared effects vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn fault_code(error: EffectError) -> &'static str {
    match error {
        EffectError::IntegerOverflow => "INTEGER_OVERFLOW",
        EffectError::UnknownEffect => "UNKNOWN_EFFECT",
    }
}

#[test]
fn independent_effect_reduction_matches_all_shared_core_reducers() {
    for case in vectors().cases {
        let (reduced, rejected) = reduce_effects(&case.effects).unwrap();
        assert_eq!(
            serde_json::to_value(reduced).unwrap(),
            Value::Array(case.reduced),
            "{}:reduced",
            case.id
        );
        assert_eq!(
            serde_json::to_value(rejected).unwrap(),
            Value::Array(case.rejected),
            "{}:rejected",
            case.id
        );
    }
}

#[test]
fn independent_effect_reduction_matches_shared_faults() {
    for case in vectors().fault_cases {
        let error = reduce_effects(&case.effects).unwrap_err();
        assert_eq!(fault_code(error), case.fault, "{}", case.id);
    }
}
