use pcam_independent::numeric::{
    NumericError, OverflowPolicy, apply_i64, apply_u64, euclidean_divmod, scale_ratio,
};
use pcam_independent::rng::{Pcg32Stream, RngError};
use serde::Deserialize;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    overflow_cases: Vec<OverflowCase>,
    division_cases: Vec<DivisionCase>,
    ratio_cases: Vec<RatioCase>,
    pcg32: PcgVector,
}

#[derive(Deserialize)]
struct OverflowCase {
    id: String,
    domain: String,
    input: String,
    policy: String,
    result: Option<i64>,
    fault: Option<String>,
}

#[derive(Deserialize)]
struct DivisionCase {
    id: String,
    dividend: i64,
    divisor: i64,
    quotient: Option<i64>,
    remainder: Option<i64>,
    fault: Option<String>,
}

#[derive(Deserialize)]
struct RatioCase {
    id: String,
    value: i64,
    numerator: i64,
    denominator: u64,
    result: Option<i64>,
    fault: Option<String>,
}

#[derive(Deserialize)]
struct PcgVector {
    seed: u64,
    stream_selector: u64,
    values: Vec<u32>,
    snapshot: Pcg32Stream,
    next_value: u32,
    next_state: u64,
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn vectors() -> VectorFile {
    let source = fs::read(repository_root().join("tests/vectors/numeric-rng.json"))
        .expect("shared numeric and RNG vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn policy(value: &str) -> OverflowPolicy {
    match value {
        "FAULT" => OverflowPolicy::Fault,
        "SATURATE" => OverflowPolicy::Saturate,
        "WRAP" => OverflowPolicy::Wrap,
        _ => panic!("unknown policy: {value}"),
    }
}

fn fault_code(error: NumericError) -> &'static str {
    match error {
        NumericError::IntegerOverflow => "INTEGER_OVERFLOW",
        NumericError::DivisionByZero => "DIVISION_BY_ZERO",
        NumericError::InvalidDivisor => "STATE_INVARIANT_FAILURE",
    }
}

#[test]
fn independent_numeric_semantics_match_shared_vectors() {
    let vectors = vectors();
    for case in vectors.overflow_cases {
        let value = case.input.parse::<i128>().expect("i128 input");
        let actual = match case.domain.as_str() {
            "I64" => apply_i64(value, policy(&case.policy)).map(|item| item as i128),
            "U64" => apply_u64(value, policy(&case.policy)).map(|item| item as i128),
            _ => panic!("unknown domain: {}", case.domain),
        };
        match (case.result, case.fault) {
            (Some(expected), None) => assert_eq!(actual.unwrap(), expected as i128, "{}", case.id),
            (None, Some(expected)) => {
                assert_eq!(fault_code(actual.unwrap_err()), expected, "{}", case.id)
            }
            _ => panic!("invalid vector case: {}", case.id),
        }
    }

    for case in vectors.division_cases {
        let actual = euclidean_divmod(case.dividend, case.divisor);
        if let Some(expected) = case.fault {
            assert_eq!(fault_code(actual.unwrap_err()), expected, "{}", case.id);
        } else {
            assert_eq!(
                actual.unwrap(),
                (case.quotient.unwrap(), case.remainder.unwrap()),
                "{}",
                case.id
            );
        }
    }

    for case in vectors.ratio_cases {
        let actual = scale_ratio(case.value, case.numerator, case.denominator);
        if let Some(expected) = case.fault {
            assert_eq!(fault_code(actual.unwrap_err()), expected, "{}", case.id);
        } else {
            assert_eq!(actual.unwrap(), case.result.unwrap(), "{}", case.id);
        }
    }
}

#[test]
fn independent_pcg32_matches_shared_outputs_and_restore_state() {
    let vector = vectors().pcg32;
    let mut stream = Pcg32Stream::seeded(vector.seed, vector.stream_selector);
    let values: Vec<_> = (0..vector.values.len())
        .map(|_| stream.draw_u32().unwrap())
        .collect();
    assert_eq!(values, vector.values);
    assert_eq!(stream, vector.snapshot);

    let mut restored = Pcg32Stream::from_snapshot(stream.clone()).unwrap();
    assert_eq!(restored.draw_u32().unwrap(), vector.next_value);
    assert_eq!(restored.state, vector.next_state);
    assert_eq!(restored.draw_count, 6);
}

#[test]
fn independent_pcg32_rejects_profile_mismatch_and_draw_count_overflow() {
    let mut profile_mismatch = Pcg32Stream::seeded(42, 54);
    profile_mismatch.algorithm_id = "pcam.unknown".to_owned();
    assert_eq!(
        Pcg32Stream::from_snapshot(profile_mismatch).unwrap_err(),
        RngError::ProfileMismatch
    );

    let mut exhausted = Pcg32Stream {
        algorithm_id: "pcam.pcg32.v1".to_owned(),
        draw_count: u64::MAX,
        state: 1,
        stream_selector: 1,
    };
    assert_eq!(
        exhausted.draw_u32().unwrap_err(),
        RngError::DrawCountOverflow
    );
}
