# PCAM v3 Normative Issue Ledger

Status: CLOSED for the current Normative Candidate text

Owner: PCAM specification gate

This ledger records issues found during the contradiction audit and the normative decisions now incorporated into `PCAM-v3.md`. New issues reopen the specification gate until they receive an explicit resolution.

## Freeze stack merge semantics

Resolved in §18.5. The group key is `(target_id, stack_group)`; tokens remain separate records; compatible `MAX_DURATION` tokens overlap; compatible `SUM_DURATION` tokens queue by exclusive expiration; `REPLACE` and `REJECT_NEW` are exact; incompatible duration groups fault before mutation; and `HOLD` dominates overlapping progression freezes.

## Deferred progression state

Resolved in §7.3 and §10.3. `deferred_quanta` is required authoritative action-instance state.

## Intent atomic groups

Resolved in §15.2. `atomic_group_id` is optional correlation metadata only in Core. It does not couple acceptance across intents. Cross-intent atomicity requires an authoritative extension with complete ordering and allocation semantics.

## Defense-fact selection

Resolved in §20.2, §20.5, and §20.6. A candidate has an optional defense selector. Zero matches selects no defense, one selects that fact, and multiple matches fault as ambiguous. Multi-fact composition requires an authoritative extension.

## Materialization operation registry

Resolved in §21.5. `MATERIALIZE` is a core operation with explicit status and effect-class filtering.

## Parry reaction materialization

Resolved in §21.5-21.6. Appending a reaction template does not emit it. Rejected-status materialization must be explicit, class-restricted to `REACTION`, and occur before the pipeline stops. The §34 parry example preserves a decision template but emits no authoritative reaction effect.

## Event-delivery freeze lifetime

Resolved in §25.4. A frozen target-action event advances its authoritative `delivery_tick` by one and remains pending; repeated freezes repeat the deferral.

## Terminate-parent composition

Resolved in §17.4. The new child starts first and is exempt from the parent termination-policy pass applied to previously occupying children. It remains linked and continues after the parent terminates.

## Freeze-all action domains

Resolved in §17.2. `FREEZE_ALL_ACTION_LOGIC` expands to progression, PRE/POST transitions, input capture, and interaction emission/reception. Buffer expiry, event delivery, resource regeneration, and RNG consumption remain separate domains.

## Adjacent audit corrections

The audit also added `input_id` to the intent structure, added `target.<field>` to interaction references, removed reliance on map insertion order for initial-node selection, and resolved canonical transition-field presence. Machine documents now encode absent matches as `null` and empty/default assignment, effect, cycle, and metadata fields explicitly; readable design listings may omit them only when they identify the machine artifact.

## Transition operation order

Resolved in §8.5, §14.6, §14.7, and §23.1. The required transition `exit_assignments`, `entry_assignments`, and `cycle_delta` fields now have exact positions in the mutation order. All transition assignment arrays target the source action, node-entry state is visible to node entry operations, new actions execute their own initial-node operations, and declarative effect defaults and payload materialization timing are explicit.

## Fault-policy containment

Resolved in §30.3. Fault attribution, tick-start rollback, logical-tick advancement, action and entity scope, child and cross-entity relationship handling, trace behavior, input consumption, and escalation of unattributable faults are explicit for all three runtime policies.

## Parameter binding

Resolved in §8.4. Direct-start bindings use the input payload's `parameters` object and are validated before instance allocation. Captures are authoritative deep copies. Core action and child transitions have no binding field and therefore can start only targets whose required parameters have defaults.
