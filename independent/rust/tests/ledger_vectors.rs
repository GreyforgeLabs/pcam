use pcam_independent::ledger::{
    HitPolicy, LedgerContext, is_eligible, ledger_key, receipt_required, write_receipt,
};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/ledgers.json")).expect("shared ledger vectors");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn context(base: &Value, overrides: &Value) -> LedgerContext {
    let mut values = base.as_object().unwrap().clone();
    values.extend(overrides.as_object().unwrap().clone());
    LedgerContext {
        tick: values["tick"].as_u64().unwrap(),
        source_action_instance_id: values["source_action_instance_id"].as_u64().unwrap(),
        offense_fact_id: values["offense_fact_id"].as_str().unwrap().to_owned(),
        target_entity_id: values["target_entity_id"].as_u64().unwrap(),
        cycle: values["cycle"].as_u64().unwrap(),
        predicate_entry_serials: values["predicate_entry_serials"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(key, value)| (key.clone(), value.as_u64().unwrap()))
            .collect(),
        contact_partition: values["contact_partition"].as_str().unwrap().to_owned(),
    }
}

#[test]
fn independent_ledger_policies_match_shared_sequential_vectors() {
    let vector = vector();
    for case in vector["cases"].as_array().unwrap() {
        let policy: HitPolicy = serde_json::from_value(case["policy"].clone()).unwrap();
        let mut ledger = BTreeMap::new();
        for (index, step) in case["steps"].as_array().unwrap().iter().enumerate() {
            let context = context(&vector["base_context"], &step["context"]);
            assert_eq!(
                serde_json::to_value(ledger_key(&policy, &context).unwrap()).unwrap(),
                step["key"],
                "{}:{index}:key",
                case["id"]
            );
            let eligible = is_eligible(&ledger, &policy, &context).unwrap();
            assert_eq!(eligible, step["eligible"].as_bool().unwrap());
            let mut written = false;
            if step["write"].as_bool().unwrap() && eligible {
                written = write_receipt(
                    &mut ledger,
                    &policy,
                    &context,
                    &format!("{}-{index}", case["id"].as_str().unwrap()),
                )
                .unwrap();
            }
            assert_eq!(written, step["receipt_written"].as_bool().unwrap());
            assert_eq!(ledger.len() as u64, step["ledger_count"].as_u64().unwrap());
        }
    }
}

#[test]
fn independent_receipt_conditions_match_shared_truth_table() {
    for case in vector()["receipt_conditions"].as_array().unwrap() {
        assert_eq!(
            receipt_required(
                case["condition"].as_str().unwrap(),
                case["accepted"].as_bool().unwrap(),
                case["impact"].as_bool().unwrap(),
            )
            .unwrap(),
            case["required"].as_bool().unwrap()
        );
    }
}

#[test]
fn independent_rejects_shared_invalid_ledger_policies() {
    for raw in vector()["invalid_policies"].as_array().unwrap() {
        let policy: HitPolicy = serde_json::from_value(raw.clone()).unwrap();
        assert!(policy.validate().is_err());
    }
}
