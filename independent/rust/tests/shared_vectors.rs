use pcam_independent::{canonical_hash, canonical_hash_json, canonicalize};
use serde::Deserialize;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
    definition_case: DefinitionCase,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    input: Value,
    canonical: String,
    sha256: String,
}

#[derive(Deserialize)]
struct DefinitionCase {
    path: String,
    sha256: String,
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn independent_implementation_matches_shared_pcam_cj1_vectors() {
    let root = repository_root();
    let source = fs::read(root.join("tests/vectors/pcam-cj1.json")).expect("shared vector");
    let vectors: VectorFile = serde_json::from_slice(&source).expect("vector JSON");
    for case in vectors.cases {
        assert_eq!(
            String::from_utf8(canonicalize(&case.input).unwrap()).unwrap(),
            case.canonical,
            "{}",
            case.id
        );
        assert_eq!(
            canonical_hash(&case.input).unwrap(),
            case.sha256,
            "{}",
            case.id
        );
    }
    let definition = fs::read(root.join(vectors.definition_case.path)).expect("definition vector");
    assert_eq!(
        canonical_hash_json(&definition).unwrap(),
        vectors.definition_case.sha256
    );
}

#[test]
fn independent_implementation_rejects_floating_point() {
    let value: Value = serde_json::from_str("{\"bad\":1.5}").unwrap();
    assert!(canonicalize(&value).is_err());
}

#[test]
fn independent_implementation_rejects_normalized_key_collisions() {
    let value: Value = serde_json::from_str("{\"e\\u0301\":1,\"é\":2}").unwrap();
    assert!(canonicalize(&value).is_err());
}
