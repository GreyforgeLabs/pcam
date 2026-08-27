use crate::arbitration::{
    ArbitrationState, Claim as ArbitrationClaim, Intent as ArbitrationIntent,
    arbitrate as arbitrate_intents,
};
use crate::effects::{EffectEnvelope, ReducedEffect, RejectedEffect, reduce_effects};
use crate::events::{EventEnvelope, deliver_due};
use crate::faults::{FaultContext, contain_fault};
use crate::interactions::{
    EffectTemplate as InteractionEffectTemplate, InteractionCandidate, InteractionError,
    InteractionRule, SemanticFact, resolve_candidate,
};
use crate::ledger::{
    HitPolicy as LedgerHitPolicy, LedgerContext, is_eligible as ledger_is_eligible,
    receipt_required, write_receipt,
};
use crate::{CanonicalError, canonical_hash};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug)]
pub enum SimulationError {
    Canonical(CanonicalError),
    Fault(FaultContext),
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
    direction: String,
    channels: Vec<String>,
    tags: Vec<String>,
    when_predicate: String,
    effect_templates: Vec<InteractionEffectTemplate>,
    hit_policy: LedgerHitPolicy,
}

#[derive(Debug, Clone)]
struct Definition {
    id: String,
    hash: String,
    initial_node: String,
    rate_scale: u64,
    units_per_tick: u64,
    nodes: BTreeMap<String, String>,
    predicates: Vec<Predicate>,
    facts: Vec<FactBinding>,
    transitions: Vec<SimulationTransition>,
    child_slot_capacities: BTreeMap<String, u64>,
    child_termination_policies: BTreeMap<String, String>,
    start_claims: Vec<ArbitrationClaim>,
    slot_claims: Vec<ArbitrationClaim>,
}

