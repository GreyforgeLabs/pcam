use pcam_independent::canonical_hash;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/full-definition-hashes.json"))
        .expect("shared full-definition hash vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn set_path(document: &mut Value, path: &[Value], value: Value) {
    let mut target = document;
    for part in &path[..path.len() - 1] {
        target = if let Some(key) = part.as_str() {
            &mut target[key]
        } else {
            &mut target[part.as_u64().unwrap() as usize]
        };
    }
    let last = &path[path.len() - 1];
    if let Some(key) = last.as_str() {
        target[key] = value;
    } else {
        target[last.as_u64().unwrap() as usize] = value;
    }
}

#[test]
fn independent_full_definition_base_and_every_field_mutation_match_shared_hashes() {
    let vector = vector();
    let base = &vector["base_document"];
    let base_hash = canonical_hash(base).unwrap();
    assert_eq!(base_hash, vector["expected"]["base_sha256"]);

    let mut mutation_hashes = Vec::new();
    for case in vector["mutations"].as_array().unwrap() {
        let mut document = base.clone();
        set_path(
            &mut document,
            case["path"].as_array().unwrap(),
            case["value"].clone(),
        );
        let digest = canonical_hash(&document).unwrap();
        assert_ne!(digest, base_hash, "{}", case["id"]);
        mutation_hashes.push(json!({"id": case["id"], "sha256": digest}));
    }
    assert_eq!(
        canonical_hash(&Value::Array(mutation_hashes)).unwrap(),
        vector["expected"]["mutation_hashes_sha256"]
    );
}
