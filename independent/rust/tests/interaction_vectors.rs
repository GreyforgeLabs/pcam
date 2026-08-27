use pcam_independent::canonical_hash;
use pcam_independent::interactions::{
    InteractionCandidate, InteractionError, InteractionRule, SemanticFact, canonical_candidates,
    resolve_candidate,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

#[derive(Deserialize)]
struct VectorFile {
    canonical_candidate_order: CandidateOrder,
    cases: Vec<Case>,
    fault_cases: Vec<FaultCase>,
}

#[derive(Deserialize)]
struct CandidateOrder {
    candidates: Vec<InteractionCandidate>,
    candidate_ids: Vec<String>,
}

#[derive(Deserialize)]
struct Case {
    id: String,
    candidate: InteractionCandidate,
    offense: SemanticFact,
    defense_by_target: BTreeMap<String, Option<SemanticFact>>,
    rules: Vec<InteractionRule>,
    #[serde(default)]
    options: Options,
    decision_sha256: String,
    expected: Value,
}

#[derive(Deserialize)]
struct FaultCase {
    id: String,
    candidate: InteractionCandidate,
    offense: SemanticFact,
    defense_by_target: BTreeMap<String, Option<SemanticFact>>,
    rules: Vec<InteractionRule>,
    #[serde(default)]
    options: Options,
    fault: String,
}

#[derive(Deserialize)]
struct Options {
    #[serde(default = "default_redirects")]
    max_redirects: u64,
    #[serde(default = "default_policy")]
    redirect_limit_policy: String,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            max_redirects: default_redirects(),
            redirect_limit_policy: default_policy(),
        }
    }
}

fn vectors() -> VectorFile {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source =
        fs::read(root.join("tests/vectors/interactions.json")).expect("shared interaction vector");
    serde_json::from_slice(&source).expect("vector JSON")
}

fn defense_map(
    values: BTreeMap<String, Option<SemanticFact>>,
) -> BTreeMap<u64, Option<SemanticFact>> {
    values
        .into_iter()
        .map(|(target, fact)| (target.parse().expect("numeric entity id"), fact))
        .collect()
}

fn fault_code(error: InteractionError) -> &'static str {
    match error {
        InteractionError::DefinitionRejected => "DEFINITION_REJECTED",
        InteractionError::DivisionByZero => "DIVISION_BY_ZERO",
        InteractionError::IntegerOverflow => "INTEGER_OVERFLOW",
        InteractionError::RedirectLimitExceeded => "REDIRECT_LIMIT_EXCEEDED",
        InteractionError::StateInvariant => "STATE_INVARIANT_FAILURE",
    }
}

#[test]
fn independent_interaction_resolver_matches_shared_decision_records() {
    for case in vectors().cases {
        let decision = resolve_candidate(
            &case.candidate,
            &case.offense,
            &defense_map(case.defense_by_target),
            &case.rules,
            case.options.max_redirects,
            &case.options.redirect_limit_policy,
            64,
            4096,
        )
        .unwrap();
        let record = serde_json::to_value(&decision).unwrap();
        let summary = json!({
            "status": decision.status,
            "current_target": decision.current_target,
            "effect_classes": decision.active_effect_templates.iter().map(|item| item.effect_class.clone()).collect::<Vec<_>>(),
            "generated_effect_ids": decision.generated_effects.iter().map(|item| item.effect_id.clone()).collect::<Vec<_>>(),
            "decision_tags": decision.decision_tags,
            "receipt_requests": decision.receipt_requests,
            "redirect_count": decision.redirect_count,
            "visited_targets": decision.visited_targets,
            "trace_rule_ids": decision.trace.iter().map(|item| item.rule_id.clone()).collect::<Vec<_>>(),
        });
        assert_eq!(summary, case.expected, "{}:summary", case.id);
        assert_eq!(
            canonical_hash(&record).unwrap(),
            case.decision_sha256,
            "{}:decision",
            case.id
        );
    }
}

#[test]
fn independent_interaction_resolver_matches_shared_faults() {
    for case in vectors().fault_cases {
        let error = resolve_candidate(
            &case.candidate,
            &case.offense,
            &defense_map(case.defense_by_target),
            &case.rules,
            case.options.max_redirects,
            &case.options.redirect_limit_policy,
            64,
            4096,
        )
        .unwrap_err();
        assert_eq!(fault_code(error), case.fault, "{}", case.id);
    }
}

#[test]
fn independent_candidate_order_matches_shared_vector() {
    let order = vectors().canonical_candidate_order;
    let ids: Vec<_> = canonical_candidates(&order.candidates)
        .into_iter()
        .map(|item| item.candidate_id)
        .collect();
    assert_eq!(ids, order.candidate_ids);
}

fn default_redirects() -> u64 {
    8
}

fn default_policy() -> String {
    "FAULT".to_owned()
}