#[derive(Debug, Clone)]
struct SimulationTransition {
    id: String,
    source_node: String,
    evaluation_point: String,
    priority: i64,
    cycle_delta: u64,
    claims: Vec<ArbitrationClaim>,
    target_kind: String,
    target_node: Option<String>,
    target_action: Option<String>,
    child_slot_id: Option<String>,
    parent_policy: Option<String>,
    source_disposition: String,
    event_type: Option<String>,
    input_command: Option<String>,
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
    pub faults: Vec<Value>,
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
    fault_policy: String,
    interaction_rules: Vec<InteractionRule>,
    max_actions_per_entity: u64,
    max_action_nesting_depth: u64,
    max_expression_depth: usize,
    max_expression_nodes: usize,
    max_quanta_per_action_per_tick: u64,
    max_redirects_per_candidate: u64,
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
        let max_actions_per_entity = profile["limits"]["max_actions_per_entity"]
            .as_u64()
            .ok_or(SimulationError::InvalidVector)?;
        let max_action_nesting_depth = profile["limits"]["max_action_nesting_depth"]
            .as_u64()
            .ok_or(SimulationError::InvalidVector)?;
        let max_quanta_per_action_per_tick = profile["limits"]["max_quanta_per_action_per_tick"]
            .as_u64()
            .ok_or(SimulationError::InvalidVector)?;
        let max_redirects_per_candidate = profile["limits"]["max_redirects_per_candidate"]
            .as_u64()
            .ok_or(SimulationError::InvalidVector)?;
        let max_expression_depth = profile["limits"]["max_expression_depth"]
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .ok_or(SimulationError::InvalidVector)?;
        let max_expression_nodes = profile["limits"]["max_expression_nodes"]
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .ok_or(SimulationError::InvalidVector)?;
        let fault_policy = profile["fault_policy"]
            .as_str()
            .ok_or(SimulationError::InvalidVector)?
            .to_owned();
        let interaction_profile_hash = canonical_hash(&canonical_rules(rules)?)?;
        let interaction_rules = rules
            .iter()
            .map(|rule| {
                serde_json::from_value::<InteractionRule>(rule.clone())
                    .map_err(|_| SimulationError::InvalidVector)
            })
            .collect::<Result<Vec<_>, _>>()?;
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
            fault_policy,
            interaction_rules,
            max_actions_per_entity,
            max_action_nesting_depth,
            max_expression_depth,
            max_expression_nodes,
            max_quanta_per_action_per_tick,
            max_redirects_per_candidate,
        })
    }

    pub fn initial_state(&self, vector: &Value) -> Result<SimulationState, SimulationError> {
        let initial = object_value(vector, "initial_state")?;
        let resource_banks = initial
            .get("resource_banks")
            .cloned()
            .unwrap_or_else(|| json!({}));
        let action_slots = initial
            .get("slot_capacities")
            .and_then(Value::as_object)
            .map(|entities| {
                entities
                    .iter()
                    .map(|(entity, slots)| {
                        let slots = slots.as_object().ok_or(SimulationError::InvalidVector)?;
                        let normalized = slots
                            .iter()
                            .map(|(slot, capacity)| {
                                Ok((
                                    slot.clone(),
                                    json!({
                                        "capacity": capacity.as_u64().ok_or(SimulationError::InvalidVector)?,
                                        "instance_ids": [],
                                        "usage": 0,
                                    }),
                                ))
                            })
                            .collect::<Result<Map<String, Value>, SimulationError>>()?;
                        Ok((entity.clone(), Value::Object(normalized)))
                    })
                    .collect::<Result<BTreeMap<String, Value>, SimulationError>>()
            })
            .transpose()?
            .unwrap_or_default();
        Ok(SimulationState {
            pcam_version: "3.0".to_owned(),
            action_instances: Vec::new(),
            action_slots,
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
        match self.tick_once(state, tick) {
            Ok(result) => Ok(result),
            Err(SimulationError::Fault(context)) => {
                let contained = contain_fault(state, &self.fault_policy, &context)
                    .ok_or_else(|| SimulationError::Fault(context.clone()))?;
                let fault = contained
                    .fault_state
                    .get("last_fault")
                    .cloned()
                    .ok_or(SimulationError::RuntimeFault)?;
                let state_digest = contained.digest()?;
                Ok((
                    contained,
                    SimulationTrace {
                        input_order: Vec::new(),
                        candidate_order: Vec::new(),
                        effects: Vec::new(),
                        faults: vec![fault],
                        reduced: Vec::new(),
                        rejected: Vec::new(),
                        receipts: Vec::new(),
                        state_digest,
                    },
                ))
            }
            Err(error) => Err(error),
        }
    }

    fn tick_once(
        &self,
        state: &SimulationState,
        tick: &Value,
    ) -> Result<(SimulationState, SimulationTrace), SimulationError> {
        if state.definition_set_hash != self.definition_set_hash {
            return Err(SimulationError::RuntimeFault);
        }
        let mut work = state.clone();
        let pending_events = work
            .pending_events
            .iter()
            .map(|event| {
                serde_json::from_value::<EventEnvelope>(event.clone())
                    .map_err(|_| SimulationError::RuntimeFault)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let (delivered_events, pending_events) =
            deliver_due(&pending_events, state.tick, &BTreeSet::new())
                .map_err(|_| SimulationError::RuntimeFault)?;
        work.pending_events = pending_events
            .iter()
            .map(|event| serde_json::to_value(event).map_err(|_| SimulationError::RuntimeFault))
            .collect::<Result<Vec<_>, _>>()?;
        for event in delivered_events {
            if matches!(
                event.delivery_mode.as_str(),
                "TARGET_ACTION" | "PARENT" | "CHILD"
            ) {
                let action = work
                    .action_instances
                    .iter_mut()
                    .find(|action| action.instance_id == event.target_id)
                    .ok_or(SimulationError::RuntimeFault)?;
                action
                    .event_inbox
                    .push(serde_json::to_value(event).map_err(|_| SimulationError::RuntimeFault)?);
            }
        }
        let contacts = canonical_contacts(array(tick, "contacts")?)?;
        work.host_state = json!({"contacts": contacts, "imports": {}});

        let inputs = canonical_inputs(array(tick, "inputs")?)?;
        let input_order = inputs
            .iter()
            .map(|input| string_field(input, "input_id").map(str::to_owned))
            .collect::<Result<Vec<_>, _>>()?;
        self.arbitrate_transition_stage(&mut work, &inputs, "PRE_ADVANCE", true)?;
        self.progress_actions(&mut work)?;
        self.arbitrate_transition_stage(&mut work, &inputs, "POST_ADVANCE", false)?;

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
                .cloned()
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
            let candidate_id = string_field(contact, "candidate_id")?;
            let target_entity_id = u64_field(contact, "target_entity_id")?;
            let ledger_context = LedgerContext {
                tick: state.tick,
                source_action_instance_id: instance_id,
                offense_fact_id: binding.fact_id.clone(),
                target_entity_id,
                cycle: action.cycle,
                predicate_entry_serials: action.predicate_entry_serials.clone(),
                contact_partition: string_field(contact, "contact_partition")?.to_owned(),
            };
            if !ledger_is_eligible(
                &work.interaction_ledgers,
                &binding.hit_policy,
                &ledger_context,
            )
            .map_err(|_| SimulationError::RuntimeFault)?
            {
                receipts.push(json!({
                    "accepted": false,
                    "candidate_id": candidate_id,
                    "reason": binding.hit_policy.kind,
                }));
                continue;
            }
            if binding.direction != "OFFENSE" {
                return Err(SimulationError::RuntimeFault);
            }
            let mut receipt_written = false;
            if binding.hit_policy.receipt_on == "ON_CONTACT" {
                receipt_written = write_receipt(
                    &mut work.interaction_ledgers,
                    &binding.hit_policy,
                    &ledger_context,
                    candidate_id,
                )
                .map_err(|_| SimulationError::RuntimeFault)?;
            }
            let offense = SemanticFact {
                fact_id: binding.fact_id.clone(),
                direction: binding.direction.clone(),
                channels: binding.channels.clone(),
                tags: binding.tags.clone(),
                attributes: BTreeMap::new(),
                effect_templates: binding.effect_templates.clone(),
            };
            let defense_fact_id = contact
                .get("defense_fact_id")
                .and_then(Value::as_str)
                .map(str::to_owned);
            let defenses = self
                .defense_map(&work, defense_fact_id.as_deref())
                .map_err(|_| {
                    contextual_runtime_fault(
                        "INVALID_CONTACT",
                        candidate_id,
                        instance_id,
                        action.owner_entity_id,
                    )
                })?;
            let candidate = InteractionCandidate {
                tick: state.tick,
                candidate_id: candidate_id.to_owned(),
                source_entity_id: action.owner_entity_id,
                target_entity_id,
                source_action_instance_id: instance_id,
                offense_fact_id: binding.fact_id.clone(),
                contact_id: string_field(contact, "contact_id")?.to_owned(),
                contact_partition: string_field(contact, "contact_partition")?.to_owned(),
                host_context: serde_json::from_value(contact["host_context"].clone())
                    .map_err(|_| SimulationError::RuntimeFault)?,
                defense_fact_id,
            };
            let decision = resolve_candidate(
                &candidate,
                &offense,
                &defenses,
                &self.interaction_rules,
                self.max_redirects_per_candidate,
                "FAULT",
                self.max_expression_depth,
                self.max_expression_nodes,
            )
            .map_err(|error| {
                interaction_runtime_fault(error, candidate_id, instance_id, action.owner_entity_id)
            })?;
            let accepted = decision.status == "ACCEPTED";
            let impact = decision
                .generated_effects
                .iter()
                .any(|effect| effect.authoritative);
            effects.extend(decision.generated_effects.clone());
            if !receipt_written
                && receipt_required(&binding.hit_policy.receipt_on, accepted, impact)
                    .map_err(|_| SimulationError::RuntimeFault)?
            {
                receipt_written = write_receipt(
                    &mut work.interaction_ledgers,
                    &binding.hit_policy,
                    &ledger_context,
                    candidate_id,
                )
                .map_err(|_| SimulationError::RuntimeFault)?;
            }
            receipts.push(json!({
                "accepted": accepted,
                "candidate_id": candidate_id,
                "decision_tags": decision.decision_tags,
                "receipt_written": receipt_written,
                "redirect_count": decision.redirect_count,
                "rules_fired": decision.trace,
            }));
        }

        let authoritative_effects = effects
            .iter()
            .filter(|effect| effect.authoritative)
            .cloned()
            .collect::<Vec<_>>();
        let (reduced, rejected) =
            reduce_effects(&authoritative_effects).map_err(|_| SimulationError::RuntimeFault)?;
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
        self.finalize_children(&mut work)?;
        for action in &mut work.action_instances {
            action.event_inbox.clear();
        }
        for token in &mut work.freeze_tokens {
            let active = token["activation_tick"]
                .as_u64()
                .is_some_and(|activation| activation <= work.tick);
            if active {
                let remaining = token["remaining_ticks"]
                    .as_u64()
                    .ok_or(SimulationError::RuntimeFault)?;
                token["remaining_ticks"] = json!(remaining.saturating_sub(1));
            }
        }
        work.freeze_tokens.retain(|token| {
            token["remaining_ticks"]
                .as_u64()
                .is_some_and(|remaining| remaining > 0)
        });
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
                faults: Vec::new(),
                reduced,
                rejected,
                receipts,
                state_digest,
            },
        ))
    }

    fn arbitrate_transition_stage(
        &self,
        state: &mut SimulationState,
        inputs: &[Value],
        evaluation_point: &str,
        include_direct_starts: bool,
    ) -> Result<(), SimulationError> {
        let action_ids = state
            .action_instances
            .iter()
            .map(|action| action.instance_id)
            .collect::<Vec<_>>();
        let mut proposals = Vec::new();
        for action_id in action_ids {
            let action = state
                .action_instances
                .iter()
                .find(|action| action.instance_id == action_id)
                .cloned()
                .ok_or(SimulationError::RuntimeFault)?;
            if action.lifecycle_state != "RUNNING" {
                continue;
            }
            let freeze_domain = match evaluation_point {
                "PRE_ADVANCE" => "PRE_ADVANCE_TRANSITIONS",
                "POST_ADVANCE" => "POST_ADVANCE_TRANSITIONS",
                _ => return Err(SimulationError::RuntimeFault),
            };
            if domain_frozen(state, action.instance_id, freeze_domain) {
                continue;
            }
            let definition = self
                .definitions
                .values()
                .find(|definition| definition.hash == action.definition_hash)
                .ok_or(SimulationError::RuntimeFault)?;
            let mut eligible = definition
                .transitions
                .iter()
                .filter(|transition| {
                    transition.source_node == action.current_node_id
                        && transition.evaluation_point == evaluation_point
                })
                .filter(|transition| {
                    transition.input_command.as_ref().is_none_or(|command| {
                        inputs.iter().any(|input| {
                            input
                                .get("command_id")
                                .and_then(Value::as_str)
                                .is_some_and(|value| value == command)
                                && input.get("source_entity_id").and_then(Value::as_u64)
                                    == Some(action.owner_entity_id)
                        })
                    })
                })
                .filter(|transition| {
                    transition.event_type.as_ref().is_none_or(|event_type| {
                        action.event_inbox.iter().any(|event| {
                            event.get("event_type").and_then(Value::as_str)
                                == Some(event_type.as_str())
                        })
                    })
                })
                .cloned()
                .collect::<Vec<_>>();
            eligible.sort_by(|left, right| {
                right
                    .priority
                    .cmp(&left.priority)
                    .then_with(|| left.id.as_bytes().cmp(right.id.as_bytes()))
            });
            let Some(transition) = eligible.into_iter().next() else {
                continue;
            };
            let matched_input = transition.input_command.as_ref().and_then(|command| {
                inputs.iter().find(|input| {
                    input.get("command_id").and_then(Value::as_str) == Some(command.as_str())
                        && input.get("source_entity_id").and_then(Value::as_u64)
                            == Some(action.owner_entity_id)
                })
            });
            proposals.push((
                action,
                transition,
                matched_input
                    .and_then(|input| input.get("sequence"))
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                matched_input
                    .and_then(|input| input.get("input_id"))
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .unwrap_or_else(|| format!("internal:{}:{action_id}", state.tick)),
            ));
        }
        let mut arbitration = self.arbitration_state(state)?;
        let mut intents = Vec::new();
        for (action, transition, input_sequence, input_id) in &proposals {
            let capacity_key = (
                "CAPACITY".to_owned(),
                action.owner_entity_id,
                "ACTIONS".to_owned(),
            );
            arbitration
                .capacities
                .insert(capacity_key.clone(), self.max_actions_per_entity);
            arbitration.usages.insert(
                capacity_key,
                state
                    .action_instances
                    .iter()
                    .filter(|item| {
                        item.owner_entity_id == action.owner_entity_id
                            && !matches!(item.lifecycle_state.as_str(), "TERMINATED" | "FAULTED")
                    })
                    .count() as u64,
            );
            let mut claims = transition.claims.clone();
            let mut releases = Vec::new();
            if matches!(transition.target_kind.as_str(), "ACTION" | "CHILD_ACTION") {
                let target = self
                    .definitions
                    .get(
                        transition
                            .target_action
                            .as_ref()
                            .ok_or(SimulationError::RuntimeFault)?,
                    )
                    .ok_or(SimulationError::RuntimeFault)?;
                claims.extend(target.start_claims.clone());
                claims.extend(target.slot_claims.clone());
                claims.push(ArbitrationClaim {
                    kind: "CAPACITY".to_owned(),
                    key: "ACTIONS".to_owned(),
                    amount: 1,
                    owner_id: None,
                });
                if transition.target_kind == "CHILD_ACTION" {
                    let child_slot = transition
                        .child_slot_id
                        .clone()
                        .ok_or(SimulationError::RuntimeFault)?;
                    let source_definition = self
                        .definitions
                        .values()
                        .find(|definition| definition.hash == action.definition_hash)
                        .ok_or(SimulationError::RuntimeFault)?;
                    let capacity = source_definition
                        .child_slot_capacities
                        .get(&child_slot)
                        .copied()
                        .ok_or(SimulationError::RuntimeFault)?;
                    let child_key = (
                        "CHILD_SLOT".to_owned(),
                        action.instance_id,
                        child_slot.clone(),
                    );
                    arbitration.capacities.insert(child_key.clone(), capacity);
                    arbitration.usages.insert(
                        child_key,
                        action
                            .child_instance_ids
                            .iter()
                            .filter(|child_id| {
                                state.action_instances.iter().any(|child| {
                                    child.instance_id == **child_id
                                        && !matches!(
                                            child.lifecycle_state.as_str(),
                                            "TERMINATED" | "FAULTED"
                                        )
                                })
                            })
                            .count() as u64,
                    );
                    claims.push(ArbitrationClaim {
                        kind: "CHILD_SLOT".to_owned(),
                        key: child_slot,
                        amount: 1,
                        owner_id: Some(action.instance_id),
                    });
                }
                if transition.target_kind == "ACTION"
                    && transition.source_disposition == "TERMINATE_SOURCE"
                {
                    releases.push(ArbitrationClaim {
                        kind: "CAPACITY".to_owned(),
                        key: "ACTIONS".to_owned(),
                        amount: 1,
                        owner_id: None,
                    });
                    releases.extend(
                        action
                            .slot_claims
                            .iter()
                            .map(|claim| {
                                serde_json::from_value::<ArbitrationClaim>(claim.clone())
                                    .map_err(|_| SimulationError::RuntimeFault)
                            })
                            .collect::<Result<Vec<_>, _>>()?,
                    );
                }
            }
            intents.push(ArbitrationIntent {
                intent_kind: "TRANSITION".to_owned(),
                intent_priority: transition.priority,
                owner_entity_id: action.owner_entity_id,
                source_action_instance_id: action.instance_id,
                transition_id: transition.id.clone(),
                input_sequence: *input_sequence,
                input_id: input_id.clone(),
                claims,
                releases,
                operations: vec![json!({"transition": transition.id})],
                atomic_group_id: "default".to_owned(),
            });
        }
        if include_direct_starts {
            for input in inputs {
                if string_field(input, "command_id")? != "START" {
                    continue;
                }
                let definition_id = string_field(input, "action_definition_id")?;
                let definition = self
                    .definitions
                    .get(definition_id)
                    .ok_or(SimulationError::RuntimeFault)?;
                let owner = u64_field(input, "source_entity_id")?;
                let capacity_key = ("CAPACITY".to_owned(), owner, "ACTIONS".to_owned());
                arbitration
                    .capacities
                    .insert(capacity_key.clone(), self.max_actions_per_entity);
                arbitration.usages.insert(
                    capacity_key,
                    state
                        .action_instances
                        .iter()
                        .filter(|action| {
                            action.owner_entity_id == owner
                                && !matches!(
                                    action.lifecycle_state.as_str(),
                                    "TERMINATED" | "FAULTED"
                                )
                        })
                        .count() as u64,
                );
                let mut claims = definition.start_claims.clone();
                claims.extend(definition.slot_claims.clone());
                claims.push(ArbitrationClaim {
                    kind: "CAPACITY".to_owned(),
                    key: "ACTIONS".to_owned(),
                    amount: 1,
                    owner_id: None,
                });
                intents.push(ArbitrationIntent {
                    intent_kind: "ACTION_START".to_owned(),
                    intent_priority: 0,
                    owner_entity_id: owner,
                    source_action_instance_id: 0,
                    transition_id: definition_id.to_owned(),
                    input_sequence: u64_field(input, "sequence")?,
                    input_id: string_field(input, "input_id")?.to_owned(),
                    claims,
                    releases: Vec::new(),
                    operations: vec![json!({"start_action": definition_id})],
                    atomic_group_id: "default".to_owned(),
                });
            }
        }
        if intents.is_empty() {
            return Ok(());
        }
        let (reserved, decisions) =
            arbitrate_intents(&intents, &arbitration).map_err(|_| SimulationError::RuntimeFault)?;
        self.commit_reserved_resources(state, reserved.resource_banks)?;
        for decision in decisions {
            if !decision.accepted {
                continue;
            }
            match decision.intent.intent_kind.as_str() {
                "TRANSITION" => {
                    let (_, transition, _, _) = proposals
                        .iter()
                        .find(|(action, transition, _, _)| {
                            action.instance_id == decision.intent.source_action_instance_id
                                && transition.id == decision.intent.transition_id
                        })
                        .ok_or(SimulationError::RuntimeFault)?;
                    self.apply_simulation_transition(
                        state,
                        decision.intent.source_action_instance_id,
                        transition,
                    )?;
                }
                "ACTION_START" => self.start_direct_action(
                    state,
                    &decision.intent.transition_id,
                    decision.intent.owner_entity_id,
                )?,
                _ => return Err(SimulationError::RuntimeFault),
            }
        }
        self.rebuild_action_slots(state)
    }

    fn defense_map(
        &self,
        state: &SimulationState,
        required_fact_id: Option<&str>,
    ) -> Result<BTreeMap<u64, Option<SemanticFact>>, SimulationError> {
        let mut by_target = BTreeMap::<u64, Vec<(u64, SemanticFact)>>::new();
        for action in &state.action_instances {
            if action.lifecycle_state != "RUNNING"
                || domain_frozen(state, action.instance_id, "INTERACTION_RECEPTION")
            {
                continue;
            }
            let definition = self
                .definitions
                .values()
                .find(|definition| definition.hash == action.definition_hash)
                .ok_or(SimulationError::RuntimeFault)?;
            for binding in &definition.facts {
                if binding.direction != "DEFENSE"
                    || required_fact_id.is_some_and(|fact_id| binding.fact_id != fact_id)
                    || !action
                        .predicate_truth_state
                        .get(&binding.when_predicate)
                        .copied()
                        .unwrap_or(false)
                {
                    continue;
                }
                by_target.entry(action.owner_entity_id).or_default().push((
                    action.instance_id,
                    SemanticFact {
                        fact_id: binding.fact_id.clone(),
                        direction: binding.direction.clone(),
                        channels: binding.channels.clone(),
                        tags: binding.tags.clone(),
                        attributes: BTreeMap::new(),
                        effect_templates: binding.effect_templates.clone(),
                    },
                ));
            }
        }
        let mut defenses = BTreeMap::new();
        for (target_entity_id, mut options) in by_target {
            options.sort_by(|left, right| {
                left.0
                    .cmp(&right.0)
                    .then_with(|| left.1.fact_id.as_bytes().cmp(right.1.fact_id.as_bytes()))
            });
            if options.len() > 1 {
                return Err(SimulationError::RuntimeFault);
            }
            defenses.insert(
                target_entity_id,
                options.into_iter().next().map(|(_, fact)| fact),
            );
        }
        Ok(defenses)
    }

    fn arbitration_state(
        &self,
        state: &SimulationState,
    ) -> Result<ArbitrationState, SimulationError> {
        let mut arbitration = ArbitrationState::default();
        for (owner, bank) in &state.resource_banks {
            let owner = owner
                .parse::<u64>()
                .map_err(|_| SimulationError::RuntimeFault)?;
            arbitration.resource_banks.insert(
                owner,
                bank.iter()
                    .map(|(resource, value)| {
                        Ok((
                            resource.clone(),
                            u64::try_from(*value).map_err(|_| SimulationError::RuntimeFault)?,
                        ))
                    })
                    .collect::<Result<BTreeMap<_, _>, SimulationError>>()?,
            );
        }
        for (owner, slots) in &state.action_slots {
            let owner = owner
                .parse::<u64>()
                .map_err(|_| SimulationError::RuntimeFault)?;
            for (slot, value) in slots.as_object().ok_or(SimulationError::RuntimeFault)? {
                let key = ("ACTION_SLOT".to_owned(), owner, slot.clone());
                arbitration.capacities.insert(
                    key.clone(),
                    value["capacity"]
                        .as_u64()
                        .ok_or(SimulationError::RuntimeFault)?,
                );
                arbitration.usages.insert(
                    key,
                    value["usage"]
                        .as_u64()
                        .ok_or(SimulationError::RuntimeFault)?,
                );
            }
        }
        Ok(arbitration)
    }

    fn commit_reserved_resources(
        &self,
        state: &mut SimulationState,
        resources: BTreeMap<u64, BTreeMap<String, u64>>,
    ) -> Result<(), SimulationError> {
        state.resource_banks = resources
            .into_iter()
            .map(|(owner, bank)| {
                Ok((
                    owner.to_string(),
                    bank.into_iter()
                        .map(|(resource, value)| {
                            Ok((
                                resource,
                                i64::try_from(value).map_err(|_| SimulationError::RuntimeFault)?,
                            ))
                        })
                        .collect::<Result<BTreeMap<_, _>, SimulationError>>()?,
                ))
            })
            .collect::<Result<BTreeMap<_, _>, SimulationError>>()?;
        Ok(())
    }

    fn start_direct_action(
        &self,
        state: &mut SimulationState,
        definition_id: &str,
        owner_entity_id: u64,
    ) -> Result<(), SimulationError> {
        let definition = self
            .definitions
            .get(definition_id)
            .ok_or(SimulationError::RuntimeFault)?;
        let instance_id = state.next_action_instance_id;
        state.next_action_instance_id = instance_id
            .checked_add(1)
            .ok_or(SimulationError::RuntimeFault)?;
        state.action_instances.push(ActionSnapshot {
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
            lifecycle_state: if definition
                .nodes
                .get(&definition.initial_node)
                .is_some_and(|mode| mode == "TERMINAL")
            {
                "TERMINATED".to_owned()
            } else {
                "RUNNING".to_owned()
            },
            local_step: 0,
            node_step: 0,
            owner_entity_id,
            parent_instance_id: None,
            parent_slot_id: None,
            predicate_entry_serials: BTreeMap::new(),
            predicate_exit_serials: BTreeMap::new(),
            predicate_truth_state: BTreeMap::new(),
            quantum_accumulator: 0,
            registers: BTreeMap::new(),
            rng_stream_ids: Vec::new(),
            slot_claims: definition
                .slot_claims
                .iter()
                .map(|claim| {
                    json!({
                        "amount": claim.amount,
                        "key": claim.key,
                        "kind": claim.kind,
                    })
                })
                .collect(),
            transition_serial: 0,
        });
        state
            .action_instances
            .sort_by_key(|action| action.instance_id);
        Ok(())
    }

    fn rebuild_action_slots(&self, state: &mut SimulationState) -> Result<(), SimulationError> {
        for slots in state.action_slots.values_mut() {
            for value in slots
                .as_object_mut()
                .ok_or(SimulationError::RuntimeFault)?
                .values_mut()
            {
                value["instance_ids"] = Value::Array(Vec::new());
                value["usage"] = json!(0);
            }
        }
        for action in &state.action_instances {
            if matches!(action.lifecycle_state.as_str(), "TERMINATED" | "FAULTED") {
                continue;
            }
            let entity = action.owner_entity_id.to_string();
            for claim in &action.slot_claims {
                if claim["kind"] != "ACTION_SLOT" {
                    continue;
                }
                let slot = claim["key"].as_str().ok_or(SimulationError::RuntimeFault)?;
                let value = state
                    .action_slots
                    .get_mut(&entity)
                    .and_then(Value::as_object_mut)
                    .and_then(|slots| slots.get_mut(slot))
                    .ok_or(SimulationError::RuntimeFault)?;
                value["instance_ids"]
                    .as_array_mut()
                    .ok_or(SimulationError::RuntimeFault)?
                    .push(json!(action.instance_id));
                let usage = value["usage"]
                    .as_u64()
                    .ok_or(SimulationError::RuntimeFault)?;
                value["usage"] = json!(usage + claim["amount"].as_u64().unwrap_or(1));
            }
        }
        Ok(())
    }

    fn progress_actions(&self, state: &mut SimulationState) -> Result<(), SimulationError> {
        let action_ids = state
            .action_instances
            .iter()
            .map(|action| action.instance_id)
            .collect::<Vec<_>>();
        for action_id in action_ids {
            let index = state
                .action_instances
                .iter()
                .position(|action| action.instance_id == action_id)
                .ok_or(SimulationError::RuntimeFault)?;
            if state.action_instances[index].lifecycle_state != "RUNNING" {
                continue;
            }
            if domain_frozen(state, action_id, "PROGRESSION") {
                continue;
            }
            let definition = self
                .definitions
                .values()
                .find(|definition| definition.hash == state.action_instances[index].definition_hash)
                .ok_or(SimulationError::RuntimeFault)?;
            let accumulated = state.action_instances[index]
                .quantum_accumulator
                .checked_add(state.action_instances[index].current_rate_units)
                .ok_or(SimulationError::RuntimeFault)?;
            let quanta = accumulated / definition.rate_scale;
            if quanta > self.max_quanta_per_action_per_tick {
                return Err(SimulationError::Fault(FaultContext {
                    code: "RUNTIME_FAULT".to_owned(),
                    fault: "QUANTUM_LIMIT_EXCEEDED".to_owned(),
                    message: action_id.to_string(),
                    action_instance_id: Some(action_id),
                    owner_entity_id: Some(state.action_instances[index].owner_entity_id),
                }));
            }
            state.action_instances[index].quantum_accumulator = accumulated % definition.rate_scale;
            for _ in 0..quanta {
                let action = &mut state.action_instances[index];
                action.local_step = action
                    .local_step
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                action.node_step = action
                    .node_step
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                let mut eligible = definition
                    .transitions
                    .iter()
                    .filter(|transition| {
                        transition.source_node == action.current_node_id
                            && transition.evaluation_point == "AFTER_QUANTUM"
                    })
                    .cloned()
                    .collect::<Vec<_>>();
                eligible.sort_by(|left, right| {
                    right
                        .priority
                        .cmp(&left.priority)
                        .then_with(|| left.id.as_bytes().cmp(right.id.as_bytes()))
                });
                if let Some(transition) = eligible.into_iter().next() {
                    self.apply_simulation_transition(state, action_id, &transition)?;
                }
                if state.action_instances[index].lifecycle_state != "RUNNING" {
                    break;
                }
            }
        }
        Ok(())
    }

    fn apply_simulation_transition(
        &self,
        state: &mut SimulationState,
        action_id: u64,
        transition: &SimulationTransition,
    ) -> Result<(), SimulationError> {
        let index = state
            .action_instances
            .iter()
            .position(|action| action.instance_id == action_id)
            .ok_or(SimulationError::RuntimeFault)?;
        state.action_instances[index].cycle = state.action_instances[index]
            .cycle
            .checked_add(transition.cycle_delta)
            .ok_or(SimulationError::RuntimeFault)?;
        match transition.target_kind.as_str() {
            "NODE" => {
                let target = transition
                    .target_node
                    .as_ref()
                    .ok_or(SimulationError::RuntimeFault)?;
                let definition = self
                    .definitions
                    .values()
                    .find(|definition| {
                        definition.hash == state.action_instances[index].definition_hash
                    })
                    .ok_or(SimulationError::RuntimeFault)?;
                state.action_instances[index].current_node_id = target.clone();
                state.action_instances[index].node_step = 0;
                state.action_instances[index].transition_serial = state.action_instances[index]
                    .transition_serial
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                if definition
                    .nodes
                    .get(target)
                    .is_some_and(|mode| mode == "TERMINAL")
                {
                    self.terminate_action(state, action_id, "TERMINATED", None)?;
                }
            }
            "TERMINATE" => {
                state.action_instances[index].transition_serial = state.action_instances[index]
                    .transition_serial
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                self.terminate_action(state, action_id, "TERMINATED", None)?;
            }
            "FAULT" => {
                state.action_instances[index].transition_serial = state.action_instances[index]
                    .transition_serial
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                state.action_instances[index].fault_record = Some(transition.id.clone());
                self.terminate_action(state, action_id, "FAULTED", None)?;
            }
            "ACTION" => {
                let target_action = transition
                    .target_action
                    .as_ref()
                    .ok_or(SimulationError::RuntimeFault)?;
                let definition = self
                    .definitions
                    .get(target_action)
                    .ok_or(SimulationError::RuntimeFault)?;
                let owner_entity_id = state.action_instances[index].owner_entity_id;
                state.action_instances[index].transition_serial = state.action_instances[index]
                    .transition_serial
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                match transition.source_disposition.as_str() {
                    "TERMINATE_SOURCE" => {
                        self.terminate_action(state, action_id, "TERMINATED", None)?;
                    }
                    "SUSPEND_SOURCE" => {
                        state.action_instances[index].lifecycle_state = "SUSPENDED".to_owned();
                    }
                    "KEEP_SOURCE" => {}
                    _ => return Err(SimulationError::RuntimeFault),
                }
                let instance_id = state.next_action_instance_id;
                state.next_action_instance_id = instance_id
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                state.action_instances.push(ActionSnapshot {
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
                    lifecycle_state: if definition
                        .nodes
                        .get(&definition.initial_node)
                        .is_some_and(|mode| mode == "TERMINAL")
                    {
                        "TERMINATED".to_owned()
                    } else {
                        "RUNNING".to_owned()
                    },
                    local_step: 0,
                    node_step: 0,
                    owner_entity_id,
                    parent_instance_id: None,
                    parent_slot_id: None,
                    predicate_entry_serials: BTreeMap::new(),
                    predicate_exit_serials: BTreeMap::new(),
                    predicate_truth_state: BTreeMap::new(),
                    quantum_accumulator: 0,
                    registers: BTreeMap::new(),
                    rng_stream_ids: Vec::new(),
                    slot_claims: definition
                        .slot_claims
                        .iter()
                        .map(|claim| {
                            json!({
                                "amount": claim.amount,
                                "key": claim.key,
                                "kind": claim.kind,
                            })
                        })
                        .collect(),
                    transition_serial: 0,
                });
                state
                    .action_instances
                    .sort_by_key(|action| action.instance_id);
            }
            "CHILD_ACTION" => {
                let target_action = transition
                    .target_action
                    .as_ref()
                    .ok_or(SimulationError::RuntimeFault)?;
                let child_slot = transition
                    .child_slot_id
                    .as_ref()
                    .ok_or(SimulationError::RuntimeFault)?;
                let parent_definition = self
                    .definitions
                    .values()
                    .find(|definition| {
                        definition.hash == state.action_instances[index].definition_hash
                    })
                    .ok_or(SimulationError::RuntimeFault)?;
                let capacity = parent_definition
                    .child_slot_capacities
                    .get(child_slot)
                    .copied()
                    .ok_or(SimulationError::RuntimeFault)?;
                let active_children = state.action_instances[index]
                    .child_instance_ids
                    .iter()
                    .filter(|child_id| {
                        state.action_instances.iter().any(|child| {
                            child.instance_id == **child_id
                                && !matches!(
                                    child.lifecycle_state.as_str(),
                                    "TERMINATED" | "FAULTED"
                                )
                        })
                    })
                    .count() as u64;
                if active_children >= capacity {
                    return Err(SimulationError::RuntimeFault);
                }
                let mut depth = 1_u64;
                let mut cursor = state.action_instances[index].parent_instance_id;
                while let Some(parent_id) = cursor {
                    depth = depth.checked_add(1).ok_or(SimulationError::RuntimeFault)?;
                    cursor = state
                        .action_instances
                        .iter()
                        .find(|action| action.instance_id == parent_id)
                        .ok_or(SimulationError::RuntimeFault)?
                        .parent_instance_id;
                }
                if depth >= self.max_action_nesting_depth {
                    return Err(SimulationError::Fault(FaultContext {
                        code: "RUNTIME_FAULT".to_owned(),
                        fault: "NESTING_LIMIT_EXCEEDED".to_owned(),
                        message: target_action.clone(),
                        action_instance_id: Some(action_id),
                        owner_entity_id: Some(state.action_instances[index].owner_entity_id),
                    }));
                }
                let definition = self
                    .definitions
                    .get(target_action)
                    .ok_or(SimulationError::RuntimeFault)?;
                let child_id = state.next_action_instance_id;
                state.next_action_instance_id = child_id
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                let owner_entity_id = state.action_instances[index].owner_entity_id;
                state.action_instances[index].transition_serial = state.action_instances[index]
                    .transition_serial
                    .checked_add(1)
                    .ok_or(SimulationError::RuntimeFault)?;
                state.action_instances[index]
                    .child_instance_ids
                    .push(child_id);
                let parent_policy = transition
                    .parent_policy
                    .as_deref()
                    .ok_or(SimulationError::RuntimeFault)?;
                let domains: &[&str] = match parent_policy {
                    "CONTINUE" | "TERMINATE_PARENT" => &[],
                    "FREEZE_PROGRESSION" => &["PROGRESSION"],
                    "FREEZE_TRANSITIONS" => {
                        &["PRE_ADVANCE_TRANSITIONS", "POST_ADVANCE_TRANSITIONS"]
                    }
                    "FREEZE_ALL_ACTION_LOGIC" => &[
                        "PROGRESSION",
                        "PRE_ADVANCE_TRANSITIONS",
                        "POST_ADVANCE_TRANSITIONS",
                        "INPUT_CAPTURE",
                        "INTERACTION_EMISSION",
                        "INTERACTION_RECEPTION",
                    ],
                    _ => return Err(SimulationError::RuntimeFault),
                };
                if !domains.is_empty() {
                    let mut domains = domains.to_vec();
                    domains.sort_unstable();
                    let token_id = state.next_freeze_token_id;
                    state.next_freeze_token_id = token_id
                        .checked_add(1)
                        .ok_or(SimulationError::RuntimeFault)?;
                    state.action_instances[index]
                        .freeze_token_references
                        .push(token_id);
                    state.freeze_tokens.push(json!({
                        "accrual_policy": "HOLD",
                        "activation_tick": state.tick + 1,
                        "domains": domains,
                        "metadata": {"child_slot_id": child_slot, "relationship": "PARENT_CHILD"},
                        "remaining_ticks": u64::MAX,
                        "source_id": child_id,
                        "stack_group": "default",
                        "stack_policy": "INDEPENDENT",
                        "target_id": action_id,
                        "token_id": token_id,
                    }));
                }
                state.action_instances.push(ActionSnapshot {
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
                    instance_id: child_id,
                    interaction_ledger_partition: "default".to_owned(),
                    lifecycle_state: "RUNNING".to_owned(),
                    local_step: 0,
                    node_step: 0,
                    owner_entity_id,
                    parent_instance_id: Some(action_id),
                    parent_slot_id: Some(child_slot.clone()),
                    predicate_entry_serials: BTreeMap::new(),
                    predicate_exit_serials: BTreeMap::new(),
                    predicate_truth_state: BTreeMap::new(),
                    quantum_accumulator: 0,
                    registers: BTreeMap::new(),
                    rng_stream_ids: Vec::new(),
                    slot_claims: Vec::new(),
                    transition_serial: 0,
                });
                if parent_policy == "TERMINATE_PARENT" {
                    self.terminate_action(state, action_id, "TERMINATED", Some(child_id))?;
                }
                state
                    .action_instances
                    .sort_by_key(|action| action.instance_id);
            }
            _ => return Err(SimulationError::RuntimeFault),
        }
        Ok(())
    }

    fn finalize_children(&self, state: &mut SimulationState) -> Result<(), SimulationError> {
        let child_ids = state
            .action_instances
            .iter()
            .filter(|action| {
                action.parent_instance_id.is_some()
                    && matches!(action.lifecycle_state.as_str(), "TERMINATED" | "FAULTED")
                    && action.extension_state.get("pcam.child_result_emitted") != Some(&json!(true))
            })
            .map(|action| action.instance_id)
            .collect::<Vec<_>>();
        for child_id in child_ids {
            let child_index = state
                .action_instances
                .iter()
                .position(|action| action.instance_id == child_id)
                .ok_or(SimulationError::RuntimeFault)?;
            let parent_id = state.action_instances[child_index]
                .parent_instance_id
                .ok_or(SimulationError::RuntimeFault)?;
            let parent_index = state
                .action_instances
                .iter()
                .position(|action| action.instance_id == parent_id)
                .ok_or(SimulationError::RuntimeFault)?;
            let child_slot_id = state.action_instances[child_index].parent_slot_id.clone();
            let transition_serial = state.action_instances[child_index].transition_serial;
            let event = EventEnvelope {
                event_id: format!("child-result:{child_id}:{transition_serial}"),
                event_type: "CHILD_RESULT".to_owned(),
                source_id: child_id,
                target_id: parent_id,
                origin_tick: state.tick,
                delivery_tick: state.tick + 1,
                payload: json!({
                    "child_instance_id": child_id,
                    "child_slot_id": child_slot_id,
                    "parent_instance_id": parent_id,
                    "result_code": if state.action_instances[child_index].lifecycle_state == "FAULTED" {
                        state.action_instances[child_index].fault_record.clone().unwrap_or_else(|| "FAULTED".to_owned())
                    } else {
                        "TERMINATED".to_owned()
                    },
                    "termination_tick": state.tick,
                }),
                delivery_mode: "PARENT".to_owned(),
            };
            state
                .pending_events
                .push(serde_json::to_value(event).map_err(|_| SimulationError::RuntimeFault)?);
            state.action_instances[parent_index]
                .child_instance_ids
                .retain(|value| *value != child_id);
            let removed_tokens = state
                .freeze_tokens
                .iter()
                .filter(|token| {
                    token.get("source_id").and_then(Value::as_u64) == Some(child_id)
                        && token.get("target_id").and_then(Value::as_u64) == Some(parent_id)
                        && token
                            .get("metadata")
                            .and_then(|metadata| metadata.get("relationship"))
                            .and_then(Value::as_str)
                            == Some("PARENT_CHILD")
                })
                .filter_map(|token| token.get("token_id").and_then(Value::as_u64))
                .collect::<BTreeSet<_>>();
            state.action_instances[parent_index]
                .freeze_token_references
                .retain(|token_id| !removed_tokens.contains(token_id));
            state.freeze_tokens.retain(|token| {
                token
                    .get("token_id")
                    .and_then(Value::as_u64)
                    .is_none_or(|token_id| !removed_tokens.contains(&token_id))
            });
            state.action_instances[child_index]
                .extension_state
                .insert("pcam.child_result_emitted".to_owned(), json!(true));
        }
        state.pending_events.sort_by(|left, right| {
            (
                left["delivery_tick"].as_u64().unwrap_or_default(),
                left["target_id"].as_u64().unwrap_or_default(),
                left["event_id"].as_str().unwrap_or_default(),
            )
                .cmp(&(
                    right["delivery_tick"].as_u64().unwrap_or_default(),
                    right["target_id"].as_u64().unwrap_or_default(),
                    right["event_id"].as_str().unwrap_or_default(),
                ))
        });
        Ok(())
    }

    fn terminate_action(
        &self,
        state: &mut SimulationState,
        action_id: u64,
        lifecycle: &str,
        exempt_child_id: Option<u64>,
    ) -> Result<(), SimulationError> {
        let index = state
            .action_instances
            .iter()
            .position(|action| action.instance_id == action_id)
            .ok_or(SimulationError::RuntimeFault)?;
        let action = state.action_instances[index].clone();
        let definition = self
            .definitions
            .values()
            .find(|definition| definition.hash == action.definition_hash)
            .ok_or(SimulationError::RuntimeFault)?;
        let mut retained = Vec::new();
        for child_id in action.child_instance_ids {
            if Some(child_id) == exempt_child_id {
                retained.push(child_id);
                continue;
            }
            let child_index = state
                .action_instances
                .iter()
                .position(|child| child.instance_id == child_id)
                .ok_or(SimulationError::RuntimeFault)?;
            let slot = state.action_instances[child_index]
                .parent_slot_id
                .as_ref()
                .ok_or(SimulationError::RuntimeFault)?;
            let policy = definition
                .child_termination_policies
                .get(slot)
                .ok_or(SimulationError::RuntimeFault)?;
            match policy.as_str() {
                "TERMINATE_CHILD" => {
                    self.terminate_action(state, child_id, "TERMINATED", None)?;
                    retained.push(child_id);
                }
                "DETACH_CHILD" => {
                    state.action_instances[child_index].parent_instance_id = None;
                    state.action_instances[child_index].parent_slot_id = None;
                }
                "ALLOW_CHILD_TO_COMPLETE" => retained.push(child_id),
                "FAULT_IF_OCCUPIED" => return Err(SimulationError::RuntimeFault),
                _ => return Err(SimulationError::RuntimeFault),
            }
        }
        let index = state
            .action_instances
            .iter()
            .position(|action| action.instance_id == action_id)
            .ok_or(SimulationError::RuntimeFault)?;
        state.action_instances[index].child_instance_ids = retained;
        state.action_instances[index].lifecycle_state = lifecycle.to_owned();
        state
            .freeze_tokens
            .retain(|token| token.get("target_id").and_then(Value::as_u64) != Some(action_id));
        Ok(())
    }
}

