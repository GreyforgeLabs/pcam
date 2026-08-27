use pcam_independent::action::{
    ActionDefinition, ActionError, RuntimeLimits, start, tick, validate_definition,
};
use serde::Deserialize;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    limits: RuntimeLimitsVector,
    cases: Vec<Case>,
    definition_fault_cases: Vec<DefinitionFaultCase>,
    fault_cases: Vec<FaultCase>,
}

#[derive(Clone, Deserialize)]
struct RuntimeLimitsVector {
    max_quanta_per_action_per_tick: u64,
    max_internal_transitions_per_tick: u64,
}

impl From<RuntimeLimitsVector> for RuntimeLimits {
    fn from(value: RuntimeLimitsVector) -> Self {
        Self {
            max_quanta_per_action_per_tick: value.max_quanta_per_action_per_tick,
            max_internal_transitions_per_tick: value.max_internal_transitions_per_tick,
        }
    }
}

#[derive(Deserialize)]
struct Case {
    id: String,
    definition: ActionDefinition,
    ticks: usize,
    expected: Vec<Value>,
}

#[derive(Deserialize)]
struct FaultCase {
    id: String,
    definition: ActionDefinition,
    limits: RuntimeLimitsVector,
    fault: String,
}

#[derive(Deserialize)]
struct DefinitionFaultCase {
    id: String,
    definition: ActionDefinition,
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn vectors() -> VectorFile {
    let source = fs::read(repository_root().join("tests/vectors/action-runtime.json"))
        .expect("shared action runtime vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn fault_code(error: ActionError) -> &'static str {
    match error {
        ActionError::IntegerOverflow => "INTEGER_OVERFLOW",
        ActionError::InvalidDefinition | ActionError::StateInvariant => "STATE_INVARIANT_FAILURE",
        ActionError::QuantumLimitExceeded => "QUANTUM_LIMIT_EXCEEDED",
        ActionError::TransitionLimitExceeded => "TRANSITION_LIMIT_EXCEEDED",
    }
}

fn assert_expected(actual: &Value, expected: &Value, case_id: &str) {
    for (key, value) in expected.as_object().expect("expected projection") {
        assert_eq!(&actual[key], value, "{case_id}:{key}");
    }
}

#[test]
fn independent_runtime_matches_shared_progression_and_transition_vectors() {
    let vectors = vectors();
    for case in vectors.cases {
        assert_eq!(case.ticks, case.expected.len(), "{}", case.id);
        let mut action = start(&case.definition).unwrap();
        for (tick_index, expected) in case.expected.iter().enumerate() {
            tick(
                &mut action,
                &case.definition,
                vectors.limits.clone().into(),
                tick_index != 0,
            )
            .unwrap();
            assert_expected(&serde_json::to_value(&action).unwrap(), expected, &case.id);
        }
    }
}

#[test]
fn independent_runtime_matches_shared_limit_faults() {
    for case in vectors().fault_cases {
        let mut action = start(&case.definition).unwrap();
        let error = tick(&mut action, &case.definition, case.limits.into(), false).unwrap_err();
        assert_eq!(fault_code(error), case.fault, "{}", case.id);
    }
}

#[test]
fn independent_runtime_rejects_shared_invalid_definitions() {
    for case in vectors().definition_fault_cases {
        assert_eq!(
            validate_definition(&case.definition).unwrap_err(),
            ActionError::InvalidDefinition,
            "{}",
            case.id
        );
    }
}
