use pcam_independent::{
    CanonicalError, canonical_hash, canonical_hash_json, canonicalize, canonicalize_json,
    canonicalize_logical_map, canonicalize_set,
};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn vector() -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/pcam-cj1-hostile.json"))
        .expect("shared hostile canonicalization vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn source(case: &Value) -> Vec<u8> {
    if let Some(encoded) = case.get("source_hex") {
        let text = encoded.as_str().unwrap();
        return text
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| {
                let pair = std::str::from_utf8(pair).unwrap();
                u8::from_str_radix(pair, 16).unwrap()
            })
            .collect();
    }
    case["source"].as_str().unwrap().as_bytes().to_vec()
}

fn assert_error(case: &Value, error: CanonicalError) {
    let expected = case["error"].as_str().unwrap();
    match expected {
        "NEGATIVE_ZERO" => assert_eq!(error, CanonicalError::NegativeZero),
        "FLOATING_POINT" => assert_eq!(error, CanonicalError::FloatingPoint),
        "INTEGER_DOMAIN" => assert!(matches!(
            error,
            CanonicalError::UnsupportedNumber | CanonicalError::Json(_)
        )),
        "KEY_COLLISION" => assert!(matches!(error, CanonicalError::NormalizedKeyCollision(_))),
        "SET_COLLISION" => assert_eq!(error, CanonicalError::NormalizedSetCollision),
        "LOGICAL_KEY_COLLISION" => {
            assert_eq!(error, CanonicalError::NormalizedLogicalKeyCollision)
        }
        "INVALID_JSON" => assert!(matches!(error, CanonicalError::Json(_))),
        other => panic!("unsupported expected error: {other}"),
    }
}

#[test]
fn independent_hostile_corpus_names_evidence_for_every_pcam_cj1_rule() {
    let vector = vector();
    let coverage = vector["rule_coverage"].as_object().unwrap();
    assert_eq!(coverage.len(), 18);
    for number in 1..=18 {
        let cases = coverage[&number.to_string()].as_array().unwrap();
        assert!(!cases.is_empty(), "rule {number}");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    for path in vector["external_evidence"].as_object().unwrap().values() {
        assert!(root.join(path.as_str().unwrap()).is_file());
    }
}

#[test]
fn independent_matches_hostile_exact_value_vectors() {
    let vector = vector();
    for case in vector["value_cases"].as_array().unwrap() {
        let actual = canonicalize(&case["input"]).unwrap();
        assert_eq!(
            actual,
            case["canonical"].as_str().unwrap().as_bytes(),
            "{}",
            case["id"]
        );
        assert_eq!(
            canonical_hash(&case["input"]).unwrap(),
            case["sha256"],
            "{}",
            case["id"]
        );
    }
}

#[test]
fn independent_raw_json_preserves_rejection_information_and_exact_bytes() {
    let vector = vector();
    for case in vector["raw_json_cases"].as_array().unwrap() {
        let source = source(case);
        if case["outcome"] == "OK" {
            let actual = canonicalize_json(&source).unwrap();
            assert_eq!(
                actual,
                case["canonical"].as_str().unwrap().as_bytes(),
                "{}",
                case["id"]
            );
            assert_eq!(
                canonical_hash_json(&source).unwrap(),
                case["sha256"],
                "{}",
                case["id"]
            );
        } else {
            assert_error(case, canonicalize_json(&source).unwrap_err());
        }
    }
}

#[test]
fn independent_native_sets_sort_canonically_and_reject_normalized_collisions() {
    let vector = vector();
    for case in vector["set_cases"].as_array().unwrap() {
        let items = case["items"].as_array().unwrap();
        if case["outcome"] == "OK" {
            let actual = canonicalize_set(items).unwrap();
            assert_eq!(
                actual,
                case["canonical"].as_str().unwrap().as_bytes(),
                "{}",
                case["id"]
            );
            assert_eq!(
                canonical_hash_json(&actual).unwrap(),
                case["sha256"],
                "{}",
                case["id"]
            );
        } else {
            assert_error(case, canonicalize_set(items).unwrap_err());
        }
    }
}

#[test]
fn independent_logical_maps_sort_canonically_and_reject_key_collisions() {
    let vector = vector();
    for case in vector["logical_map_cases"].as_array().unwrap() {
        let entries = case["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| {
                let pair = entry.as_array().unwrap();
                (pair[0].clone(), pair[1].clone())
            })
            .collect::<Vec<_>>();
        if case["outcome"] == "OK" {
            let actual = canonicalize_logical_map(&entries).unwrap();
            assert_eq!(
                actual,
                case["canonical"].as_str().unwrap().as_bytes(),
                "{}",
                case["id"]
            );
            assert_eq!(
                canonical_hash_json(&actual).unwrap(),
                case["sha256"],
                "{}",
                case["id"]
            );
        } else {
            assert_error(case, canonicalize_logical_map(&entries).unwrap_err());
        }
    }
}
