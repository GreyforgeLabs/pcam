use pcam_independent::expression::{EvalError, evaluate};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;
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
    expression: Value,
    context: BTreeMap<String, Value>,
    result: Value,
}

#[derive(Deserialize)]
struct FaultCase {
    id: String,
    expression: Value,
    context: BTreeMap<String, Value>,
    fault: String,
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn vectors() -> VectorFile {
    let source = fs::read(repository_root().join("tests/vectors/expressions.json"))
        .expect("shared expression vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn fault_code(error: EvalError) -> &'static str {
    match error {
        EvalError::DivisionByZero => "DIVISION_BY_ZERO",
        EvalError::IntegerOverflow => "INTEGER_OVERFLOW",
        EvalError::StateInvariant => "STATE_INVARIANT_FAILURE",
    }
}

#[test]
fn independent_expression_evaluator_matches_shared_vectors() {
    let vectors = vectors();
    for case in vectors.cases {
        assert_eq!(
            evaluate(&case.expression, &case.context, 64, 4096).unwrap(),
            case.result,
            "{}",
            case.id
        );
    }
    for case in vectors.fault_cases {
        assert_eq!(
            fault_code(evaluate(&case.expression, &case.context, 64, 4096).unwrap_err()),
            case.fault,
            "{}",
            case.id
        );
    }
}

#[test]
fn independent_expression_evaluator_enforces_depth_and_node_limits() {
    let expression =
        serde_json::json!({"op":"not","args":[{"op":"not","args":[{"literal":true}]}]});
    assert_eq!(
        evaluate(&expression, &BTreeMap::new(), 1, 4096).unwrap_err(),
        EvalError::StateInvariant
    );
    assert_eq!(
        evaluate(&expression, &BTreeMap::new(), 64, 2).unwrap_err(),
        EvalError::StateInvariant
    );
}
