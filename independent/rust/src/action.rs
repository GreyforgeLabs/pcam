use crate::expression::{EvalError, evaluate};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActionError {
    IntegerOverflow,
    InvalidDefinition,
    QuantumLimitExceeded,
    StateInvariant,
    TransitionLimitExceeded,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Rate {
    pub scale: u64,
    pub units_per_tick: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NodeDefinition {
    pub id: String,
    #[serde(default = "event_driven")]
    pub mode: String,
    pub duration_quanta: Option<u64>,
    #[serde(default)]
    pub seekable: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TransitionDefinition {
    pub id: String,
    pub source_node: String,
    pub evaluation_point: String,
    pub priority: i64,
    #[serde(default = "node_target")]
    pub target_kind: String,
    pub target_node: Option<String>,
    #[serde(default)]
    pub target_step: u64,
    pub guard_expression: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PredicateDefinition {
    pub id: String,
    pub expression: Value,
    #[serde(default = "enabled")]
    pub track_edges: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ActionDefinition {
    pub id: String,
    pub rate: Rate,
    pub initial_node: String,
    pub nodes: Vec<NodeDefinition>,
    #[serde(default)]
    pub predicates: Vec<PredicateDefinition>,
    #[serde(default)]
    pub transitions: Vec<TransitionDefinition>,
}

#[derive(Debug, Clone, Copy)]
pub struct RuntimeLimits {
    pub max_quanta_per_action_per_tick: u64,
    pub max_internal_transitions_per_tick: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ActionInstance {
    pub lifecycle_state: String,
    pub current_node_id: String,
    pub node_step: u64,
    pub local_step: u64,
    pub cycle: u64,
    pub transition_serial: u64,
    pub quantum_accumulator: u64,
    pub current_rate_units: u64,
    pub predicate_truth_state: BTreeMap<String, bool>,
    pub predicate_entry_serials: BTreeMap<String, u64>,
    pub predicate_exit_serials: BTreeMap<String, u64>,
    pub fault_record: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TickResult {
    pub quanta: u64,
    pub transitions: Vec<String>,
}

pub fn validate_definition(definition: &ActionDefinition) -> Result<(), ActionError> {
    if definition.rate.scale == 0 || definition.nodes.is_empty() {
        return Err(ActionError::InvalidDefinition);
    }
    let nodes: BTreeMap<&str, &NodeDefinition> = definition
        .nodes
        .iter()
        .map(|node| (node.id.as_str(), node))
        .collect();
    if nodes.len() != definition.nodes.len()
        || !nodes.contains_key(definition.initial_node.as_str())
    {
        return Err(ActionError::InvalidDefinition);
    }
    for node in &definition.nodes {
        match node.mode.as_str() {
            "TIMED" if node.duration_quanta.is_none_or(|duration| duration == 0) => {
                return Err(ActionError::InvalidDefinition);
            }
            "TIMED" => {}
            "EVENT_DRIVEN" | "TERMINAL" if node.duration_quanta.is_none() => {}
            _ => return Err(ActionError::InvalidDefinition),
        }
    }
    let mut priorities = BTreeSet::new();
    for transition in &definition.transitions {
        if !nodes.contains_key(transition.source_node.as_str())
            || !matches!(
                transition.evaluation_point.as_str(),
                "PRE_ADVANCE" | "AFTER_QUANTUM" | "POST_ADVANCE"
            )
            || !priorities.insert((
                transition.source_node.as_str(),
                transition.evaluation_point.as_str(),
                transition.priority,
            ))
        {
            return Err(ActionError::InvalidDefinition);
        }
        if transition.target_kind == "NODE" {
            let target = transition
                .target_node
                .as_deref()
                .and_then(|target| nodes.get(target))
                .ok_or(ActionError::InvalidDefinition)?;
            if transition.target_step != 0 && !target.seekable {
                return Err(ActionError::InvalidDefinition);
            }
            if target.mode == "TIMED"
                && transition.target_step >= target.duration_quanta.unwrap_or_default()
            {
                return Err(ActionError::InvalidDefinition);
            }
        } else if !matches!(transition.target_kind.as_str(), "TERMINATE" | "FAULT") {
            return Err(ActionError::InvalidDefinition);
        }
    }
    validate_predicates(&definition.predicates)?;
    Ok(())
}

pub fn start(definition: &ActionDefinition) -> Result<ActionInstance, ActionError> {
    validate_definition(definition)?;
    let node = node(definition, &definition.initial_node)?;
    Ok(ActionInstance {
        lifecycle_state: if node.mode == "TERMINAL" {
            "TERMINATED".to_owned()
        } else {
            "RUNNING".to_owned()
        },
        current_node_id: definition.initial_node.clone(),
        node_step: 0,
        local_step: 0,
        cycle: 0,
        transition_serial: 0,
        quantum_accumulator: 0,
        current_rate_units: definition.rate.units_per_tick,
        predicate_truth_state: BTreeMap::new(),
        predicate_entry_serials: BTreeMap::new(),
        predicate_exit_serials: BTreeMap::new(),
        fault_record: None,
    })
}

pub fn tick(
    action: &mut ActionInstance,
    definition: &ActionDefinition,
    limits: RuntimeLimits,
    include_pre_advance: bool,
) -> Result<TickResult, ActionError> {
    if action.lifecycle_state != "RUNNING" {
        return Ok(TickResult {
            quanta: 0,
            transitions: Vec::new(),
        });
    }
    let mut applied = Vec::new();
    if include_pre_advance {
        apply_selected(action, definition, "PRE_ADVANCE", &mut applied)?;
    }
    if action.lifecycle_state != "RUNNING" {
        return Ok(TickResult {
            quanta: 0,
            transitions: applied,
        });
    }
    let accumulated = action
        .quantum_accumulator
        .checked_add(action.current_rate_units)
        .ok_or(ActionError::IntegerOverflow)?;
    let quanta = accumulated / definition.rate.scale;
    if quanta > limits.max_quanta_per_action_per_tick {
        return Err(ActionError::QuantumLimitExceeded);
    }
    action.quantum_accumulator = accumulated % definition.rate.scale;
    let mut internal_transitions = 0_u64;
    for _ in 0..quanta {
        if action.lifecycle_state != "RUNNING" {
            break;
        }
        let local_step = action
            .local_step
            .checked_add(1)
            .ok_or(ActionError::IntegerOverflow)?;
        let node_step = action
            .node_step
            .checked_add(1)
            .ok_or(ActionError::IntegerOverflow)?;
        action.local_step = local_step;
        action.node_step = node_step;
        if let Some(transition) = select(action, definition, "AFTER_QUANTUM")? {
            if internal_transitions >= limits.max_internal_transitions_per_tick {
                return Err(ActionError::TransitionLimitExceeded);
            }
            apply_transition(action, definition, transition)?;
            applied.push(transition.id.clone());
            internal_transitions = internal_transitions
                .checked_add(1)
                .ok_or(ActionError::IntegerOverflow)?;
        }
    }
    if action.lifecycle_state == "RUNNING" {
        apply_selected(action, definition, "POST_ADVANCE", &mut applied)?;
    }
    semantic_snapshot(action, definition)?;
    Ok(TickResult {
        quanta,
        transitions: applied,
    })
}

fn apply_selected(
    action: &mut ActionInstance,
    definition: &ActionDefinition,
    point: &str,
    applied: &mut Vec<String>,
) -> Result<bool, ActionError> {
    let Some(transition) = select(action, definition, point)? else {
        return Ok(false);
    };
    apply_transition(action, definition, transition)?;
    applied.push(transition.id.clone());
    Ok(true)
}

fn select<'a>(
    action: &ActionInstance,
    definition: &'a ActionDefinition,
    point: &str,
) -> Result<Option<&'a TransitionDefinition>, ActionError> {
    let mut eligible = definition
        .transitions
        .iter()
        .filter(|transition| {
            transition.source_node == action.current_node_id && transition.evaluation_point == point
        })
        .filter_map(|transition| match guard(action, transition) {
            Ok(true) => Some(Ok(transition)),
            Ok(false) => None,
            Err(error) => Some(Err(error)),
        })
        .collect::<Result<Vec<_>, _>>()?;
    eligible.sort_by_key(|transition| transition.priority);
    Ok(eligible.pop())
}

fn guard(action: &ActionInstance, transition: &TransitionDefinition) -> Result<bool, ActionError> {
    let Some(expression) = &transition.guard_expression else {
        return Ok(true);
    };
    let context = action_context(action);
    evaluate(expression, &context, 64, 4096)
        .map_err(map_expression)?
        .as_bool()
        .ok_or(ActionError::StateInvariant)
}

fn action_context(action: &ActionInstance) -> BTreeMap<String, Value> {
    let mut context = BTreeMap::from([
        ("action.lifecycle".to_owned(), json!(action.lifecycle_state)),
        ("action.node".to_owned(), json!(action.current_node_id)),
        ("action.node_step".to_owned(), json!(action.node_step)),
        ("action.local_step".to_owned(), json!(action.local_step)),
        ("action.cycle".to_owned(), json!(action.cycle)),
        (
            "action.transition_serial".to_owned(),
            json!(action.transition_serial),
        ),
    ]);
    for (predicate, truth) in &action.predicate_truth_state {
        context.insert(format!("action.predicate.{predicate}"), json!(truth));
    }
    context
}

fn semantic_snapshot(
    action: &mut ActionInstance,
    definition: &ActionDefinition,
) -> Result<(), ActionError> {
    let definitions: BTreeMap<&str, &PredicateDefinition> = definition
        .predicates
        .iter()
        .map(|predicate| (predicate.id.as_str(), predicate))
        .collect();
    let mut values = BTreeMap::new();
    let mut visiting = BTreeSet::new();
    let mut context = action_context(action);
    for identifier in definitions.keys() {
        evaluate_predicate(
            identifier,
            &definitions,
            &mut values,
            &mut visiting,
            &mut context,
        )?;
    }
    for predicate in &definition.predicates {
        let now = values[&predicate.id];
        let before = action
            .predicate_truth_state
            .get(&predicate.id)
            .copied()
            .unwrap_or(false);
        action
            .predicate_truth_state
            .insert(predicate.id.clone(), now);
        if predicate.track_edges && now != before {
            let serials = if now {
                &mut action.predicate_entry_serials
            } else {
                &mut action.predicate_exit_serials
            };
            let next = serials
                .get(&predicate.id)
                .copied()
                .unwrap_or(0)
                .checked_add(1)
                .ok_or(ActionError::IntegerOverflow)?;
            serials.insert(predicate.id.clone(), next);
        }
    }
    Ok(())
}

fn evaluate_predicate(
    identifier: &str,
    definitions: &BTreeMap<&str, &PredicateDefinition>,
    values: &mut BTreeMap<String, bool>,
    visiting: &mut BTreeSet<String>,
    context: &mut BTreeMap<String, Value>,
) -> Result<bool, ActionError> {
    if let Some(value) = values.get(identifier) {
        return Ok(*value);
    }
    if !visiting.insert(identifier.to_owned()) {
        return Err(ActionError::InvalidDefinition);
    }
    let predicate = definitions
        .get(identifier)
        .ok_or(ActionError::InvalidDefinition)?;
    for dependency in predicate_dependencies(&predicate.expression) {
        let value = evaluate_predicate(&dependency, definitions, values, visiting, context)?;
        context.insert(format!("action.predicate.{dependency}"), json!(value));
    }
    let value = evaluate(&predicate.expression, context, 64, 4096)
        .map_err(map_expression)?
        .as_bool()
        .ok_or(ActionError::StateInvariant)?;
    visiting.remove(identifier);
    values.insert(identifier.to_owned(), value);
    context.insert(format!("action.predicate.{identifier}"), json!(value));
    Ok(value)
}

fn validate_predicates(predicates: &[PredicateDefinition]) -> Result<(), ActionError> {
    let definitions: BTreeMap<&str, &PredicateDefinition> = predicates
        .iter()
        .map(|predicate| (predicate.id.as_str(), predicate))
        .collect();
    if definitions.len() != predicates.len() {
        return Err(ActionError::InvalidDefinition);
    }
    let mut complete = BTreeSet::new();
    let mut visiting = BTreeSet::new();
    for identifier in definitions.keys() {
        validate_predicate(identifier, &definitions, &mut complete, &mut visiting)?;
    }
    Ok(())
}

fn validate_predicate(
    identifier: &str,
    definitions: &BTreeMap<&str, &PredicateDefinition>,
    complete: &mut BTreeSet<String>,
    visiting: &mut BTreeSet<String>,
) -> Result<(), ActionError> {
    if complete.contains(identifier) {
        return Ok(());
    }
    if !visiting.insert(identifier.to_owned()) {
        return Err(ActionError::InvalidDefinition);
    }
    let predicate = definitions
        .get(identifier)
        .ok_or(ActionError::InvalidDefinition)?;
    for dependency in predicate_dependencies(&predicate.expression) {
        validate_predicate(&dependency, definitions, complete, visiting)?;
    }
    visiting.remove(identifier);
    complete.insert(identifier.to_owned());
    Ok(())
}

fn predicate_dependencies(expression: &Value) -> BTreeSet<String> {
    let mut dependencies = BTreeSet::new();
    collect_predicate_dependencies(expression, &mut dependencies);
    dependencies
}

fn collect_predicate_dependencies(expression: &Value, dependencies: &mut BTreeSet<String>) {
    match expression {
        Value::Object(object) => {
            if let Some(reference) = object.get("ref").and_then(Value::as_str)
                && let Some(identifier) = reference.strip_prefix("action.predicate.")
            {
                dependencies.insert(identifier.to_owned());
            }
            for value in object.values() {
                collect_predicate_dependencies(value, dependencies);
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_predicate_dependencies(value, dependencies);
            }
        }
        _ => {}
    }
}

fn apply_transition(
    action: &mut ActionInstance,
    definition: &ActionDefinition,
    transition: &TransitionDefinition,
) -> Result<(), ActionError> {
    action.transition_serial = action
        .transition_serial
        .checked_add(1)
        .ok_or(ActionError::IntegerOverflow)?;
    match transition.target_kind.as_str() {
        "NODE" => {
            let target_id = transition
                .target_node
                .as_deref()
                .ok_or(ActionError::InvalidDefinition)?;
            let target = node(definition, target_id)?;
            action.current_node_id = target_id.to_owned();
            action.node_step = transition.target_step;
            if target.mode == "TERMINAL" {
                action.lifecycle_state = "TERMINATED".to_owned();
            }
        }
        "TERMINATE" => action.lifecycle_state = "TERMINATED".to_owned(),
        "FAULT" => {
            action.lifecycle_state = "FAULTED".to_owned();
            action.fault_record = Some(transition.id.clone());
        }
        _ => return Err(ActionError::InvalidDefinition),
    }
    Ok(())
}

fn node<'a>(
    definition: &'a ActionDefinition,
    identifier: &str,
) -> Result<&'a NodeDefinition, ActionError> {
    definition
        .nodes
        .iter()
        .find(|node| node.id == identifier)
        .ok_or(ActionError::InvalidDefinition)
}

fn map_expression(error: EvalError) -> ActionError {
    match error {
        EvalError::IntegerOverflow => ActionError::IntegerOverflow,
        EvalError::DivisionByZero | EvalError::StateInvariant => ActionError::StateInvariant,
    }
}

fn event_driven() -> String {
    "EVENT_DRIVEN".to_owned()
}

fn node_target() -> String {
    "NODE".to_owned()
}

fn enabled() -> bool {
    true
}
