use pcam_independent::freezes::{FreezeError, FreezeToken, add_token};
use serde::Deserialize;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    tokens: Vec<FreezeToken>,
    incoming: FreezeToken,
    expected: Option<Value>,
    fault: Option<String>,
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source = fs::read(root.join("tests/vectors/freeze-stacking.json"))
        .expect("shared freeze stacking vectors");
    serde_json::from_slice(&source).expect("freeze stacking JSON")
}

#[test]
fn independent_freeze_stacking_matches_shared_vectors() {
    for case in vectors().cases {
        match add_token(&case.tokens, case.incoming) {
            Ok(tokens) => {
                assert!(case.fault.is_none(), "{}:unexpected-success", case.id);
                assert_eq!(
                    serde_json::to_value(tokens).unwrap(),
                    case.expected.unwrap(),
                    "{}",
                    case.id
                );
            }
            Err(error) => {
                assert_eq!(error, FreezeError::InvalidToken, "{}", case.id);
                assert_eq!(case.fault.as_deref(), Some("STATE_INVARIANT_FAILURE"));
            }
        }
    }
}
