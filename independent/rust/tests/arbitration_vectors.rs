use pcam_independent::arbitration::{
    ArbitrationState, Claim, Intent, IntentDecision, allocate_action_instance_ids, arbitrate,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    state: StateDocument,
    intents: Vec<Intent>,
    next_action_instance_id: u64,
    decisions: Vec<Value>,
    expected_state: ExpectedState,
    allocated: BTreeMap<String, u64>,
    next_id: u64,
}

#[derive(Deserialize)]
struct StateDocument {
    resource_banks: BTreeMap<u64, BTreeMap<String, u64>>,
    capacities: Vec<CapacityDocument>,
    usages: Vec<CapacityDocument>,
    exclusive_keys: BTreeSet<String>,
}

#[derive(Deserialize)]
struct ExpectedState {
    resource_banks: BTreeMap<u64, BTreeMap<String, u64>>,
    usages: Vec<CapacityDocument>,
    exclusive_keys: Vec<String>,
}

#[derive(Clone, Deserialize)]
struct CapacityDocument {
    kind: String,
    owner_id: u64,
    key: String,
    value: u64,
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/arbitration.json")).expect("shared arbitration vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn state(document: &StateDocument) -> ArbitrationState {
    ArbitrationState {
        resource_banks: document.resource_banks.clone(),
        capacities: capacity_map(&document.capacities),
        usages: capacity_map(&document.usages),
        exclusive_keys: document.exclusive_keys.clone(),
    }
}

fn capacity_map(values: &[CapacityDocument]) -> BTreeMap<(String, u64, String), u64> {
    values
        .iter()
        .map(|value| {
            (
                (value.kind.clone(), value.owner_id, value.key.clone()),
                value.value,
            )
        })
        .collect()
}

fn decision_projection(decisions: &[IntentDecision]) -> Vec<Value> {
    decisions
        .iter()
        .map(|decision| {
            json!({
                "input_id": decision.intent.input_id,
                "accepted": decision.accepted,
                "reason": decision.reason,
            })
        })
        .collect()
}

#[test]
fn independent_arbitration_matches_shared_atomic_claim_and_allocation_vectors() {
    for case in vectors().cases {
        let initial = state(&case.state);
        let (actual, decisions) = arbitrate(&case.intents, &initial).unwrap();
        assert_eq!(
            decision_projection(&decisions),
            case.decisions,
            "{}",
            case.id
        );
        assert_eq!(
            actual.resource_banks, case.expected_state.resource_banks,
            "{}",
            case.id
        );
        assert_eq!(
            actual.usages,
            capacity_map(&case.expected_state.usages),
            "{}",
            case.id
        );
        assert_eq!(
            actual.exclusive_keys,
            case.expected_state.exclusive_keys.into_iter().collect(),
            "{}",
            case.id
        );
        let (allocated, next_id) =
            allocate_action_instance_ids(&decisions, case.next_action_instance_id).unwrap();
        assert_eq!(allocated, case.allocated, "{}", case.id);
        assert_eq!(next_id, case.next_id, "{}", case.id);

        let mut reversed = case.intents.clone();
        reversed.reverse();
        let (permuted, permuted_decisions) = arbitrate(&reversed, &initial).unwrap();
        assert_eq!(permuted, actual, "{}:state permutation", case.id);
        assert_eq!(
            decision_projection(&permuted_decisions),
            decision_projection(&decisions),
            "{}:decision permutation",
            case.id
        );
    }
}

#[test]
fn independent_claim_deserialization_rejects_negative_amounts() {
    assert!(
        serde_json::from_value::<Claim>(json!({
            "kind": "RESOURCE",
            "key": "STAMINA",
            "amount": -1
        }))
        .is_err()
    );
}
