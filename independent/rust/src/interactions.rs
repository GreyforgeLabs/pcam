use crate::effects::EffectEnvelope;
use crate::expression::{EvalError, evaluate};
use crate::numeric::{NumericError, scale_ratio};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

const STAGES: [&str; 5] = [
    "ADMISSION",
    "ROUTING",
    "MODIFICATION",
    "MATERIALIZATION",
    "REACTION",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InteractionError {
    DefinitionRejected,
    DivisionByZero,
    IntegerOverflow,
    RedirectLimitExceeded,
    StateInvariant,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct EffectTemplate {
    pub effect_type: String,
    pub effect_class: String,
    pub payload: Value,
    #[serde(default = "ordered_reducer")]
    pub reducer: String,
    #[serde(default)]
    pub priority: i64,
    #[serde(default = "enabled")]
    pub authoritative: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct SemanticFact {
    pub fact_id: String,
    pub direction: String,
    #[serde(default)]
    pub channels: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub attributes: BTreeMap<String, Value>,
    #[serde(default)]
    pub effect_templates: Vec<EffectTemplate>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct InteractionCandidate {
    pub tick: u64,
    pub candidate_id: String,
    pub source_entity_id: u64,
    pub target_entity_id: u64,
    pub source_action_instance_id: u64,
    pub offense_fact_id: String,
    pub contact_id: String,
    #[serde(default = "default_partition")]
    pub contact_partition: String,
    #[serde(default)]
    pub host_context: BTreeMap<String, Value>,
    #[serde(default)]
    pub defense_fact_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct RuleOperation {
    pub op: String,
    #[serde(default)]
    pub data: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct InteractionRule {
    pub rule_id: String,
    pub stage: String,
    pub order: i64,
    pub condition: Value,
    pub operations: Vec<RuleOperation>,
    #[serde(default)]
    pub stop_stage: bool,
    #[serde(default)]
    pub stop_pipeline: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TraceEntry {
    pub rule_id: String,
    pub stage: String,
    pub order: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InteractionDecision {
    pub candidate_id: String,
    pub status: String,
    pub current_target: u64,
    pub active_effect_templates: Vec<EffectTemplate>,
    pub decision_tags: Vec<String>,
    pub generated_effects: Vec<EffectEnvelope>,
    pub receipt_requests: Vec<String>,
    pub redirect_count: u64,
    pub visited_targets: Vec<u64>,
    pub trace: Vec<TraceEntry>,
}

pub fn canonical_candidates(candidates: &[InteractionCandidate]) -> Vec<InteractionCandidate> {
    let mut ordered = candidates.to_vec();
    ordered.sort_by(|left, right| {
        left.source_entity_id
            .cmp(&right.source_entity_id)
            .then_with(|| left.target_entity_id.cmp(&right.target_entity_id))
            .then_with(|| {
                left.source_action_instance_id
                    .cmp(&right.source_action_instance_id)
            })
            .then_with(|| {
                left.offense_fact_id
                    .as_bytes()
                    .cmp(right.offense_fact_id.as_bytes())
            })
            .then_with(|| {
                left.defense_fact_id
                    .as_deref()
                    .unwrap_or("")
                    .as_bytes()
                    .cmp(right.defense_fact_id.as_deref().unwrap_or("").as_bytes())
            })
            .then_with(|| {
                left.contact_partition
                    .as_bytes()
                    .cmp(right.contact_partition.as_bytes())
            })
            .then_with(|| left.contact_id.as_bytes().cmp(right.contact_id.as_bytes()))
            .then_with(|| {
                left.candidate_id
                    .as_bytes()
                    .cmp(right.candidate_id.as_bytes())
            })
    });
    ordered
}

pub fn resolve_candidate(
    candidate: &InteractionCandidate,
    offense: &SemanticFact,
    defense_by_target: &BTreeMap<u64, Option<SemanticFact>>,
    rules: &[InteractionRule],
    max_redirects: u64,
    redirect_limit_policy: &str,
    max_expression_depth: usize,
    max_expression_nodes: usize,
) -> Result<InteractionDecision, InteractionError> {
    let mut seen = BTreeSet::new();
    let mut ordered_rules = Vec::with_capacity(rules.len());
    for rule in rules {
        let stage = stage_rank(&rule.stage)?;
        if !seen.insert((stage, rule.order)) {
            return Err(InteractionError::DefinitionRejected);
        }
        ordered_rules.push((stage, rule.clone()));
    }
    ordered_rules.sort_by(|left, right| {
        left.0
            .cmp(&right.0)
            .then_with(|| left.1.order.cmp(&right.1.order))
    });

    let mut status = "ACCEPTED".to_owned();
    let mut current_target = candidate.target_entity_id;
    let mut templates = offense.effect_templates.clone();
    let mut tags = BTreeSet::new();
    let mut generated = Vec::new();
    let mut receipts = Vec::new();
    let mut redirect_count = 0_u64;
    let mut visited = vec![current_target];
    let mut trace = Vec::new();
    let mut restart = true;
    let mut pipeline_stopped = false;

    while restart && !pipeline_stopped {
        restart = false;
        let defense = defense_by_target
            .get(&current_target)
            .and_then(Option::as_ref);
        for (stage_index, stage_name) in STAGES.iter().enumerate() {
            let mut stop_stage = false;
            for (_, rule) in ordered_rules
                .iter()
                .filter(|(rank, _)| *rank == stage_index)
            {
                let context = interaction_context(
                    candidate,
                    current_target,
                    offense,
                    defense,
                    &status,
                    &tags,
                );
                let condition = evaluate(
                    &rule.condition,
                    &context,
                    max_expression_depth,
                    max_expression_nodes,
                )
                .map_err(map_eval)?;
                if condition != Value::Bool(true) {
                    continue;
                }
                trace.push(TraceEntry {
                    rule_id: rule.rule_id.clone(),
                    stage: (*stage_name).to_owned(),
                    order: rule.order,
                });
                for (operation_index, operation) in rule.operations.iter().enumerate() {
                    match operation.op.as_str() {
                        "REJECT" => {
                            status = "REJECTED".to_owned();
                            tags.insert(string_or_default(&operation.data, "reason", "REJECTED")?);
                        }
                        "REDIRECT" => {
                            let target = required_u64(&operation.data, "target_entity_id")?;
                            if visited.contains(&target) || redirect_count >= max_redirects {
                                if redirect_limit_policy == "REJECT" {
                                    status = "REJECTED".to_owned();
                                    tags.insert("REDIRECT_LIMIT_EXCEEDED".to_owned());
                                    pipeline_stopped = true;
                                    break;
                                }
                                return Err(InteractionError::RedirectLimitExceeded);
                            }
                            current_target = target;
                            visited.push(target);
                            redirect_count += 1;
                            restart = true;
                            stop_stage = true;
                            break;
                        }
                        "REMOVE_EFFECT_CLASS" => {
                            let class = required_string(&operation.data, "effect_class")?;
                            templates.retain(|item| item.effect_class != class);
                        }
                        "SCALE_EFFECT_CLASS" => {
                            let class = required_string(&operation.data, "effect_class")?;
                            let numerator = required_i64(&operation.data, "numerator")?;
                            let denominator = required_i64(&operation.data, "denominator")?;
                            if denominator <= 0 {
                                return Err(if denominator == 0 {
                                    InteractionError::DivisionByZero
                                } else {
                                    InteractionError::StateInvariant
                                });
                            }
                            for template in templates
                                .iter_mut()
                                .filter(|item| item.effect_class == class)
                            {
                                let payload = template
                                    .payload
                                    .as_i64()
                                    .ok_or(InteractionError::StateInvariant)?;
                                template.payload = Value::from(
                                    scale_ratio(payload, numerator, denominator as u64)
                                        .map_err(map_numeric)?,
                                );
                            }
                        }
                        "CAP_EFFECT_CLASS" => {
                            let class = required_string(&operation.data, "effect_class")?;
                            let cap = required_i64(&operation.data, "cap")?;
                            for template in templates
                                .iter_mut()
                                .filter(|item| item.effect_class == class)
                            {
                                let payload = template
                                    .payload
                                    .as_i64()
                                    .ok_or(InteractionError::StateInvariant)?;
                                template.payload = Value::from(payload.min(cap));
                            }
                        }
                        "REPLACE_EFFECT_CLASS" => {
                            let class = required_string(&operation.data, "effect_class")?;
                            let replacement: EffectTemplate = serde_json::from_value(
                                operation
                                    .data
                                    .get("replacement")
                                    .cloned()
                                    .ok_or(InteractionError::StateInvariant)?,
                            )
                            .map_err(|_| InteractionError::StateInvariant)?;
                            for template in templates
                                .iter_mut()
                                .filter(|item| item.effect_class == class)
                            {
                                *template = replacement.clone();
                            }
                        }
                        "APPEND_EFFECT_TEMPLATE" => {
                            let mut template: EffectTemplate = serde_json::from_value(
                                operation
                                    .data
                                    .get("template")
                                    .cloned()
                                    .ok_or(InteractionError::StateInvariant)?,
                            )
                            .map_err(|_| InteractionError::StateInvariant)?;
                            template.payload = resolve_payload(
                                &template.payload,
                                &context,
                                max_expression_depth,
                                max_expression_nodes,
                            )?;
                            templates.push(template);
                        }
                        "ADD_DECISION_TAG" => {
                            tags.insert(required_string(&operation.data, "tag")?);
                        }
                        "REQUEST_RECEIPT" => {
                            receipts.push(required_string(&operation.data, "condition")?);
                        }
                        "MATERIALIZE" => {
                            let statuses = materialize_list(
                                operation.data.get("statuses"),
                                &["ACCEPTED"],
                                false,
                            )?;
                            if statuses
                                .iter()
                                .any(|item| item != "ACCEPTED" && item != "REJECTED")
                            {
                                return Err(InteractionError::StateInvariant);
                            }
                            let effect_classes =
                                materialize_list(operation.data.get("effect_classes"), &[], true)?;
                            let selected: Vec<_> = templates
                                .iter()
                                .filter(|item| {
                                    effect_classes.is_empty()
                                        || effect_classes.contains(&item.effect_class)
                                })
                                .cloned()
                                .collect();
                            if status == "REJECTED"
                                && statuses.contains(&status)
                                && (effect_classes.is_empty()
                                    || selected.iter().any(|item| item.effect_class != "REACTION"))
                            {
                                return Err(InteractionError::StateInvariant);
                            }
                            if statuses.contains(&status) {
                                generated.extend(materialize(
                                    candidate,
                                    current_target,
                                    &selected,
                                    &rule.rule_id,
                                    operation_index,
                                ));
                            }
                        }
                        "STOP_STAGE" => {
                            stop_stage = true;
                            break;
                        }
                        "STOP_PIPELINE" => {
                            pipeline_stopped = true;
                            break;
                        }
                        _ => return Err(InteractionError::StateInvariant),
                    }
                }
                if restart || pipeline_stopped {
                    break;
                }
                if rule.stop_pipeline {
                    pipeline_stopped = true;
                    break;
                }
                if rule.stop_stage {
                    stop_stage = true;
                }
                if stop_stage {
                    break;
                }
            }
            if restart || pipeline_stopped {
                break;
            }
        }
    }

    Ok(InteractionDecision {
        candidate_id: candidate.candidate_id.clone(),
        status,
        current_target,
        active_effect_templates: templates,
        decision_tags: tags.into_iter().collect(),
        generated_effects: generated,
        receipt_requests: receipts,
        redirect_count,
        visited_targets: visited,
        trace,
    })
}

fn stage_rank(stage: &str) -> Result<usize, InteractionError> {
    STAGES
        .iter()
        .position(|item| *item == stage)
        .ok_or(InteractionError::DefinitionRejected)
}

fn interaction_context(
    candidate: &InteractionCandidate,
    current_target: u64,
    offense: &SemanticFact,
    defense: Option<&SemanticFact>,
    status: &str,
    tags: &BTreeSet<String>,
) -> BTreeMap<String, Value> {
    let mut context = BTreeMap::new();
    context.insert(
        "candidate.candidate_id".to_owned(),
        Value::String(candidate.candidate_id.clone()),
    );
    context.insert(
        "candidate.source_entity_id".to_owned(),
        Value::from(candidate.source_entity_id),
    );
    context.insert(
        "candidate.target_entity_id".to_owned(),
        Value::from(current_target),
    );
    context.insert(
        "candidate.source_action_instance_id".to_owned(),
        Value::from(candidate.source_action_instance_id),
    );
    context.insert(
        "candidate.offense_fact_id".to_owned(),
        Value::String(candidate.offense_fact_id.clone()),
    );
    context.insert(
        "candidate.defense_fact_id".to_owned(),
        candidate
            .defense_fact_id
            .as_ref()
            .map_or(Value::Null, |value| Value::String(value.clone())),
    );
    context.insert("offense.channels".to_owned(), strings(&offense.channels));
    context.insert("offense.tags".to_owned(), strings(&offense.tags));
    context.insert(
        "offense.fact_id".to_owned(),
        Value::String(offense.fact_id.clone()),
    );
    context.insert(
        "defense.channels".to_owned(),
        strings(defense.map_or(&[], |item| item.channels.as_slice())),
    );
    context.insert(
        "defense.tags".to_owned(),
        strings(defense.map_or(&[], |item| item.tags.as_slice())),
    );
    context.insert(
        "defense.fact_id".to_owned(),
        defense.map_or(Value::Null, |item| Value::String(item.fact_id.clone())),
    );
    context.insert(
        "target.lifecycle".to_owned(),
        candidate
            .host_context
            .get("target.lifecycle")
            .cloned()
            .unwrap_or_else(|| Value::String("RUNNING".to_owned())),
    );
    context.insert(
        "decision.status".to_owned(),
        Value::String(status.to_owned()),
    );
    context.insert(
        "decision.tags".to_owned(),
        Value::Array(tags.iter().cloned().map(Value::String).collect()),
    );
    context
}

fn resolve_payload(
    payload: &Value,
    context: &BTreeMap<String, Value>,
    max_depth: usize,
    max_nodes: usize,
) -> Result<Value, InteractionError> {
    match payload {
        Value::Object(object) if expression_shape(object) => {
            evaluate(payload, context, max_depth, max_nodes).map_err(map_eval)
        }
        Value::Object(object) => object
            .iter()
            .map(|(key, value)| {
                Ok((
                    key.clone(),
                    resolve_payload(value, context, max_depth, max_nodes)?,
                ))
            })
            .collect::<Result<Map<_, _>, _>>()
            .map(Value::Object),
        Value::Array(items) => items
            .iter()
            .map(|item| resolve_payload(item, context, max_depth, max_nodes))
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        _ => Ok(payload.clone()),
    }
}

fn expression_shape(object: &Map<String, Value>) -> bool {
    (object.len() == 1 && (object.contains_key("literal") || object.contains_key("ref")))
        || (object.len() == 2 && object.contains_key("op") && object.contains_key("args"))
}

fn materialize(
    candidate: &InteractionCandidate,
    current_target: u64,
    templates: &[EffectTemplate],
    rule_id: &str,
    operation_index: usize,
) -> Vec<EffectEnvelope> {
    templates
        .iter()
        .enumerate()
        .map(|(index, template)| EffectEnvelope {
            effect_id: format!(
                "{}:{}:{}:{}:{}:{}",
                candidate.tick,
                candidate.source_action_instance_id,
                candidate.candidate_id,
                rule_id,
                operation_index,
                index
            ),
            effect_type: template.effect_type.clone(),
            effect_class: template.effect_class.clone(),
            source_entity_id: candidate.source_entity_id,
            target_entity_id: current_target,
            source_action_instance_id: candidate.source_action_instance_id,
            origin_tick: candidate.tick,
            priority: template.priority,
            payload: template.payload.clone(),
            reducer: template.reducer.clone(),
            authoritative: template.authoritative,
        })
        .collect()
}

fn materialize_list(
    value: Option<&Value>,
    default: &[&str],
    allow_empty: bool,
) -> Result<Vec<String>, InteractionError> {
    let values = match value {
        Some(value) => value.as_array().ok_or(InteractionError::StateInvariant)?,
        None => {
            return Ok(default.iter().map(|item| (*item).to_owned()).collect());
        }
    };
    if (!allow_empty && values.is_empty())
        || values
            .iter()
            .any(|item| item.as_str().is_none_or(str::is_empty))
    {
        return Err(InteractionError::StateInvariant);
    }
    let items: Vec<String> = values
        .iter()
        .map(|item| item.as_str().unwrap().to_owned())
        .collect();
    if items.iter().collect::<BTreeSet<_>>().len() != items.len() {
        return Err(InteractionError::StateInvariant);
    }
    Ok(items)
}

fn required_string(data: &Map<String, Value>, key: &str) -> Result<String, InteractionError> {
    data.get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or(InteractionError::StateInvariant)
}

fn string_or_default(
    data: &Map<String, Value>,
    key: &str,
    default: &str,
) -> Result<String, InteractionError> {
    match data.get(key) {
        Some(value) => value
            .as_str()
            .map(str::to_owned)
            .ok_or(InteractionError::StateInvariant),
        None => Ok(default.to_owned()),
    }
}

fn required_i64(data: &Map<String, Value>, key: &str) -> Result<i64, InteractionError> {
    data.get(key)
        .and_then(Value::as_i64)
        .ok_or(InteractionError::StateInvariant)
}

fn required_u64(data: &Map<String, Value>, key: &str) -> Result<u64, InteractionError> {
    data.get(key)
        .and_then(Value::as_u64)
        .ok_or(InteractionError::StateInvariant)
}

fn strings(values: &[String]) -> Value {
    Value::Array(values.iter().cloned().map(Value::String).collect())
}

fn map_numeric(error: NumericError) -> InteractionError {
    match error {
        NumericError::DivisionByZero => InteractionError::DivisionByZero,
        NumericError::IntegerOverflow => InteractionError::IntegerOverflow,
        NumericError::InvalidDivisor => InteractionError::StateInvariant,
    }
}

fn map_eval(error: EvalError) -> InteractionError {
    match error {
        EvalError::DivisionByZero => InteractionError::DivisionByZero,
        EvalError::IntegerOverflow => InteractionError::IntegerOverflow,
        EvalError::StateInvariant => InteractionError::StateInvariant,
    }
}

fn ordered_reducer() -> String {
    "ORDERED".to_owned()
}

fn default_partition() -> String {
    "default".to_owned()
}

fn enabled() -> bool {
    true
}