fn contextual_runtime_fault(
    fault: &str,
    message: &str,
    action_instance_id: u64,
    owner_entity_id: u64,
) -> SimulationError {
    SimulationError::Fault(FaultContext {
        code: "RUNTIME_FAULT".to_owned(),
        fault: fault.to_owned(),
        message: message.to_owned(),
        action_instance_id: Some(action_instance_id),
        owner_entity_id: Some(owner_entity_id),
    })
}

fn interaction_runtime_fault(
    error: InteractionError,
    candidate_id: &str,
    action_instance_id: u64,
    owner_entity_id: u64,
) -> SimulationError {
    let fault = match error {
        InteractionError::DivisionByZero => "DIVISION_BY_ZERO",
        InteractionError::IntegerOverflow => "INTEGER_OVERFLOW",
        InteractionError::RedirectLimitExceeded => "REDIRECT_LIMIT_EXCEEDED",
        InteractionError::DefinitionRejected | InteractionError::StateInvariant => {
            "STATE_INVARIANT_FAILURE"
        }
    };
    contextual_runtime_fault(fault, candidate_id, action_instance_id, owner_entity_id)
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
    let transitions = raw
        .get("transitions")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(canonical_transition)
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
        "slot_claims": canonical_claims(raw.get("slot_claims"))?,
        "start_claims": canonical_claims(raw.get("start_claims"))?,
        "transitions": transitions,
    }))
}

