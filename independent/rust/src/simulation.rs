use crate::effects::{EffectEnvelope, ReducedEffect, RejectedEffect, reduce_effects};
use crate::{CanonicalError, canonical_hash};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug)]
pub enum SimulationError {
    Canonical(CanonicalError),
    InvalidVector,
    RuntimeFault,
}

impl From<CanonicalError> for SimulationError {
    fn from(error: CanonicalError) -> Self {
        Self::Canonical(error)
    }
}

#[derive(Debug, Clone)]
struct Predicate {
    id: String,
    node_ids: Vec<String>,
    min_node_step: u64,
    max_node_step_exclusive: Option<u64>,
    track_edges: bool,
}

#[derive(Debug, Clone)]
struct FactBinding {
    fact_id: String,
    when_predicate: String,
    effect_templates: Vec<EffectTemplate>,
    hit_policy: String,
    receipt_on: String,
}

#[derive(Debug, Clone)]
struct EffectTemplate {
    effect_type: String,
    effect_class: String,
    payload: Value,
    reducer: String,
    priority: i64,
    authoritative: bool,
}

#[derive(Debug, Clone)]
struct Definition {
    id: String,
    hash: String,
    initial_node: String,
    units_per_tick: u64,
    predicates: Vec<Predicate>,
    facts: Vec<FactBinding>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct ActionSnapshot {
    pub captured_parameters: BTreeMap<String, Value>,
    pub child_instance_ids: Vec<u64>,
    pub current_node_id: String,
    pub current_rate_units: u64,
    pub cycle: u64,
    pub deferred_quanta: u64,
    pub definition_hash: String,
    pub emission_serial: u64,
    pub event_inbox: Vec<Value>,
    pub extension_state: BTreeMap<String, Value>,
    pub fault_record: Option<String>,
    pub freeze_token_references: Vec<u64>,
    pub input_buffer: Vec<Value>,
    pub instance_id: u64,
    pub interaction_ledger_partition: String,
    pub lifecycle_state: String,
    pub local_step: u64,
    pub node_step: u64,
    pub owner_entity_id: u64,
    pub parent_instance_id: Option<u64>,
    pub parent_slot_id: Option<String>,
    pub predicate_entry_serials: BTreeMap<String, u64>,
    pub predicate_exit_serials: BTreeMap<String, u64>,
    pub predicate_truth_state: BTreeMap<String, bool>,
    pub quantum_accumulator: u64,
    pub registers: BTreeMap<String, Value>,
    pub rng_stream_ids: Vec<String>,
    pub slot_claims: Vec<Value>,
    pub transition_serial: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct SimulationState {
    pub pcam_version: String,
    pub action_instances: Vec<ActionSnapshot>,
    pub action_slots: BTreeMap<String, Value>,
    pub definition_set_hash: String,
    pub entity_records: BTreeMap<String, Value>,
    pub extension_state: BTreeMap<String, Value>,
    pub fault_state: BTreeMap<String, Value>,
    pub freeze_tokens: Vec<Value>,
    pub host_state: Value,
    pub input_buffers: BTreeMap<String, Value>,
    pub interaction_ledgers: BTreeMap<String, Value>,
    pub next_action_instance_id: u64,
    pub next_freeze_token_id: u64,
    pub pending_events: Vec<Value>,
    pub pending_inputs: Vec<Value>,
    pub resource_banks: BTreeMap<String, BTreeMap<String, i64>>,
    pub rng_streams: BTreeMap<String, Value>,
    pub tick: u64,
}

impl SimulationState {
    pub fn snapshot(&self) -> Result<Value, SimulationError> {
        serde_json::to_value(self).map_err(|_| SimulationError::RuntimeFault)
    }

    pub fn digest(&self) -> Result<String, SimulationError> {
        Ok(canonical_hash(&self.snapshot()?)?)
    }

    pub fn restore(snapshot: &Value) -> Result<Self, SimulationError> {
        let state: Self =
            serde_json::from_value(snapshot.clone()).map_err(|_| SimulationError::RuntimeFault)?;
        if state.pcam_version != "3.0" {
            return Err(SimulationError::RuntimeFault);
        }
        Ok(state)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SimulationTrace {
    pub input_order: Vec<String>,
    pub candidate_order: Vec<String>,
    pub effects: Vec<EffectEnvelope>,
    pub reduced: Vec<ReducedEffect>,
    pub rejected: Vec<RejectedEffect>,
    pub receipts: Vec<Value>,
    pub state_digest: String,
}

#[derive(Debug, Clone)]
pub struct SimulationRuntime {
    definitions: BTreeMap<String, Definition>,
    effect_registry: BTreeMap<String, (String, i64)>,
    definition_set_hash: String,
}

#[derive(Debug, Clone)]
pub struct RollbackFrame {
    pub snapshot: Value,
    pub tick_document: Value,
    pub presentation_effect_ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RollbackCorrection {
    pub state: SimulationState,
    pub traces: Vec<SimulationTrace>,
    pub rewind_ticks: u64,
    pub presentation_emit: Vec<String>,
    pub presentation_invalidated: Vec<String>,
    pub presentation_suppressed: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct RetainedRollbackHistory {
    runtime: SimulationRuntime,
    retained_history_ticks: u64,
    frames: BTreeMap<u64, RollbackFrame>,
    head_state: Option<SimulationState>,
    presented_effect_ids: BTreeSet<String>,
}

impl RetainedRollbackHistory {
    pub fn new(
        runtime: SimulationRuntime,
        retained_history_ticks: u64,
    ) -> Result<Self, SimulationError> {
        if retained_history_ticks == 0 {
            return Err(SimulationError::InvalidVector);
        }
        Ok(Self {
            runtime,
            retained_history_ticks,
            frames: BTreeMap::new(),
            head_state: None,
            presented_effect_ids: BTreeSet::new(),
        })
    }

    pub fn head_state(&self) -> Option<&SimulationState> {
        self.head_state.as_ref()
    }

    pub fn frame_snapshots(&self) -> BTreeMap<u64, Value> {
        self.frames
            .iter()
            .map(|(tick, frame)| (*tick, frame.snapshot.clone()))
            .collect()
    }

    pub fn advance(
        &mut self,
        state: &SimulationState,
        tick_document: &Value,
    ) -> Result<(SimulationState, SimulationTrace, Vec<String>), SimulationError> {
        if self.head_state.as_ref().is_some_and(|head| head != state) {
            return Err(SimulationError::RuntimeFault);
        }
        let snapshot = state.snapshot()?;
        let (next, trace) = self.runtime.tick(state, tick_document)?;
        let presentation_effect_ids = presentation_ids(&trace.effects);
        self.frames.insert(
            state.tick,
            RollbackFrame {
                snapshot,
                tick_document: tick_document.clone(),
                presentation_effect_ids: presentation_effect_ids.clone(),
            },
        );
        self.presented_effect_ids
            .extend(presentation_effect_ids.iter().cloned());
        self.head_state = Some(next.clone());
        self.prune(next.tick);
        Ok((next, trace, presentation_effect_ids))
    }

    pub fn correct_and_resimulate(
        &mut self,
        corrected_tick: u64,
        corrected_tick_document: &Value,
    ) -> Result<RollbackCorrection, SimulationError> {
        let head = self
            .head_state
            .as_ref()
            .ok_or(SimulationError::RuntimeFault)?;
        let until_tick = head.tick;
        let frame = self
            .frames
            .get(&corrected_tick)
            .ok_or(SimulationError::RuntimeFault)?;
        let required = (corrected_tick..until_tick).collect::<Vec<_>>();
        if required.iter().any(|tick| !self.frames.contains_key(tick)) {
            return Err(SimulationError::RuntimeFault);
        }
        let old_frames = required
            .iter()
            .map(|tick| (*tick, self.frames[tick].clone()))
            .collect::<BTreeMap<_, _>>();
        let old_presentation = old_frames
            .values()
            .flat_map(|old| old.presentation_effect_ids.iter().cloned())
            .collect::<BTreeSet<_>>();
        let base_presented = self
            .presented_effect_ids
            .difference(&old_presentation)
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut state = SimulationState::restore(&frame.snapshot)?;
        let mut traces = Vec::new();
        let mut replacement_frames = BTreeMap::new();
        let mut replayed_presentation = BTreeSet::new();
        for tick in &required {
            let old = &old_frames[tick];
            let document = if *tick == corrected_tick {
                corrected_tick_document
            } else {
                &old.tick_document
            };
            let snapshot = state.snapshot()?;
            let (next, trace) = self.runtime.tick(&state, document)?;
            let ids = presentation_ids(&trace.effects);
            replayed_presentation.extend(ids.iter().cloned());
            replacement_frames.insert(
                *tick,
                RollbackFrame {
                    snapshot,
                    tick_document: document.clone(),
                    presentation_effect_ids: ids,
                },
            );
            state = next;
            traces.push(trace);
        }
        let invalidated = canonical_set(old_presentation.difference(&replayed_presentation));
        let suppressed = canonical_set(old_presentation.intersection(&replayed_presentation));
        let emitted = canonical_set(
            replayed_presentation
                .difference(&old_presentation)
                .filter(|identifier| !base_presented.contains(*identifier)),
        );
        self.frames.extend(replacement_frames);
        self.presented_effect_ids = base_presented
            .union(&replayed_presentation)
            .cloned()
            .collect();
        self.head_state = Some(state.clone());
        Ok(RollbackCorrection {
            state,
            traces,
            rewind_ticks: until_tick - corrected_tick,
            presentation_emit: emitted,
            presentation_invalidated: invalidated,
            presentation_suppressed: suppressed,
        })
    }

    fn prune(&mut self, head_tick: u64) {
        let earliest = head_tick.saturating_sub(self.retained_history_ticks);
        self.frames.retain(|tick, _| *tick >= earliest);
    }
}

impl SimulationRuntime {
    pub fn from_vector(vector: &Value) -> Result<Self, SimulationError> {
        let definitions_raw = array(vector, "definitions")?;
        let profile = object_value(vector, "runtime_profile")?;
        let rules = array(vector, "interaction_rules")?;
        let registry = object_value(vector, "effect_registry")?;

        let profile_hash = canonical_hash(&canonical_profile(profile)?)?;
        let interaction_profile_hash = canonical_hash(&canonical_rules(rules)?)?;
        let effect_registry_hash = canonical_hash(registry)?;
        let extension_registry_hash = canonical_hash(&Value::Array(Vec::new()))?;
        let mut definitions = BTreeMap::new();
        let mut identities = Vec::new();
        for raw in definitions_raw {
            let canonical = canonical_definition(raw)?;
            let hash = canonical_hash(&canonical)?;
            let definition = parse_definition(raw, hash.clone())?;
            identities.push(json!({
                "definition_hash": hash,
                "definition_id": definition.id,
                "effect_registry_hash": effect_registry_hash,
                "extension_registry_hash": extension_registry_hash,
                "interaction_profile_hash": interaction_profile_hash,
                "runtime_profile_hash": profile_hash,
            }));
            definitions.insert(definition.id.clone(), definition);
        }
        identities.sort_by(|left, right| {
            left["definition_id"]
                .as_str()
                .unwrap_or_default()
                .as_bytes()
                .cmp(
                    right["definition_id"]
                        .as_str()
                        .unwrap_or_default()
                        .as_bytes(),
                )
        });
        let definition_set_hash = canonical_hash(&Value::Array(identities))?;
        let effect_registry = registry
            .as_object()
            .ok_or(SimulationError::InvalidVector)?
            .iter()
            .map(|(effect_type, raw)| {
                let values = raw.as_array().ok_or(SimulationError::InvalidVector)?;
                Ok((
                    effect_type.clone(),
                    (
                        string(&values[0])?.to_owned(),
                        values[1].as_i64().ok_or(SimulationError::InvalidVector)?,
                    ),
                ))
            })
            .collect::<Result<BTreeMap<_, _>, SimulationError>>()?;
        Ok(Self {
            definitions,
            effect_registry,
            definition_set_hash,
        })
    }

    pub fn initial_state(&self, vector: &Value) -> Result<SimulationState, SimulationError> {
        let initial = object_value(vector, "initial_state")?;
        let resource_banks = initial
            .get("resource_banks")
            .cloned()
            .unwrap_or_else(|| json!({}));
        Ok(SimulationState {
            pcam_version: "3.0".to_owned(),
            action_instances: Vec::new(),
            action_slots: BTreeMap::new(),
            definition_set_hash: self.definition_set_hash.clone(),
            entity_records: BTreeMap::new(),
            extension_state: BTreeMap::new(),
            fault_state: BTreeMap::new(),
            freeze_tokens: Vec::new(),
            host_state: json!({}),
            input_buffers: BTreeMap::new(),
            interaction_ledgers: BTreeMap::new(),
            next_action_instance_id: 1,
            next_freeze_token_id: 1,
            pending_events: Vec::new(),
            pending_inputs: Vec::new(),
            resource_banks: serde_json::from_value(resource_banks)
                .map_err(|_| SimulationError::InvalidVector)?,
            rng_streams: BTreeMap::new(),
            tick: 0,
        })
    }

    pub fn tick(
        &self,
        state: &SimulationState,
        tick: &Value,
    ) -> Result<(SimulationState, SimulationTrace), SimulationError> {
        if state.definition_set_hash != self.definition_set_hash {
            return Err(SimulationError::RuntimeFault);
        }
        let mut work = state.clone();
        let contacts = canonical_contacts(array(tick, "contacts")?)?;
        work.host_state = json!({"contacts": contacts, "imports": {}});

        let inputs = canonical_inputs(array(tick, "inputs")?)?;
        let input_order = inputs
            .iter()
            .map(|input| string_field(input, "input_id").map(str::to_owned))
            .collect::<Result<Vec<_>, _>>()?;
        for input in inputs {
            if string_field(&input, "command_id")? != "START" {
                continue;
            }
            let definition_id = string_field(&input, "action_definition_id")?;
            let definition = self
                .definitions
                .get(definition_id)
                .ok_or(SimulationError::RuntimeFault)?;
            let instance_id = work.next_action_instance_id;
            work.next_action_instance_id = work
                .next_action_instance_id
                .checked_add(1)
                .ok_or(SimulationError::RuntimeFault)?;
            work.action_instances.push(ActionSnapshot {
                captured_parameters: BTreeMap::new(),
                child_instance_ids: Vec::new(),
                current_node_id: definition.initial_node.clone(),
                current_rate_units: definition.units_per_tick,
                cycle: 0,
                deferred_quanta: 0,
                definition_hash: definition.hash.clone(),
                emission_serial: 0,
                event_inbox: Vec::new(),
                extension_state: BTreeMap::new(),
                fault_record: None,
                freeze_token_references: Vec::new(),
                input_buffer: Vec::new(),
                instance_id,
                interaction_ledger_partition: "default".to_owned(),
                lifecycle_state: "RUNNING".to_owned(),
                local_step: 0,
                node_step: 0,
                owner_entity_id: u64_field(&input, "source_entity_id")?,
                parent_instance_id: None,
                parent_slot_id: None,
                predicate_entry_serials: BTreeMap::new(),
                predicate_exit_serials: BTreeMap::new(),
                predicate_truth_state: BTreeMap::new(),
                quantum_accumulator: 0,
                registers: BTreeMap::new(),
                rng_stream_ids: Vec::new(),
                slot_claims: Vec::new(),
                transition_serial: 0,
            });
        }
        work.action_instances
            .sort_by_key(|action| action.instance_id);

        for action in &mut work.action_instances {
            let definition = self
                .definitions
                .values()
                .find(|definition| definition.hash == action.definition_hash)
                .ok_or(SimulationError::RuntimeFault)?;
            for predicate in &definition.predicates {
                let now = predicate.node_ids.contains(&action.current_node_id)
                    && action.node_step >= predicate.min_node_step
                    && predicate
                        .max_node_step_exclusive
                        .is_none_or(|maximum| action.node_step < maximum);
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
                        .ok_or(SimulationError::RuntimeFault)?;
                    serials.insert(predicate.id.clone(), next);
                }
            }
        }

        let candidate_order = contacts
            .iter()
            .map(|contact| string_field(contact, "candidate_id").map(str::to_owned))
            .collect::<Result<Vec<_>, _>>()?;
        let mut effects = Vec::new();
        let mut receipts = Vec::new();
        for contact in &contacts {
            let instance_id = u64_field(contact, "source_instance_id")?;
            let Some(action) = work
                .action_instances
                .iter()
                .find(|action| action.instance_id == instance_id)
            else {
                continue;
            };
            let definition = self
                .definitions
                .values()
                .find(|definition| definition.hash == action.definition_hash)
                .ok_or(SimulationError::RuntimeFault)?;
            let fact_id = string_field(contact, "fact_id")?;
            let binding = definition
                .facts
                .iter()
                .find(|binding| {
                    binding.fact_id == fact_id
                        && action
                            .predicate_truth_state
                            .get(&binding.when_predicate)
                            .copied()
                            .unwrap_or(false)
                })
                .ok_or(SimulationError::RuntimeFault)?;
            let ledger_key = canonical_hash(&json!({
                "fact": binding.fact_id,
                "instance": instance_id,
                "policy": binding.hit_policy,
                "target": u64_field(contact, "target_entity_id")?,
            }))?;
            let candidate_id = string_field(contact, "candidate_id")?;
            if work.interaction_ledgers.contains_key(&ledger_key) {
                receipts.push(json!({
                    "accepted": false,
                    "candidate_id": candidate_id,
                    "reason": binding.hit_policy,
                }));
                continue;
            }
            for (template_index, template) in binding.effect_templates.iter().enumerate() {
                effects.push(EffectEnvelope {
                    effect_id: format!(
                        "{}:{instance_id}:{candidate_id}:materialize:0:{template_index}",
                        state.tick
                    ),
                    effect_type: template.effect_type.clone(),
                    effect_class: template.effect_class.clone(),
                    source_entity_id: action.owner_entity_id,
                    target_entity_id: u64_field(contact, "target_entity_id")?,
                    source_action_instance_id: instance_id,
                    origin_tick: state.tick,
                    priority: template.priority,
                    payload: template.payload.clone(),
                    reducer: template.reducer.clone(),
                    authoritative: template.authoritative,
                });
            }
            if binding.receipt_on == "ON_IMPACT"
                && effects.iter().any(|effect| effect.authoritative)
            {
                work.interaction_ledgers.insert(
                    ledger_key,
                    json!({
                        "candidate_id": candidate_id,
                        "condition": binding.receipt_on,
                        "origin_tick": state.tick,
                    }),
                );
            }
            receipts.push(json!({
                "accepted": true,
                "candidate_id": candidate_id,
                "decision_tags": [],
                "receipt_written": true,
                "redirect_count": 0,
                "rules_fired": [{
                    "order": 100,
                    "rule_id": "materialize",
                    "stage": "MATERIALIZATION",
                }],
            }));
        }

        let (reduced, rejected) =
            reduce_effects(&effects).map_err(|_| SimulationError::RuntimeFault)?;
        for effect in &reduced {
            let (resource, multiplier) = self
                .effect_registry
                .get(&effect.effect_type)
                .ok_or(SimulationError::RuntimeFault)?;
            if effects
                .iter()
                .filter(|source| {
                    source.target_entity_id == effect.target_entity_id
                        && source.effect_type == effect.effect_type
                })
                .any(|source| source.authoritative)
            {
                let value = effect.value.as_i64().ok_or(SimulationError::RuntimeFault)?;
                let delta = value
                    .checked_mul(*multiplier)
                    .ok_or(SimulationError::RuntimeFault)?;
                let bank = work
                    .resource_banks
                    .entry(effect.target_entity_id.to_string())
                    .or_default();
                let current = bank.get(resource).copied().unwrap_or(0);
                bank.insert(
                    resource.clone(),
                    current
                        .checked_add(delta)
                        .ok_or(SimulationError::RuntimeFault)?,
                );
            }
        }
        for action in &mut work.action_instances {
            action.event_inbox.clear();
        }
        work.tick = work
            .tick
            .checked_add(1)
            .ok_or(SimulationError::RuntimeFault)?;
        let state_digest = work.digest()?;
        Ok((
            work,
            SimulationTrace {
                input_order,
                candidate_order,
                effects,
                reduced,
                rejected,
                receipts,
                state_digest,
            },
        ))
    }
}

fn canonical_definition(raw: &Value) -> Result<Value, SimulationError> {
    let id = string_field(raw, "id")?;
    let nodes = array(raw, "nodes")?
        .iter()
        .map(|node| {
            Ok(json!({
                "duration_quanta": node.get("duration_quanta").cloned().unwrap_or(Value::Null),
                "entry_assignments": node.get("entry_assignments").cloned().unwrap_or_else(|| json!([])),
                "entry_effects": node.get("entry_effects").cloned().unwrap_or_else(|| json!([])),
                "exit_assignments": node.get("exit_assignments").cloned().unwrap_or_else(|| json!([])),
                "exit_effects": node.get("exit_effects").cloned().unwrap_or_else(|| json!([])),
                "extensions": node.get("extensions").cloned().unwrap_or_else(|| json!({})),
                "id": string_field(node, "id")?,
                "mode": node.get("mode").cloned().unwrap_or_else(|| json!("EVENT_DRIVEN")),
                "predicates": node.get("predicates").cloned().unwrap_or_else(|| json!([])),
                "seekable": node.get("seekable").cloned().unwrap_or_else(|| json!(false)),
                "tags": node.get("tags").cloned().unwrap_or_else(|| json!([])),
            }))
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    let predicates = raw
        .get("predicates")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|predicate| {
            Ok(json!({
                "expression": predicate.get("expression").cloned().unwrap_or(Value::Null),
                "id": string_field(predicate, "id")?,
                "max_node_step_exclusive": predicate.get("max_node_step_exclusive").cloned().unwrap_or(Value::Null),
                "min_node_step": predicate.get("min_node_step").cloned().unwrap_or_else(|| json!(0)),
                "node_ids": predicate.get("node_ids").cloned().unwrap_or_else(|| json!([])),
                "track_edges": predicate.get("track_edges").cloned().unwrap_or_else(|| json!(true)),
            }))
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    let semantic_facts = raw
        .get("semantic_facts")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(canonical_fact_binding)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({
        "buffer": {
            "capacity": raw.get("buffer_capacity").cloned().unwrap_or_else(|| json!(8)),
            "default_lifetime": raw.get("default_buffer_lifetime").cloned().unwrap_or_else(|| json!(1)),
            "overflow_policy": raw.get("buffer_overflow_policy").cloned().unwrap_or_else(|| json!("DROP_OLDEST")),
        },
        "child_slot_capacities": raw.get("child_slot_capacities").cloned().unwrap_or_else(|| json!({})),
        "child_termination_policies": raw.get("child_termination_policies").cloned().unwrap_or_else(|| json!({})),
        "extensions": raw.get("extensions").cloned().unwrap_or_else(|| json!({})),
        "id": id,
        "import_declarations": raw.get("import_declarations").cloned().unwrap_or_else(|| json!({})),
        "initial_node": raw.get("initial_node_id").cloned().unwrap_or_else(|| json!(string_field(&nodes[0], "id").unwrap_or_default())),
        "metadata": raw.get("metadata").cloned().unwrap_or_else(|| json!({})),
        "nodes": nodes,
        "parameter_declarations": raw.get("parameter_declarations").cloned().unwrap_or_else(|| json!({})),
        "parameter_defaults": raw.get("parameter_defaults").cloned().unwrap_or_else(|| json!({})),
        "predicates": predicates,
        "rate": {"scale": raw["rate_scale"].clone(), "units_per_tick": raw["units_per_tick"].clone()},
        "register_declarations": raw.get("register_declarations").cloned().unwrap_or_else(|| json!({})),
        "register_initials": raw.get("register_initials").cloned().unwrap_or_else(|| json!({})),
        "semantic_facts": semantic_facts,
        "slot_claims": raw.get("slot_claims").cloned().unwrap_or_else(|| json!([])),
        "start_claims": raw.get("start_claims").cloned().unwrap_or_else(|| json!([])),
        "transitions": raw.get("transitions").cloned().unwrap_or_else(|| json!([])),
    }))
}

fn canonical_fact_binding(raw: &Value) -> Result<Value, SimulationError> {
    let fact = object_value(raw, "fact")?;
    let policy = object_value(raw, "hit_policy")?;
    let templates = fact
        .get("effect_templates")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|template| {
            json!({
                "authoritative": template.get("authoritative").cloned().unwrap_or_else(|| json!(true)),
                "effect_class": template["effect_class"].clone(),
                "effect_type": template["effect_type"].clone(),
                "payload": template["payload"].clone(),
                "priority": template.get("priority").cloned().unwrap_or_else(|| json!(0)),
                "reducer": template.get("reducer").cloned().unwrap_or_else(|| json!("ORDERED")),
            })
        })
        .collect::<Vec<_>>();
    Ok(json!({
        "fact": {
            "attributes": fact.get("attributes").cloned().unwrap_or_else(|| json!({})),
            "channels": fact.get("channels").cloned().unwrap_or_else(|| json!([])),
            "direction": fact["direction"].clone(),
            "effect_templates": templates,
            "fact_id": fact["fact_id"].clone(),
            "tags": fact.get("tags").cloned().unwrap_or_else(|| json!([])),
        },
        "hit_policy": {
            "cooldown_ticks": policy.get("cooldown_ticks").cloned().unwrap_or(Value::Null),
            "kind": policy["kind"].clone(),
            "predicate_id": policy.get("predicate_id").cloned().unwrap_or(Value::Null),
            "receipt_on": policy["receipt_on"].clone(),
        },
        "when_predicate": raw["when_predicate"].clone(),
    }))
}

fn canonical_profile(raw: &Value) -> Result<Value, SimulationError> {
    let networks = array(raw, "network_profiles")?
        .iter()
        .map(|network| {
            Ok(json!({
                "correction_policy": network.get("correction_policy").cloned().unwrap_or(Value::Null),
                "desynchronization_policy": network.get("desynchronization_policy").cloned().unwrap_or(Value::Null),
                "digest_interval_ticks": network.get("digest_interval_ticks").cloned().unwrap_or(Value::Null),
                "effect_reconciliation_policy": network.get("effect_reconciliation_policy").cloned().unwrap_or(Value::Null),
                "id": string_field(network, "id")?,
                "input_availability_policy": network.get("input_availability_policy").cloned().unwrap_or(Value::Null),
                "latency_mechanism": network.get("latency_mechanism").cloned().unwrap_or(Value::Null),
                "max_latency_compensation_ticks": network.get("max_latency_compensation_ticks").cloned().unwrap_or(Value::Null),
                "predictor_id": network.get("predictor_id").cloned().unwrap_or(Value::Null),
                "retained_history_ticks": network.get("retained_history_ticks").cloned().unwrap_or(Value::Null),
                "snapshot_interval_ticks": network.get("snapshot_interval_ticks").cloned().unwrap_or(Value::Null),
                "topology": string_field(network, "topology")?,
            }))
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    Ok(json!({
        "extensions": raw.get("extensions").cloned().unwrap_or_else(|| json!({})),
        "fault_policy": raw["fault_policy"].clone(),
        "id": raw["id"].clone(),
        "kind": "runtime_profile",
        "limits": raw["limits"].clone(),
        "network_profiles": networks,
        "pcam_version": "3.0",
        "revision": raw["revision"].clone(),
        "rng_profiles": raw["rng_profiles"].clone(),
    }))
}

fn canonical_rules(raw: &[Value]) -> Result<Value, SimulationError> {
    Ok(Value::Array(
        raw.iter()
            .map(|rule| {
                let operations = array(rule, "operations")?
                    .iter()
                    .map(|operation| {
                        json!({
                            "data": operation.get("data").cloned().unwrap_or_else(|| json!({})),
                            "op": operation["op"].clone(),
                        })
                    })
                    .collect::<Vec<_>>();
                Ok(json!({
                    "condition": rule["condition"].clone(),
                    "operations": operations,
                    "order": rule["order"].clone(),
                    "rule_id": rule["rule_id"].clone(),
                    "stage": rule["stage"].clone(),
                    "stop_pipeline": rule.get("stop_pipeline").cloned().unwrap_or_else(|| json!(false)),
                    "stop_stage": rule.get("stop_stage").cloned().unwrap_or_else(|| json!(false)),
                }))
            })
            .collect::<Result<Vec<_>, SimulationError>>()?,
    ))
}

fn parse_definition(raw: &Value, hash: String) -> Result<Definition, SimulationError> {
    let predicates = raw
        .get("predicates")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|predicate| {
            Ok(Predicate {
                id: string_field(predicate, "id")?.to_owned(),
                node_ids: predicate
                    .get("node_ids")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|value| string(value).map(str::to_owned))
                    .collect::<Result<Vec<_>, _>>()?,
                min_node_step: predicate
                    .get("min_node_step")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                max_node_step_exclusive: predicate
                    .get("max_node_step_exclusive")
                    .and_then(Value::as_u64),
                track_edges: predicate
                    .get("track_edges")
                    .and_then(Value::as_bool)
                    .unwrap_or(true),
            })
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    let facts = raw
        .get("semantic_facts")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|binding| {
            let fact = object_value(binding, "fact")?;
            let policy = object_value(binding, "hit_policy")?;
            let effect_templates = fact
                .get("effect_templates")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
                .iter()
                .map(|template| {
                    Ok(EffectTemplate {
                        effect_type: string_field(template, "effect_type")?.to_owned(),
                        effect_class: string_field(template, "effect_class")?.to_owned(),
                        payload: template["payload"].clone(),
                        reducer: template
                            .get("reducer")
                            .and_then(Value::as_str)
                            .unwrap_or("ORDERED")
                            .to_owned(),
                        priority: template
                            .get("priority")
                            .and_then(Value::as_i64)
                            .unwrap_or(0),
                        authoritative: template
                            .get("authoritative")
                            .and_then(Value::as_bool)
                            .unwrap_or(true),
                    })
                })
                .collect::<Result<Vec<_>, SimulationError>>()?;
            Ok(FactBinding {
                fact_id: string_field(fact, "fact_id")?.to_owned(),
                when_predicate: string_field(binding, "when_predicate")?.to_owned(),
                effect_templates,
                hit_policy: string_field(policy, "kind")?.to_owned(),
                receipt_on: string_field(policy, "receipt_on")?.to_owned(),
            })
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    Ok(Definition {
        id: string_field(raw, "id")?.to_owned(),
        hash,
        initial_node: raw
            .get("initial_node_id")
            .and_then(Value::as_str)
            .unwrap_or(string_field(&array(raw, "nodes")?[0], "id")?)
            .to_owned(),
        units_per_tick: u64_field(raw, "units_per_tick")?,
        predicates,
        facts,
    })
}

fn canonical_inputs(raw: &[Value]) -> Result<Vec<Value>, SimulationError> {
    let mut deduplicated = BTreeMap::new();
    for input in raw {
        deduplicated
            .entry(string_field(input, "input_id")?.to_owned())
            .or_insert_with(|| input.clone());
    }
    let mut values = deduplicated.into_values().collect::<Vec<_>>();
    values.sort_by(|left, right| {
        u64_field(left, "source_entity_id")
            .unwrap_or_default()
            .cmp(&u64_field(right, "source_entity_id").unwrap_or_default())
            .then_with(|| {
                u64_field(left, "sequence")
                    .unwrap_or_default()
                    .cmp(&u64_field(right, "sequence").unwrap_or_default())
            })
            .then_with(|| {
                string_field(left, "command_id")
                    .unwrap_or_default()
                    .as_bytes()
                    .cmp(
                        string_field(right, "command_id")
                            .unwrap_or_default()
                            .as_bytes(),
                    )
            })
            .then_with(|| {
                string_field(left, "input_id")
                    .unwrap_or_default()
                    .as_bytes()
                    .cmp(
                        string_field(right, "input_id")
                            .unwrap_or_default()
                            .as_bytes(),
                    )
            })
    });
    Ok(values)
}

fn canonical_contacts(raw: &[Value]) -> Result<Vec<Value>, SimulationError> {
    let mut values = raw
        .iter()
        .map(|contact| {
            Ok(json!({
                "candidate_id": string_field(contact, "candidate_id")?,
                "contact_id": string_field(contact, "contact_id")?,
                "contact_partition": contact.get("contact_partition").cloned().unwrap_or_else(|| json!("default")),
                "defense_fact_id": contact.get("defense_fact_id").cloned().unwrap_or(Value::Null),
                "effect": contact.get("effect").cloned().unwrap_or(Value::Null),
                "fact_id": string_field(contact, "fact_id")?,
                "host_context": contact.get("host_context").cloned().unwrap_or_else(|| json!({})),
                "source_entity_id": u64_field(contact, "source_entity_id")?,
                "source_instance_id": u64_field(contact, "source_instance_id")?,
                "target_entity_id": u64_field(contact, "target_entity_id")?,
            }))
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    values.sort_by(|left, right| contact_key(left).cmp(&contact_key(right)));
    Ok(values)
}

fn contact_key(value: &Value) -> (u64, u64, u64, String, String, String, String, String) {
    (
        u64_field(value, "source_entity_id").unwrap_or_default(),
        u64_field(value, "target_entity_id").unwrap_or_default(),
        u64_field(value, "source_instance_id").unwrap_or_default(),
        string_field(value, "fact_id")
            .unwrap_or_default()
            .to_owned(),
        value
            .get("defense_fact_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        string_field(value, "contact_partition")
            .unwrap_or_default()
            .to_owned(),
        string_field(value, "contact_id")
            .unwrap_or_default()
            .to_owned(),
        string_field(value, "candidate_id")
            .unwrap_or_default()
            .to_owned(),
    )
}

fn array<'a>(value: &'a Value, field: &str) -> Result<&'a [Value], SimulationError> {
    value
        .get(field)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .ok_or(SimulationError::InvalidVector)
}

fn object_value<'a>(value: &'a Value, field: &str) -> Result<&'a Value, SimulationError> {
    let nested = value.get(field).ok_or(SimulationError::InvalidVector)?;
    nested
        .as_object()
        .map(|_| nested)
        .ok_or(SimulationError::InvalidVector)
}

fn string(value: &Value) -> Result<&str, SimulationError> {
    value.as_str().ok_or(SimulationError::InvalidVector)
}

fn string_field<'a>(value: &'a Value, field: &str) -> Result<&'a str, SimulationError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or(SimulationError::InvalidVector)
}

fn u64_field(value: &Value, field: &str) -> Result<u64, SimulationError> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or(SimulationError::InvalidVector)
}

fn presentation_ids(effects: &[EffectEnvelope]) -> Vec<String> {
    effects
        .iter()
        .filter(|effect| !effect.authoritative)
        .map(|effect| effect.effect_id.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn canonical_set<'a>(values: impl Iterator<Item = &'a String>) -> Vec<String> {
    values
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}