fn canonical_transition(raw: &Value) -> Result<Value, SimulationError> {
    let effects = raw
        .get("effects")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|effect| {
            json!({
                "amount": effect.get("amount").cloned().unwrap_or_else(|| json!(0)),
                "effect_class": effect.get("effect_class").cloned().unwrap_or_else(|| json!("RESOURCE")),
                "id": effect["id"].clone(),
                "kind": effect.get("kind").cloned().unwrap_or_else(|| json!("RESOURCE_DELTA")),
                "origin_tick": effect.get("origin_tick").cloned().unwrap_or_else(|| json!(0)),
                "priority": effect.get("priority").cloned().unwrap_or_else(|| json!(0)),
                "resource": effect.get("resource").cloned().unwrap_or_else(|| json!("hp")),
                "source_action_instance_id": effect.get("source_action_instance_id").cloned().unwrap_or_else(|| json!(0)),
                "source_entity_id": effect.get("source_entity_id").cloned().unwrap_or_else(|| json!(0)),
                "target_entity_id": effect.get("target_entity_id").cloned().unwrap_or_else(|| json!(0)),
            })
        })
        .collect::<Vec<_>>();
    Ok(json!({
        "assignments": raw.get("assignments").cloned().unwrap_or_else(|| json!([])),
        "child_slot_id": raw.get("child_slot_id").cloned().unwrap_or(Value::Null),
        "claims": canonical_claims(raw.get("claims"))?,
        "consume_policy": raw.get("consume_policy").cloned().unwrap_or_else(|| json!("ON_ACCEPT")),
        "cycle_delta": raw.get("cycle_delta").cloned().unwrap_or_else(|| json!(0)),
        "definition_effects": raw.get("definition_effects").cloned().unwrap_or_else(|| json!([])),
        "effects": effects,
        "entry_assignments": raw.get("entry_assignments").cloned().unwrap_or_else(|| json!([])),
        "evaluation_point": raw["evaluation_point"].clone(),
        "event_type": raw.get("event_type").cloned().unwrap_or(Value::Null),
        "exit_assignments": raw.get("exit_assignments").cloned().unwrap_or_else(|| json!([])),
        "guard_expression": raw.get("guard_expression").cloned().unwrap_or(Value::Null),
        "guard_predicate": raw.get("guard_predicate").cloned().unwrap_or(Value::Null),
        "id": raw["id"].clone(),
        "input_command": raw.get("input_command").cloned().unwrap_or(Value::Null),
        "metadata": raw.get("metadata").cloned().unwrap_or_else(|| json!({})),
        "parent_policy": raw.get("parent_policy").cloned().unwrap_or(Value::Null),
        "priority": raw["priority"].clone(),
        "source_disposition": raw.get("source_disposition").cloned().unwrap_or_else(|| json!("TERMINATE_SOURCE")),
        "source_node": raw["source_node"].clone(),
        "target_action": raw.get("target_action").cloned().unwrap_or(Value::Null),
        "target_kind": raw.get("target_kind").cloned().unwrap_or_else(|| json!("NODE")),
        "target_node": raw.get("target_node").cloned().unwrap_or(Value::Null),
        "target_step": raw.get("target_step").cloned().unwrap_or_else(|| json!(0)),
    }))
}

fn canonical_claims(raw: Option<&Value>) -> Result<Value, SimulationError> {
    let claims = raw
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|claim| {
            Ok(json!({
                "amount": claim.get("amount").and_then(Value::as_u64).unwrap_or(1),
                "key": string_field(claim, "key")?,
                "kind": string_field(claim, "kind")?,
                "owner_id": claim.get("owner_id").cloned().unwrap_or(Value::Null),
            }))
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    Ok(Value::Array(claims))
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
                        let mut data = operation
                            .get("data")
                            .and_then(Value::as_object)
                            .cloned()
                            .unwrap_or_default();
                        for key in ["template", "replacement"] {
                            if let Some(template) = data.get(key).cloned() {
                                data.insert(key.to_owned(), canonical_interaction_template(&template));
                            }
                        }
                        json!({
                            "data": data,
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

fn canonical_interaction_template(template: &Value) -> Value {
    json!({
        "authoritative": template.get("authoritative").cloned().unwrap_or_else(|| json!(true)),
        "effect_class": template["effect_class"].clone(),
        "effect_type": template["effect_type"].clone(),
        "payload": template["payload"].clone(),
        "priority": template.get("priority").cloned().unwrap_or_else(|| json!(0)),
        "reducer": template.get("reducer").cloned().unwrap_or_else(|| json!("ORDERED")),
    })
}

fn parse_definition(raw: &Value, hash: String) -> Result<Definition, SimulationError> {
    let nodes = array(raw, "nodes")?
        .iter()
        .map(|node| {
            Ok((
                string_field(node, "id")?.to_owned(),
                node.get("mode")
                    .and_then(Value::as_str)
                    .unwrap_or("EVENT_DRIVEN")
                    .to_owned(),
            ))
        })
        .collect::<Result<BTreeMap<_, _>, SimulationError>>()?;
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
                    Ok(InteractionEffectTemplate {
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
                direction: string_field(fact, "direction")?.to_owned(),
                channels: fact
                    .get("channels")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|value| string(value).map(str::to_owned))
                    .collect::<Result<Vec<_>, _>>()?,
                tags: fact
                    .get("tags")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|value| string(value).map(str::to_owned))
                    .collect::<Result<Vec<_>, _>>()?,
                when_predicate: string_field(binding, "when_predicate")?.to_owned(),
                effect_templates,
                hit_policy: {
                    let policy = serde_json::from_value::<LedgerHitPolicy>(policy.clone())
                        .map_err(|_| SimulationError::InvalidVector)?;
                    policy
                        .validate()
                        .map_err(|_| SimulationError::InvalidVector)?;
                    policy
                },
            })
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    let transitions = raw
        .get("transitions")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(|transition| {
            Ok(SimulationTransition {
                id: string_field(transition, "id")?.to_owned(),
                source_node: string_field(transition, "source_node")?.to_owned(),
                evaluation_point: string_field(transition, "evaluation_point")?.to_owned(),
                priority: transition["priority"]
                    .as_i64()
                    .ok_or(SimulationError::InvalidVector)?,
                cycle_delta: transition
                    .get("cycle_delta")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                claims: transition
                    .get("claims")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default()
                    .iter()
                    .map(|claim| {
                        serde_json::from_value::<ArbitrationClaim>(claim.clone())
                            .map_err(|_| SimulationError::InvalidVector)
                    })
                    .collect::<Result<Vec<_>, _>>()?,
                target_kind: transition
                    .get("target_kind")
                    .and_then(Value::as_str)
                    .unwrap_or("NODE")
                    .to_owned(),
                target_node: transition
                    .get("target_node")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                target_action: transition
                    .get("target_action")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                child_slot_id: transition
                    .get("child_slot_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                parent_policy: transition
                    .get("parent_policy")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                source_disposition: transition
                    .get("source_disposition")
                    .and_then(Value::as_str)
                    .unwrap_or("TERMINATE_SOURCE")
                    .to_owned(),
                event_type: transition
                    .get("event_type")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                input_command: transition
                    .get("input_command")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
            })
        })
        .collect::<Result<Vec<_>, SimulationError>>()?;
    let child_slot_capacities = raw
        .get("child_slot_capacities")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let start_claims = raw
        .get("start_claims")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let slot_claims = raw.get("slot_claims").cloned().unwrap_or_else(|| json!([]));
    Ok(Definition {
        id: string_field(raw, "id")?.to_owned(),
        hash,
        initial_node: raw
            .get("initial_node_id")
            .and_then(Value::as_str)
            .unwrap_or(string_field(&array(raw, "nodes")?[0], "id")?)
            .to_owned(),
        rate_scale: u64_field(raw, "rate_scale")?,
        units_per_tick: u64_field(raw, "units_per_tick")?,
        nodes,
        predicates,
        facts,
        transitions,
        child_slot_capacities: serde_json::from_value(child_slot_capacities)
            .map_err(|_| SimulationError::InvalidVector)?,
        child_termination_policies: serde_json::from_value(
            raw.get("child_termination_policies")
                .cloned()
                .unwrap_or_else(|| json!({})),
        )
        .map_err(|_| SimulationError::InvalidVector)?,
        start_claims: serde_json::from_value(start_claims)
            .map_err(|_| SimulationError::InvalidVector)?,
        slot_claims: serde_json::from_value(slot_claims)
            .map_err(|_| SimulationError::InvalidVector)?,
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

fn domain_frozen(state: &SimulationState, target_id: u64, domain: &str) -> bool {
    state.freeze_tokens.iter().any(|token| {
        token["target_id"].as_u64() == Some(target_id)
            && token["activation_tick"]
                .as_u64()
                .is_some_and(|activation| activation <= state.tick)
            && token["remaining_ticks"]
                .as_u64()
                .is_some_and(|remaining| remaining > 0)
            && token["domains"]
                .as_array()
                .is_some_and(|domains| domains.iter().any(|value| value.as_str() == Some(domain)))
    })
}

fn canonical_set<'a>(values: impl Iterator<Item = &'a String>) -> Vec<String> {
    values
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}
