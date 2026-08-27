# PCAM v3.0 Master Specification

## Deterministic Semantic Action Model for Interactive Simulation

**Version:** 3.0.0-draft.1
**Status:** Normative Candidate
**Supersedes:** PCAM-24 v1.x and v2.x
**Compatibility:** Breaking redesign
**Project:** Greyforge Labs
**Stability condition:** This document becomes **Stable, Normative** only after the release gates in §45 are satisfied.

---

## 0. Executive Definition

PCAM v3 defines an engine-independent model for authoring, executing, inspecting, saving, restoring, networking, and testing discrete semantic actions in interactive simulations.

The authoritative unit is no longer a single phase value.

The authoritative runtime state is the complete action-machine state:

\[
A =
(\text{instance},\text{definition},\text{node},\text{progress},
\text{cycle},\text{registers},\text{buffers},\text{freezes},
\text{relationships},\text{ledgers},\text{RNG})
\]

The simulation advances through monotonic logical ticks:

\[
t \in \mathbb N
\]

A conforming implementation MUST satisfy:

\[
(S_{t+1},O_t)=F(S_t,I_t)
\]

where identical complete states and canonically identical inputs produce identical next states and outputs:

\[
S_a=S_b \land I_a=I_b
\Longrightarrow
F(S_a,I_a)=F(S_b,I_b)
\]

PCAM v3 preserves the useful parts of earlier PCAM designs:

- Explicit semantic action windows
- Discrete progression
- Deterministic transition and cancellation rules
- Presentation following simulation state
- Engine-independent action definitions
- Visual phase-wheel authoring
- Rollback-compatible state

PCAM v3 rejects the following earlier claims:

- A value in \(\mathbb Z_{24}\) is sufficient to represent complete action state.
- Phase replaces logical time.
- Integer phase alone guarantees full simulation determinism.
- `ActionID + Phase` is sufficient for rollback or reconciliation.
- A universal property ordering such as `VOID > COUNTER > MITIGATE > IMPACT` can resolve every interaction.
- Phase snapping reverses already-committed simulation consequences.
- Network latency disappears because actions use phases.

The corrected principle is:

> **Semantic action state is authoritative. Logical ticks provide ordering. Phase profiles provide authoring, visualization, and optional projections. Presentation remains subordinate to simulation.**

---

# 1. Normative Language

The keywords **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** are normative.

A requirement marked **MUST** is necessary for conformance.

A requirement marked **SHOULD** may be violated only when the implementation documents:

1. The reason for the deviation
2. The resulting semantic consequences
3. The effect on interoperability
4. The effect on determinism
5. The applicable conformance-class exclusions

Examples and explanatory notes are non-normative unless explicitly marked otherwise.

---

# 2. Scope

PCAM v3 standardizes:

1. Immutable action definitions
2. Mutable action-instance state
3. Logical-tick progression
4. Deterministic rational-rate advancement
5. State-machine nodes and transitions
6. Named semantic predicates
7. Input buffering
8. Cancellation and action replacement
9. Parent-child action composition
10. Freeze, stall, and suspension semantics
11. Directed interaction candidates
12. Typed interaction rules
13. Hit and contact ledgers
14. Effect aggregation and commit ordering
15. Deterministic random-state ownership
16. Canonical state serialization and hashing
17. Save, restore, lockstep, prediction, and rollback requirements
18. The optional PCAM-24 authoring and projection profile
19. Validation and conformance requirements

PCAM v3 does not prescribe:

- Rendering
- Animation blending
- Audio mixing
- VFX implementation
- Physical collision algorithms
- Transport protocols
- Matchmaking
- Anti-cheat systems
- Game balance
- Wall-clock scheduling
- A mandatory engine architecture
- A mandatory networking topology

A host MAY integrate those systems, but they MUST respect the authority boundaries defined by this specification.

---

# 3. Foundational Invariants

## 3.1 Complete-State Authority

A phase, node, animation frame, timer, or presentation timestamp MUST NOT be treated as the complete authoritative state unless it actually encodes every value required to determine future behavior.

PCAM action authority consists of the complete serialized action-instance state.

Two action instances MAY expose the same phase projection while remaining semantically different.

For example:

```text
phase = 11, stall_remaining = 4
phase = 11, stall_remaining = 1
```

These states MUST produce distinct canonical state encodings and distinct state hashes.

Similarly:

```text
phase = 0, cycle = 0
phase = 0, cycle = 12
```

These states MUST remain distinguishable.

## 3.2 Logical-Tick Authority

Every authoritative reaction occurs at a logical tick:

\[
t \in \{0,1,2,\ldots\}
\]

Logical ticks are monotonic and MUST NOT wrap during a simulation session.

Wall-clock seconds, frame duration, renderer delta time, animation timestamps, and audio clocks MUST NOT directly determine authoritative PCAM outcomes.

A host MAY associate logical ticks with wall-clock intervals for presentation or scheduling.

## 3.3 Deterministic Transition

Given:

- Identical complete PCAM state
- Identical declared host state
- Identical canonical input set
- Identical definition set
- Identical deterministic extension behavior

a conforming runtime MUST produce:

- Identical next PCAM state
- Identical authoritative effects
- Identical event identifiers
- Identical state digest
- Identical deterministic fault, if one occurs

## 3.4 Presentation Non-Authority

Animation, audio, VFX, camera systems, UI, interpolation, and other presentation systems MAY observe PCAM state.

They MUST NOT mutate authoritative PCAM state except by submitting explicit inputs through a declared interface.

Presentation completion callbacks MUST NOT silently advance an action.

Animation events MAY be translated into explicit host inputs only when:

- Their delivery tick is deterministic
- Their ordering is deterministic
- Their authoritative role is declared
- Their state is included in rollback and replay

Such use is NOT RECOMMENDED.

## 3.5 Explicit Ordering

No outcome may depend on:

- Hash-map traversal
- Memory address
- Thread completion order
- Unspecified entity iteration
- Nondeterministic callback ordering
- Unstable sort behavior
- File-system enumeration order

Any noncommutative operation MUST define a canonical ordering key.

## 3.6 Explicit Randomness

All authoritative randomness MUST come from declared deterministic random streams.

Every authoritative RNG stream MUST include its complete algorithm identity and mutable state in snapshots and hashes.

Calls to platform entropy, wall-clock time, thread-local randomness, or nondeterministic engine RNGs are forbidden in authoritative PCAM processing.

## 3.7 Complete Recovery

A conforming save state or rollback snapshot MUST include every value required to reproduce subsequent authoritative outcomes.

A snapshot consisting only of an action definition identifier and phase is non-conforming.

## 3.8 Bounded Execution

Every per-tick algorithm MUST have declared deterministic limits.

When a limit is exceeded, the runtime MUST produce a deterministic fault. It MUST NOT:

- Hang
- Continue indefinitely
- Clamp silently
- Drop work nondeterministically
- Produce implementation-dependent partial results

## 3.9 Profile Separation

PCAM Core defines semantic execution.

A profile MAY provide:

- Authoring syntax
- A fixed phase count
- Visualization
- Engine integration
- Networking policy
- Numeric policy
- Domain-specific interaction vocabulary

A profile MUST NOT contradict PCAM Core invariants.

---

# 4. Terminology

| Term | Definition |
|---|---|
| **Host** | The simulation engine or application embedding PCAM |
| **Logical tick** | Monotonic authoritative reaction index |
| **Definition set** | Immutable collection of action, interaction, effect, and profile definitions |
| **Action definition** | Immutable description of an action machine |
| **Action instance** | Mutable runtime execution of an action definition |
| **Node** | Named control state inside an action definition |
| **Quantum** | One discrete unit of action progression |
| **Local step** | Monotonic count of quanta consumed by an action instance |
| **Node step** | Number of quanta consumed since entering the current node |
| **Cycle** | Explicit lifecycle epoch incremented at declared boundaries |
| **Transition** | Guarded edge from a node to another node, action, or terminal state |
| **Predicate** | Pure named Boolean expression over authoritative state |
| **Window** | Compatibility term for a named predicate active over part of an action |
| **Semantic fact** | Active offense, defense, neutral, or domain-specific capability |
| **Candidate** | Directed potential interaction between a source fact and target |
| **Decision record** | Mutable deterministic record used while resolving one candidate |
| **Effect** | Declarative proposed mutation or output |
| **Receipt** | Authoritative record that a contact or impact has been processed |
| **Ledger** | Authoritative collection of receipts |
| **Freeze token** | Explicit state controlling suspension of one or more domains |
| **Buffer entry** | Authoritative retained input command |
| **Intent** | Proposed action start, transition, cancellation, or replacement |
| **Claim** | Resource, slot, or exclusivity requirement attached to an intent |
| **Snapshot** | Complete authoritative state captured at a tick boundary |
| **State digest** | SHA-256 hash of canonical authoritative state |
| **Phase projection** | Derived bounded coordinate used for tooling or presentation |
| **PCAM-24** | Optional profile providing 24-cell authoring and visualization |

---

# 5. Determinism Boundary

PCAM distinguishes three levels of determinism.

## 5.1 Semantic Determinism

A runtime provides semantic determinism when PCAM-owned state and PCAM-owned rules are deterministic.

A host with nondeterministic physics may still provide semantic determinism for isolated action execution.

## 5.2 Host Determinism

A host provides host determinism when all authoritative inputs supplied to PCAM are deterministic, including:

- Entity identifiers
- Imported host variables
- Contact generation
- Collision ordering
- Physics state
- Resource state
- Extension effects
- RNG
- Spawn ordering
- Event delivery

## 5.3 Full Simulation Determinism

Full simulation determinism requires both semantic determinism and host determinism.

An implementation MUST NOT claim complete cross-platform simulation determinism merely because its PCAM action progression uses integers.

---

# 6. Formal Simulation Model

The complete authoritative simulation state at tick \(t\) is:

\[
S_t=(P_t,H_t)
\]

where:

- \(P_t\) is PCAM-owned state
- \(H_t\) is declared host-authoritative state

The canonical tick input is:

\[
I_t
\]

The deterministic reaction is:

\[
F:(S_t,I_t)\rightarrow(S_{t+1},E_t,O_t)
\]

where:

- \(E_t\) is the authoritative committed effect set
- \(O_t\) is the non-authoritative presentation-output set

The host MUST expose all host values referenced by PCAM as an immutable tick snapshot.

A PCAM guard, predicate, or interaction rule MUST NOT read mutable host state that changes during its evaluation.

---

# 7. Authoritative State

## 7.1 Global PCAM State

The global PCAM state MUST contain at least:

```text
tick
definition_set_hash
entity_records
action_instances
resource_banks
action_slots
pending_inputs
input_buffers
pending_events
freeze_tokens
interaction_ledgers
rng_streams
next_action_instance_id
next_freeze_token_id
extension_state
fault_state
```

An implementation MAY organize these values differently internally.

Its canonical serialized state MUST preserve equivalent information.

## 7.2 Entity Record

A PCAM entity record MUST contain:

```text
entity_id
lifecycle_state
resource_bank
action_slot_state
entity_tags
entity_registers
active_action_instance_ids
entity_rng_stream_ids
extension_state
```

Entity identifiers MUST be stable unsigned integers or stable canonical identifiers.

Memory addresses and transient engine object handles MUST NOT be used as canonical entity identifiers.

## 7.3 Action-Instance State

A running action instance MUST contain:

```text
instance_id
owner_entity_id
definition_hash
slot_claims
lifecycle_state
current_node_id
node_step
local_step
cycle
transition_serial
quantum_accumulator
deferred_quanta
current_rate_units
captured_parameters
registers
input_buffer
event_inbox
freeze_token_references
parent_instance_id
parent_slot_id
child_instance_ids
predicate_truth_state
predicate_entry_serials
predicate_exit_serials
emission_serial
interaction_ledger_partition
rng_stream_ids
fault_record
extension_state
```

Every field capable of influencing future authoritative behavior MUST be serialized.

## 7.4 Lifecycle States

Core lifecycle states are:

```text
PENDING
RUNNING
SUSPENDED
TERMINATED
FAULTED
```

`TERMINATED` and `FAULTED` instances do not produce semantic facts or receive progression quanta.

A host MAY retain terminated instances for rollback history.

It MUST NOT reactivate a terminated instance except by restoring an earlier snapshot.

## 7.5 Monotonic Counters

The following counters MUST be monotonic within an action instance:

- `local_step`
- `transition_serial`
- `emission_serial`
- Predicate entry serials
- Predicate exit serials

They MUST NOT wrap.

Overflow MUST produce a deterministic fault before mutation.

`node_step` resets to zero on node entry.

`cycle` increments only at explicit cycle boundaries.

---

# 8. Action Definitions

## 8.1 Immutability

An action definition is immutable after its canonical hash is computed.

Active action instances MUST remain bound to the exact definition hash with which they started.

Hot-reloading a definition MUST produce a new definition hash.

Existing instances MAY continue using the old definition.

Migrating an active instance to a new definition requires an explicit deterministic migration operation and is outside PCAM Core v3.0.

## 8.2 Required Top-Level Fields

A canonical action definition MUST contain:

```yaml
pcam_version: "3.0"
kind: action
id: <canonical-symbol>
revision: <unsigned-integer>
metadata: {}
limits: {}
rate: {}
parameters: {}
registers: {}
imports: {}
initial_node: <node-identifier>
nodes: {}
predicates: {}
semantic_facts: []
transitions: []
slot_claims: []
profiles: {}
extensions: {}
```

## 8.3 Identifiers

Definition identifiers, node identifiers, transition identifiers, predicate identifiers, fact identifiers, register identifiers, resource identifiers, and slot identifiers MUST match:

```regex
[A-Za-z][A-Za-z0-9_.:-]{0,127}
```

Identifiers are case-sensitive.

Canonical ordering uses ascending UTF-8 byte order.

## 8.4 Parameters

Parameters are immutable values supplied when an action instance starts.

A parameter declaration MUST define:

```text
id
type
required
default, if any
minimum, if numeric
maximum, if numeric
allowed values, if enumerated
capture policy
```

Parameters MUST be captured into the action instance.

An action MUST NOT rely on a mutable external parameter after start unless it is explicitly declared as a live host import.

A direct action-start input supplies bindings in its payload's `parameters` object. The runtime MUST reject an unknown binding, a missing required binding without a default, or a value that violates the declared type, bounds, capacity, or allowed values before allocating the action instance. Captured values are deep immutable copies for authoritative purposes. An `ACTION` or `CHILD_ACTION` transition has no Core parameter-binding field, so its target action MUST be startable from declared defaults alone; otherwise the accepted transition faults atomically.

## 8.5 Registers

Registers are mutable action-local authoritative values.

Each register MUST define:

```text
type
initial value
minimum
maximum
overflow policy
serialization policy
```

Core register types are:

```text
BOOL
I64
U64
SYMBOL
BYTES
SET_SYMBOL
FIXED_ARRAY
BOUNDED_LIST
```

Dynamic collections MUST declare a maximum capacity and overflow policy.

Core assignment targets use the exact form `action.register.<id>`. Parameters are immutable and MUST NOT be assignment targets. Assignments execute in document array order, and each assignment expression observes all preceding authoritative mutations. The assigned value MUST match the declared register type. Numeric values apply the register's declared minimum, maximum, and overflow policy before mutation. An invalid target, type, or bounded value produces a deterministic fault before that assignment mutates the register.

## 8.6 Host Imports

A host import is a named immutable value supplied from the host snapshot for the current tick.

Each import MUST define:

```text
id
type
source contract
default or failure policy
authoritative flag
serialization dependency
```

An authoritative import MUST be included in host snapshots and rollback state.

## 8.7 Nodes

Each action definition MUST declare `initial_node` as the identifier of one node in its `nodes` map. Map insertion order MUST NOT select the initial node.

A node MUST contain:

```text
id
mode
duration_quanta, when timed
seekable
entry_assignments
entry_effects
exit_assignments
exit_effects
tags
extensions
```

Core node modes are:

### `TIMED`

A timed node has a positive integer `duration_quanta`.

The node is active while:

\[
0 \le \text{nodeStep} < \text{durationQuanta}
\]

After a quantum increments `node_step` to `duration_quanta`, an eligible `AFTER_QUANTUM` transition MUST leave the node.

A timed node without a valid completion path is invalid.

### `EVENT_DRIVEN`

An event-driven node remains active until an explicit transition occurs.

Its `node_step` MAY continue increasing as progression quanta are consumed.

### `TERMINAL`

A terminal node causes the action to enter `TERMINATED` immediately upon entry.

A terminal node emits its entry effects before termination effects, using canonical emission ordering.

## 8.8 Seekable Nodes

A transition MAY enter a node at a nonzero `node_step` only when the target node declares:

```yaml
seekable: true
```

The target step MUST satisfy:

\[
0 \le \text{targetStep} < \text{durationQuanta}
\]

for timed nodes.

No implicit intermediate node or step effects are fired.

Any required crossed-state behavior MUST be attached explicitly to the transition.

---

# 9. Numeric Semantics

## 9.1 Floating Point

Authoritative PCAM definitions and PCAM Core state MUST NOT contain IEEE floating-point values.

A host extension MAY use deterministic fixed-point or another exact representation.

It MUST provide:

- Canonical serialization
- Defined arithmetic
- Defined overflow
- Defined rounding
- Determinism vectors

## 9.2 Integers

Core signed arithmetic uses signed 64-bit integers.

Core unsigned arithmetic uses unsigned 64-bit integers.

Every arithmetic operation MUST use one declared overflow policy:

```text
FAULT
SATURATE
WRAP
```

`FAULT` is the default.

`WRAP` uses two’s-complement modulo arithmetic of the declared width.

## 9.3 Division

Integer division MUST use Euclidean division for positive divisors:

\[
a = qb+r,\quad 0\le r<b
\]

where \(b>0\).

Division by zero produces a deterministic fault.

## 9.4 Ratios

Ratios are represented as:

```text
numerator: I64
denominator: U64
```

The denominator MUST be greater than zero.

Ratios SHOULD be stored in reduced form.

Operations using ratios MUST specify their rounding policy.

---

# 10. Deterministic Progression

## 10.1 Progression Quanta

Actions advance in integer quanta.

Each action definition declares:

```yaml
rate:
  scale: <positive-u64>
  units_per_tick: <u64>
```

Each action instance stores:

```text
quantum_accumulator
current_rate_units
```

The default `current_rate_units` is the definition’s `units_per_tick`.

## 10.2 Advancement Algorithm

For each running action not frozen in the `PROGRESSION` domain:

```text
accumulator = accumulator + current_rate_units
quanta = accumulator div rate.scale
accumulator = accumulator mod rate.scale
```

The runtime then executes exactly `quanta` progression quanta.

If the addition overflows, the runtime faults.

If `quanta` exceeds the simulation profile’s declared `max_quanta_per_action_per_tick`, the runtime faults.

The runtime MUST NOT silently clamp excess quanta.

## 10.3 Freeze Behavior

When progression is frozen with `accrual_policy: HOLD`:

- The accumulator is not incremented.
- No progression quanta are generated.

When progression is frozen with `accrual_policy: ACCRUE`:

- The accumulator is incremented.
- Generated quanta are deferred.
- Deferred quanta remain authoritative state.
- Releasing the freeze may produce multiple quanta.
- Applicable per-tick limits still apply.

`HOLD` is the default and RECOMMENDED policy.

## 10.4 Quantum Execution

For each consumed quantum:

1. Increment `local_step`.
2. Increment `node_step`.
3. Evaluate `AFTER_QUANTUM` transitions from the current node.
4. Select at most one eligible transition.
5. Apply the selected transition.
6. Continue with any remaining quanta from the newly entered node.

An action MUST NOT consume a quantum after it terminates or faults.

## 10.5 Transition Limits

Each action definition MUST declare or inherit:

```text
max_internal_transitions_per_tick
```

Exceeding the limit produces a deterministic fault.

Zero-duration timed nodes are forbidden.

Implicit epsilon-transition loops are forbidden.

---

# 11. Expression Language

## 11.1 Purity

Guards, predicates, and rule conditions MUST be pure.

They MUST NOT:

- Modify state
- Consume input
- Advance RNG
- Allocate identifiers
- Emit effects
- Read wall-clock time
- Call arbitrary host code

## 11.2 Expression Forms

Core expressions use three forms:

```yaml
literal: <value>
```

```yaml
ref: <canonical-reference>
```

```yaml
op: <operator>
args: [...]
```

## 11.3 Core References

Core action references include:

```text
action.instance_id
action.owner_entity_id
action.lifecycle
action.node
action.node_step
action.local_step
action.cycle
action.transition_serial
action.register.<id>
action.parameter.<id>
action.predicate.<id>
owner.resource.<id>
owner.register.<id>
input.<field>
event.<field>
host.<import-id>
```

Interaction-rule references additionally include:

```text
candidate.<field>
offense.<field>
defense.<field>
decision.<field>
contact.<field>
target.<field>
```

## 11.4 Core Operators

Core Boolean operators:

```text
and
or
not
xor
```

Core comparison operators:

```text
eq
ne
lt
lte
gt
gte
```

Core integer operators:

```text
add
sub
mul
div
mod
min
max
clamp
abs
```

Core set operators:

```text
contains
intersects
subset
union
difference
```

Core selection operators:

```text
if
coalesce
```

Predicate references MUST form an acyclic dependency graph.

Circular predicate dependencies are invalid.

---

# 12. Predicates and Semantic Windows

## 12.1 Predicate Definition

A predicate contains:

```text
id
expression
track_edges
metadata
```

A predicate is evaluated over an immutable action and host snapshot.

## 12.2 Overlap

Predicates MAY overlap.

An action may simultaneously satisfy:

```text
ACTIVE
ARMORED
AIRBORNE
CANCELABLE
CHARGE_LEVEL_2
```

No predicate implicitly cancels another predicate.

## 12.3 Coverage

Predicates are not required to cover every action state.

A state may satisfy no named semantic predicate.

## 12.4 Windows

The term “window” is retained as authoring vocabulary.

A window has no separate runtime type. It is a named predicate.

For example:

```yaml
predicates:
  ACTIVE:
    expression:
      op: eq
      args:
        - ref: action.node
        - literal: active
```

## 12.5 Predicate Edge Tracking

When `track_edges: true`, the runtime stores:

```text
previous_truth
entry_serial
exit_serial
```

At the semantic snapshot stage:

- `false → true` increments `entry_serial`.
- `true → false` increments `exit_serial`.
- Other transitions do not modify the serials.

Predicate serials MUST be included in snapshots.

They MAY be used by contact policies such as once-per-activation.

---

# 13. Inputs and Buffering

## 13.1 Input Envelope

An authoritative input MUST contain:

```text
assigned_tick
source_entity_id
sequence
command_id
payload
input_id
```

`sequence` MUST be monotonic per source.

`input_id` MUST uniquely identify the input within the simulation.

Duplicate input identifiers MUST be rejected or deterministically deduplicated according to the active network profile.

## 13.2 Canonical Input Order

Inputs assigned to the same tick are sorted by:

1. `source_entity_id`
2. `sequence`
3. `command_id`
4. `input_id`

No implementation may depend on arrival order after tick assignment.

## 13.3 Buffer Entry

A buffer entry contains:

```text
buffer_entry_id
input_id
command_id
payload
captured_tick
remaining_eligibility_ticks
priority
sequence
```

## 13.4 Eligibility Lifetime

A new buffer entry is available during the tick in which it is captured.

At end of tick:

- Consumed entries are removed.
- Unconsumed entries decrement `remaining_eligibility_ticks`, unless buffer expiry is frozen.
- Entries reaching zero are removed.

An entry with lifetime `1` is therefore available only during its capture tick.

## 13.5 Buffer Capacity

Each action definition MUST declare:

```text
buffer_capacity
buffer_overflow_policy
```

Core overflow policies are:

```text
DROP_OLDEST
DROP_NEWEST
FAULT
```

The policy MUST be deterministic.

## 13.6 Consumption

A transition MAY consume one or more matching buffer entries.

Consumption defaults to:

```text
ON_ACCEPT
```

Optional policies are:

```text
ON_ACCEPT
ON_ATTEMPT
NEVER
```

`ON_ATTEMPT` SHOULD be used only when failed attempts are intended to consume the command.

---

# 14. Transitions

## 14.1 Transition Structure

A transition MUST contain:

```text
id
source_node
evaluation_point
guard
priority
target
input_match
event_match
claims
consume_policy
exit_assignments
assignments
entry_assignments
effects
cycle_delta
metadata
```

Canonical machine documents MUST encode an absent `input_match` or `event_match` as `null`, encode assignment and effect collections as arrays including when empty, encode `cycle_delta` as an integer including zero, and encode `metadata` as an object including when empty. Readable non-normative listings MAY omit these empty or default forms only when they identify the machine-valid repository artifact that supplies them.

## 14.2 Evaluation Points

Core evaluation points are:

```text
PRE_ADVANCE
AFTER_QUANTUM
POST_ADVANCE
```

### `PRE_ADVANCE`

Evaluated after input ingestion and before progression.

### `AFTER_QUANTUM`

Evaluated immediately after each progression quantum.

These transitions MUST NOT contain contested shared-resource claims.

### `POST_ADVANCE`

Evaluated after all progression quanta and before semantic-fact snapshotting.

This permits an input to trigger a transition after the action enters a newly eligible window during the same logical tick.

## 14.3 Eligibility

A transition is eligible when:

1. The action is in its declared source node.
2. The evaluation point matches the current stage.
3. Its guard evaluates to true.
4. Its required input or event is present.
5. Its static constraints are satisfied.

## 14.4 Selection

Within one action instance and evaluation point:

- Transition priorities MUST be unique.
- The eligible transition with the highest priority is selected.
- At most one external transition may be selected per action per evaluation point.

Equal priorities within the same source node and evaluation point are a definition validation error.

## 14.5 Targets

A transition target has one of the following kinds:

```text
NODE
ACTION
CHILD_ACTION
TERMINATE
FAULT
```

### `NODE`

Moves the instance to another node.

### `ACTION`

Atomically starts another action and applies the declared source disposition:

```text
TERMINATE_SOURCE
SUSPEND_SOURCE
KEEP_SOURCE
```

### `CHILD_ACTION`

Starts a child action linked to the current action.

### `TERMINATE`

Terminates the current action.

### `FAULT`

Moves the current action to `FAULTED` with a declared fault code.

## 14.6 Transition Mutation Order

An accepted transition applies local operations in this order:

1. Source-node exit assignments
2. Transition `exit_assignments`
3. Source-node exit effects
4. Transition `assignments`
5. Apply `cycle_delta`
6. Transition effects
7. Transition `entry_assignments`
8. Apply target and node-entry state mutation
9. Target-node entry assignments
10. Target-node entry effects

Assignments in each step observe results from preceding steps.

All three transition assignment arrays target the source action instance, including when an `ACTION` or `CHILD_ACTION` target starts another instance. A `NODE` target applies step 8 by setting the target node, target step, and transition serial before target-node entry operations. `ACTION`, `CHILD_ACTION`, `TERMINATE`, and `FAULT` targets do not execute target-node entry operations on the source. A newly started action independently executes its initial-node entry operations as defined in §14.7.

External effects remain deferred until the effect-commit stage.

## 14.7 Node Entry

Entering a node sets:

```text
current_node_id = target
node_step = target_step or 0
transition_serial += 1
```

Entering a terminal node terminates the action after entry operations are emitted.

Starting an action enters its declared initial node and executes that node's entry assignments and effects before terminal-node termination is applied.

## 14.8 Explicit Skipping

A skip is an explicit transition to another node or target step.

No semantic consequence is implied merely because intermediate projected phases or steps were crossed.

Skipped states do not automatically emit:

- Entry effects
- Exit effects
- Predicate-edge events
- Interaction opportunities
- Resource changes

Any required skip consequence MUST appear explicitly in the transition.

---

# 15. Intent Arbitration

## 15.1 Purpose

Starts, cancellations, replacements, and contested transitions may compete for:

- Action slots
- Resources
- Exclusive keys
- Child slots
- Capacity limits

Such operations are represented as intents.

## 15.2 Intent Structure

An intent contains:

```text
intent_kind
intent_priority
owner_entity_id
source_action_instance_id
transition_id
input_sequence
input_id
claims
operations
atomic_group_id
```

`atomic_group_id` is an optional opaque correlation identifier. PCAM Core does not grant cross-intent acceptance semantics to equal group identifiers. Each intent remains its own atomic arbitration unit. An extension that adds cross-intent group atomicity MUST define group ordering, all-or-nothing acceptance, claim visibility, input consumption, and identifier allocation, and MUST include that extension in definition-set identity.

## 15.3 Canonical Intent Order

Competing intents are sorted by:

1. Descending `intent_priority`
2. Ascending `owner_entity_id`
3. Ascending `source_action_instance_id`
4. Ascending transition or action-definition identifier
5. Ascending input sequence
6. Ascending input identifier

## 15.4 Claims

Core claim kinds are:

```text
RESOURCE
ACTION_SLOT
CHILD_SLOT
EXCLUSIVE_KEY
CAPACITY
```

A resource claim MUST specify a nonnegative integer amount.

An intent is accepted only when all claims can be satisfied atomically.

No partial claim application is allowed.

## 15.5 Resource Reservation

Accepted resource claims are applied before action progression.

Rejected intents leave state unchanged except when their input consumption policy is `ON_ATTEMPT`.

## 15.6 Identifier Allocation

New action-instance identifiers are allocated from:

```text
next_action_instance_id
```

Allocation follows accepted-intent canonical order.

The identifier counter is authoritative state and MUST be snapshotted.

---

# 16. Action Slots and Concurrency

## 16.1 Slots

An entity MAY define named action slots such as:

```text
FULL_BODY
MOVEMENT
UPPER_BODY
WEAPON
REACTION
PASSIVE
```

PCAM does not assign semantics to slot names.

## 16.2 Slot Claims

An action definition MAY claim one or more slots.

Each slot declaration MUST define:

```text
capacity
replacement policy
suspension policy
priority policy
```

## 16.3 Concurrency

Multiple action instances MAY run concurrently when their claims are compatible.

Their processing order MUST NOT determine interaction outcomes except where the specification explicitly defines canonical arbitration.

## 16.4 Replacement

An action replacement MUST be atomic.

The runtime MUST NOT terminate the source action if the target action cannot acquire all required claims.

---

# 17. Parent-Child Action Composition

## 17.1 Relationship

A child action stores:

```text
parent_instance_id
parent_slot_id
```

The parent stores the child identifier in its child-slot state.

## 17.2 Parent Policies

Starting a child MUST declare one parent policy:

```text
CONTINUE
FREEZE_PROGRESSION
FREEZE_TRANSITIONS
FREEZE_ALL_ACTION_LOGIC
TERMINATE_PARENT
```

Parent freezes are represented using explicit freeze tokens.

`FREEZE_ALL_ACTION_LOGIC` expands exactly to:

```text
PROGRESSION
PRE_ADVANCE_TRANSITIONS
POST_ADVANCE_TRANSITIONS
INPUT_CAPTURE
INTERACTION_EMISSION
INTERACTION_RECEPTION
```

It does not freeze `BUFFER_EXPIRY`, `EVENT_DELIVERY`, `RESOURCE_REGENERATION`, or `RNG_CONSUMPTION`. Those domains require separate explicit tokens.

## 17.3 Child Completion

A terminating child emits a deterministic child-result event containing:

```text
parent_instance_id
child_instance_id
child_slot_id
result_code
termination_tick
```

The event becomes available to the parent at the next logical tick.

## 17.4 Parent Termination

A parent definition MUST declare one policy for each child slot:

```text
TERMINATE_CHILD
DETACH_CHILD
ALLOW_CHILD_TO_COMPLETE
FAULT_IF_OCCUPIED
```

When an accepted child-start intent uses `TERMINATE_PARENT`, the runtime MUST atomically:

1. Start and link the new child.
2. Apply the parent termination policy to children that occupied parent slots before that intent.
3. Exempt the newly started child from that termination-policy pass.
4. Terminate the parent.

The newly started child remains linked, continues according to its own lifecycle, and emits its normal child-result event. This launch-specific precedence does not change policies applied by any later independent parent-termination operation.

## 17.5 Nesting Limits

The simulation profile MUST declare:

```text
max_action_nesting_depth
max_children_per_action
```

Exceeding either limit produces a deterministic fault or rejected intent according to the declared policy.

---

# 18. Freeze, Stall, and Suspension

## 18.1 Freeze Tokens

A freeze token contains:

```text
token_id
source_id
target_id
activation_tick
remaining_ticks
domains
accrual_policy
stack_group
stack_policy
metadata
```

## 18.2 Core Freeze Domains

Core domains are:

```text
PROGRESSION
PRE_ADVANCE_TRANSITIONS
POST_ADVANCE_TRANSITIONS
INPUT_CAPTURE
BUFFER_EXPIRY
EVENT_DELIVERY
INTERACTION_EMISSION
INTERACTION_RECEPTION
RESOURCE_REGENERATION
RNG_CONSUMPTION
```

Host extensions MAY define additional domains such as movement or physics.

## 18.3 Activation Timing

A freeze token created during tick \(t\) becomes active at the beginning of tick:

\[
t+1
\]

A token with `remaining_ticks = d` is active for exactly \(d\) subsequent ticks.

Newly created tokens are not decremented during their creation tick.

## 18.4 Expiration

At end of each active tick:

```text
remaining_ticks -= 1
```

A token is removed when the value reaches zero.

## 18.5 Stacking

Core stack policies are:

```text
INDEPENDENT
MAX_DURATION
SUM_DURATION
REPLACE
REJECT_NEW
```

The stack policy is evaluated by `stack_group`.

The stack-group identity key is `(target_id, stack_group)`. Tokens remain separate authoritative records; stacking never merges source identity, metadata, or token identifiers.

`INDEPENDENT` always inserts the new token. `REPLACE` removes every existing token with the same group key before inserting the new token. `REJECT_NEW` leaves the existing group unchanged when that group is nonempty.

`MAX_DURATION` and `SUM_DURATION` require every token in the group to have identical `domains`, `accrual_policy`, and `stack_policy`; an incompatible insertion produces `STATE_INVARIANT_FAILURE` before mutation. `MAX_DURATION` inserts the token normally, so the group remains active wherever any compatible member is active and expires at the latest member expiration. `SUM_DURATION` sets the new token's activation tick to the later of its normal activation tick and the latest exclusive expiration tick in the group, thereby serializing group durations without merging token records.

When overlapping active `PROGRESSION` tokens use different accrual policies, `HOLD` dominates `ACCRUE`. Other frozen domains use set-union semantics: a domain is frozen when any active token includes it.

## 18.6 Hit-Stop

Hit-stop is modeled using one or more freeze tokens.

A hit-stop definition MUST explicitly state which domains are frozen.

Holding action progression alone does not automatically freeze:

- Input capture
- Buffer expiration
- Interaction emission
- Movement
- Physics
- Cooldowns
- Presentation

Those decisions are profile or game rules and MUST be explicit.

---

# 19. Semantic Facts

## 19.1 Fact Binding

An action definition MAY emit semantic facts when predicates are true.

A fact binding contains:

```text
id
direction
when
channels
tags
attributes
hit_policy
effect_templates
extensions
```

## 19.2 Directions

Core directions are:

```text
OFFENSE
DEFENSE
NEUTRAL
```

Directions are descriptive, not a global priority system.

An action MAY emit offense and defense facts simultaneously.

For example, an armored attack may independently:

- Emit an outgoing strike fact
- Emit an incoming armor defense fact

Resolving the incoming candidate MUST NOT automatically erase the action’s outgoing candidate.

## 19.3 Channels

Channels are canonical symbols.

Example channels include:

```text
STRIKE
PROJECTILE
THROW
HAZARD
HEAL
TRIGGER
PICKUP
```

These names are not assigned universal semantics by PCAM Core.

Interaction rules define their meaning.

## 19.4 Snapshot

Semantic facts are evaluated after action progression and post-advance transitions.

The resulting fact set is immutable for the interaction stage of the current tick.

Effects committed later in the tick do not retroactively change that fact set.

---

# 20. Interaction Candidates

## 20.1 Directed Model

Every interaction candidate is directed.

An interaction from entity A to entity B is separate from an interaction from B to A.

Mutual attacks therefore produce two candidates.

## 20.2 Candidate Structure

A candidate MUST contain:

```text
tick
candidate_id
source_entity_id
target_entity_id
source_action_instance_id
offense_fact_id
defense_fact_id, optional
contact_id
contact_partition
host_context
```

## 20.3 Contact Generation

PCAM Core does not define collision detection.

The host provides contacts from a declared immutable host snapshot.

For full deterministic conformance, the host contact generator MUST produce the same logical contact set for identical state.

## 20.4 Candidate Identifier

A candidate identifier MUST be derived deterministically from canonical candidate fields or allocated in a deterministic canonical order.

## 20.5 Canonical Candidate Order

Candidates are sorted by:

1. `source_entity_id`
2. `target_entity_id`
3. `source_action_instance_id`
4. `offense_fact_id`
5. `defense_fact_id`, with absence ordered before any identifier
6. `contact_partition`
7. `contact_id`
8. `candidate_id`

Host enumeration order is ignored.

## 20.6 Defense-Fact Selection

Defense facts are selected from the frozen semantic-fact snapshot for the candidate's current target. When `defense_fact_id` is present, only a matching `DEFENSE` fact is eligible. When it is absent, zero eligible facts yields no defense and exactly one eligible fact selects that fact. More than one eligible defense fact is ambiguous and produces `INVALID_CONTACT` before rule evaluation.

A profile that combines several defense facts MUST declare a deterministic defense-set extension defining applicability, composition, ordering, references, and trace behavior. Redirection repeats defense selection for the new current target using the same selector. No map or emission order may select among ambiguous defense facts.

## 20.7 Simultaneity

All candidates observe the same frozen semantic-fact snapshot.

Candidates do not observe damage, death, resource loss, or state changes caused by other candidates during the same interaction stage.

Consequently, simultaneous lethal attacks MAY both resolve successfully.

---

# 21. Typed Interaction Resolution

## 21.1 No Universal Property Hierarchy

PCAM v3 does not define a universal ordering such as:

```text
VOID > COUNTER > MITIGATE > IMPACT
```

Defense and offense properties are typed facts processed within directed candidates.

## 21.2 Decision Record

Each candidate begins with a decision record:

```text
status: ACCEPTED
current_target: original target
active_effect_templates: offense effect templates
decision_tags: empty set
generated_effects: empty list
receipt_requests: empty list
redirect_count: 0
visited_targets: [original target]
```

## 21.3 Fixed Rule Stages

Interaction rules execute through these stages:

```text
ADMISSION
ROUTING
MODIFICATION
MATERIALIZATION
REACTION
```

These are processing stages, not a universal ranking of semantic properties.

### `ADMISSION`

Determines whether the candidate is valid.

Examples:

- Ledger eligibility
- Channel acceptance
- Source validity
- Target validity
- Friendly-fire rules

### `ROUTING`

May reject, absorb, redirect, reflect, or replace the delivery path.

Examples:

- Invulnerability
- Parry
- Reflection
- Absorption

### `MODIFICATION`

Transforms accepted effect templates.

Examples:

- Armor
- Guard
- Resistance
- Damage scaling
- Stagger suppression

### `MATERIALIZATION`

Converts remaining effect templates into concrete effects.

### `REACTION`

Adds secondary effects or events.

Examples:

- Counter events
- Parry-success events
- Resource gains
- Camera or presentation cues
- Status reactions

## 21.4 Rule Structure

A rule contains:

```text
id
stage
order
condition
operations
stop_stage
stop_pipeline
extensions
```

Rule `order` values MUST be unique within a stage.

Rules execute in ascending `order`.

## 21.5 Core Rule Operations

Core operations include:

```text
REJECT
REDIRECT
REMOVE_EFFECT_CLASS
SCALE_EFFECT_CLASS
CAP_EFFECT_CLASS
REPLACE_EFFECT_CLASS
APPEND_EFFECT_TEMPLATE
MATERIALIZE
ADD_DECISION_TAG
REQUEST_RECEIPT
STOP_STAGE
STOP_PIPELINE
```

All scales and caps MUST use deterministic integer or ratio semantics.

`MATERIALIZE` converts the currently selected active templates into concrete effects in template order. Its optional `statuses` list defaults to `[ACCEPTED]` and, when present, MUST be a nonempty duplicate-free subset of `ACCEPTED` and `REJECTED`. Its optional `effect_classes` list restricts materialization to matching classes and, when present, MUST be nonempty, duplicate-free, and contain only nonempty identifiers. Materializing while the decision status is `REJECTED` requires `statuses` to include `REJECTED`, requires a nonempty `effect_classes` list, and every selected template MUST have class `REACTION`; otherwise the runtime faults before emitting effects.

## 21.6 Rejection

A rejected candidate does not materialize remaining offense effect templates.

Reaction rules MAY still emit explicitly permitted effects based on the rejection reason.

Appending a template does not emit it. `STOP_STAGE` or `STOP_PIPELINE` preserves the template in the decision record but prevents later stages from materializing it. A rejected candidate therefore emits a reaction only when an eligible rule executes an explicit rejected-status `MATERIALIZE` operation before the pipeline stops.

## 21.7 Redirection

A redirect changes the candidate target and restarts resolution from `ADMISSION`.

The runtime MUST track:

```text
redirect_count
visited_targets
```

Redirecting to an already visited target is invalid.

The simulation profile MUST define `max_redirects_per_candidate`.

Exceeding the limit produces a deterministic fault or rejection according to profile policy.

## 21.8 Independent Outgoing Actions

Resolving an incoming candidate against a defensive fact does not modify other candidates already present in the frozen candidate set unless a rule explicitly operates on them through a declared candidate-group mechanism.

Candidate-group mechanisms are extensions and are not part of PCAM Core v3.0.

---

# 22. Contact Policies and Ledgers

## 22.1 Purpose

A ledger prevents unintended repeated application and records interaction history needed for future deterministic behavior.

Ledger state is authoritative.

## 22.2 Core Hit Policies

Core policies are:

```text
UNBOUNDED
ONCE_PER_ACTION_INSTANCE
ONCE_PER_CYCLE
ONCE_PER_PREDICATE_ACTIVATION
COOLDOWN_TICKS
ONCE_PER_CONTACT_PARTITION
```

## 22.3 Ledger Key

A ledger key MUST include all fields required by the active policy.

Typical fields include:

```text
source_action_instance_id
offense_fact_id
target_entity_id
cycle
predicate_entry_serial
contact_partition
```

## 22.4 Receipt Timing

A fact MUST declare one receipt condition:

```text
ON_CONTACT
ON_ACCEPT
ON_IMPACT
```

### `ON_CONTACT`

The receipt is requested when the candidate is admitted for processing.

### `ON_ACCEPT`

The receipt is requested if the candidate remains accepted after routing.

### `ON_IMPACT`

The receipt is requested only if at least one authoritative impact effect is materialized.

## 22.5 Provisional Receipts

During candidate resolution, provisional receipt writes are visible to later candidates in canonical order.

This prevents duplicate same-tick impacts.

Provisional receipt order MUST follow canonical candidate ordering.

A rejected candidate that does not meet its receipt condition does not block a later candidate.

## 22.6 Hit-Stop Safety

Holding an action in an active state for multiple ticks MUST NOT automatically retrigger a once-limited hit.

The applicable ledger policy controls retriggering independently of phase or node progression.

---

# 23. Effects

## 23.1 Effect Envelope

An authoritative effect contains:

```text
effect_id
effect_type
effect_class
source_entity_id
target_entity_id
source_action_instance_id
origin_tick
priority
payload
reducer
authoritative
```

For node and transition effect declarations, an omitted target means the source action owner's entity identifier. A string target MUST be a Core action reference that resolves to an unsigned entity identifier. An omitted reducer is `ORDERED`. An omitted effect class is `PRESENTATION` for a non-authoritative effect and the effect type for an authoritative effect. Effect payload expressions are materialized at their emission position in the mutation order, and later state changes do not alter the materialized payload.

## 23.2 Effect Identifier

Effect identifiers MUST be stable across replay and rollback.

They SHOULD be derived from:

```text
origin_tick
source_action_instance_id
emission_serial
candidate_id, when applicable
rule_id, when applicable
operation_index
```

## 23.3 Authoritative and Presentation Effects

An authoritative effect modifies future simulation outcomes and MUST be included in deterministic processing.

A presentation effect does not modify authoritative state.

Examples of presentation effects:

- Sound request
- Particle request
- Camera shake
- UI notification
- Animation cue

Presentation consumers SHOULD deduplicate replayed events by `effect_id`.

## 23.4 Core Reducers

Effect types MUST declare one reducer:

```text
SUM
MIN
MAX
SET_UNION
ORDERED
FIRST
LAST
EXCLUSIVE
CUSTOM_DETERMINISTIC
```

`FIRST` and `LAST` refer to canonical effect order.

## 23.5 Canonical Effect Order

Effects are ordered by:

1. `target_entity_id`
2. `effect_type`
3. Descending `priority`
4. `source_entity_id`
5. `source_action_instance_id`
6. `effect_id`

## 23.6 Exclusive Effects

When multiple `EXCLUSIVE` effects target the same exclusive domain, the highest-priority canonical effect wins.

The losing effects remain visible in the deterministic trace with rejection reasons.

## 23.7 Custom Effects

A custom authoritative effect MUST define:

- Canonical payload schema
- Reducer
- Ordering behavior
- Overflow behavior
- Save and restore requirements
- Rollback behavior
- Determinism vectors

An undeclared custom effect is invalid.

---

# 24. Logical-Tick Execution Pipeline

A conforming runtime MUST execute each tick in the following order.

## Stage 1 — Tick-Start Snapshot

Freeze the authoritative tick-start state:

\[
S_t
\]

Activate scheduled inputs, events, and freeze tokens assigned to tick \(t\).

## Stage 2 — Input Ingestion

1. Validate inputs.
2. Deduplicate by input identifier.
3. Sort canonically.
4. Add eligible commands to buffers.
5. Generate direct action-start intents.

## Stage 3 — Pre-Advance Intent Evaluation

For each action in canonical instance order:

1. Evaluate eligible `PRE_ADVANCE` transitions.
2. Select at most one transition.
3. Produce transition intents.

## Stage 4 — Pre-Advance Arbitration

1. Merge start and transition intents.
2. Sort intents canonically.
3. Resolve claims atomically.
4. Apply accepted local transitions and action starts.
5. Reserve resources.
6. Consume inputs according to policy.

New actions accepted during this stage enter their initial node and MAY receive progression during the current tick.

## Stage 5 — Action Progression

For each running action in canonical instance order:

1. Check progression freezes.
2. Compute progression quanta.
3. Consume quanta.
4. Apply `AFTER_QUANTUM` transitions.
5. Enforce transition and quantum limits.
6. Stop if the action terminates or faults.

## Stage 6 — Post-Advance Intent Evaluation and Arbitration

1. Evaluate eligible `POST_ADVANCE` transitions.
2. Generate intents.
3. Resolve claims.
4. Apply accepted transitions.

Actions started during this stage do not consume progression quanta until the next tick, but their initial semantic facts MAY be present during the current interaction stage.

## Stage 7 — Semantic Snapshot

1. Evaluate predicates.
2. Update predicate edge serials.
3. Produce the immutable semantic-fact set.
4. Freeze action and defense facts for interaction resolution.

## Stage 8 — Contact and Candidate Generation

1. Request deterministic contacts from the host.
2. Build directed candidates.
3. Validate and normalize candidates.
4. Sort candidates canonically.

## Stage 9 — Interaction Resolution

For each candidate in canonical order:

1. Check ledger eligibility.
2. Execute interaction-rule stages.
3. Produce provisional receipts.
4. Produce effects.
5. Preserve trace information.

## Stage 10 — Effect Reduction and Commit

1. Merge action, transition, interaction, and host effects.
2. Group effects by target and effect domain.
3. Apply reducers.
4. Commit authoritative state changes.
5. Queue next-tick events.
6. Create next-tick freeze tokens.
7. Apply interaction receipts.
8. Apply termination and spawn effects.

Effects committed during this stage do not generate new interaction candidates during the current tick.

## Stage 11 — Maintenance

1. Decrement active freeze-token durations.
2. Decrement eligible buffer lifetimes.
3. Remove expired buffers.
4. Remove expired freeze tokens.
5. Clear one-tick event inboxes.
6. Finalize parent-child results.
7. Advance deterministic identifier counters.
8. Validate invariants.

## Stage 12 — Snapshot and Digest

1. Increment the logical tick.
2. Produce the canonical state encoding.
3. Compute the state digest.
4. Store rollback snapshot data as required by the active profile.
5. Emit non-authoritative trace and presentation output.

---

# 25. Events

## 25.1 Event Envelope

An authoritative event contains:

```text
event_id
event_type
source_id
target_id
origin_tick
delivery_tick
payload
delivery_mode
```

## 25.2 Delivery

Events emitted during tick \(t\) have default delivery tick:

\[
t+1
\]

An event MUST NOT become visible during the same interaction stage in which it was created.

## 25.3 Delivery Modes

Core modes are:

```text
TARGET_ACTION
TARGET_ENTITY
BROADCAST
PARENT
CHILD
```

## 25.4 Lifetime

Core events are available only during their delivery tick.

When `EVENT_DELIVERY` is frozen for a target action on an event's delivery tick, the event is not visible or expired. The runtime MUST set `delivery_tick` to the next logical tick and retain the modified envelope in authoritative pending-event state. Repeated frozen delivery ticks repeat this one-tick deferral. Entity and broadcast delivery are unaffected unless an authoritative extension defines corresponding freeze targeting.

Persistent conditions MUST be represented as:

- Registers
- Resources
- Status state
- Freeze tokens
- Other explicit authoritative records

---

# 26. RNG Requirements

## 26.1 Stream Ownership

Every authoritative RNG use MUST identify a stream.

Recommended stream scopes include:

```text
SIMULATION
ENTITY
ACTION_INSTANCE
INTERACTION_RULE
```

## 26.2 Snapshot State

Each stream MUST serialize:

```text
algorithm_id
state
stream_selector, if applicable
draw_count
```

## 26.3 Call Ordering

RNG draws MUST occur only through explicit expression or effect operations.

Candidate enumeration and hash-map order MUST NOT change RNG call count.

A rule SHOULD derive candidate-local random values from stable keys rather than consuming one shared sequential stream when order independence is desired.

## 26.4 Canonical RNG Profile

The reference implementation SHOULD provide:

```text
pcam.pcg32.v1
```

The conformance repository MUST include exact output vectors for every supported canonical RNG profile.

Implementations MAY support other RNG algorithms but MUST identify them in the definition-set hash.

---

# 27. Canonical Serialization and Hashing

## 27.1 Purpose

Canonical serialization supports:

- Replay verification
- Rollback comparison
- Cross-implementation testing
- Desynchronization detection
- Definition identity

## 27.2 PCAM-CJ1

PCAM v3 defines canonical JSON encoding profile `PCAM-CJ1`.

Rules:

1. Encoding is UTF-8.
2. Strings are normalized to Unicode NFC.
3. Definition identifiers remain restricted to canonical ASCII syntax.
4. Object keys are sorted by ascending UTF-8 byte sequence.
5. No insignificant whitespace is permitted.
6. Numbers are integers only.
7. Positive integers have no leading zero.
8. Negative zero is forbidden.
9. Booleans are encoded as `true` and `false`.
10. Null is encoded as `null`.
11. Arrays preserve defined order.
12. Sets are encoded as canonically sorted arrays.
13. Maps with non-string logical keys are encoded as sorted `[key,value]` arrays.
14. Optional field absence and explicit null are distinct.
15. Control characters are escaped.
16. Other normalized Unicode characters are emitted directly.
17. Unknown extension fields are ordered by namespace and field identifier.
18. Floating-point literals are invalid.

## 27.3 Definition Hash

A definition hash is:

\[
\operatorname{SHA256}(\operatorname{PCAM\text{-}CJ1}(\text{definition}))
\]

## 27.4 Definition-Set Hash

The definition-set hash is computed from the canonically sorted list of:

```text
definition_id
definition_hash
interaction_profile_hash
effect_registry_hash
extension_registry_hash
runtime_profile_hash
```

## 27.5 State Digest

The state digest is:

\[
D_t=\operatorname{SHA256}(\operatorname{PCAM\text{-}CJ1}(S_t))
\]

Presentation state MUST NOT be included.

All authoritative extension state MUST be included.

## 27.6 Optimized Internal Encodings

Implementations MAY use binary internal state or custom snapshot compression.

They MUST remain capable of producing the canonical digest required by conformance tests.

---

# 28. Save and Restore

## 28.1 Snapshot Boundary

Canonical snapshots are captured after effect commit and maintenance, at the boundary before the next tick’s input processing.

## 28.2 Required Snapshot Contents

A snapshot MUST include:

- Logical tick
- Definition-set hash
- Entity state
- Resource banks
- Action instances
- Buffers
- Events pending delivery
- Freeze tokens
- Parent-child relationships
- Interaction ledgers
- Predicate serials
- RNG state
- Identifier generators
- Fault state
- Authoritative host state
- Authoritative extension state

## 28.3 Round-Trip Requirement

A conforming snapshot codec MUST satisfy:

\[
\operatorname{decode}(\operatorname{encode}(S))=S
\]

## 28.4 Continuation Equivalence

For any valid state \(S_t\) and future inputs \(I_{t:n}\):

\[
\operatorname{run}(S_t,I_{t:n})
=
\operatorname{run}(\operatorname{restore}(\operatorname{save}(S_t)),I_{t:n})
\]

Both executions MUST produce identical state digests and effects.

---

# 29. Networking Profiles

PCAM Core does not require one networking topology.

A networked implementation MUST declare one or more profiles.

## 29.1 Local Deterministic Profile

Requirements:

- Canonical tick execution
- Canonical state hashing
- Save and restore
- No network behavior required

## 29.2 Lockstep Profile

Requirements:

- Inputs assigned to logical ticks
- Identical definition-set hashes
- Identical deterministic host behavior
- No tick advances until required inputs are available or deterministically predicted
- Periodic state-digest exchange
- Defined desynchronization policy

## 29.3 Rollback Profile

Requirements:

1. Save authoritative snapshots.
2. Retain canonical input history.
3. Predict missing inputs through a declared deterministic predictor.
4. Detect corrected or late inputs.
5. Restore the latest snapshot preceding the earliest changed tick.
6. Replace predicted input with authoritative input.
7. Resimulate every affected tick.
8. Recompute state digests.
9. Reconcile presentation effects by stable effect identifiers.
10. Preserve deterministic RNG and identifier allocation.

The rollback state MUST include the entire host-authoritative state required for resimulation.

## 29.4 Server-Authoritative Prediction Profile

Requirements:

- Server assigns authoritative ticks and outcomes.
- Clients MAY predict.
- Server corrections identify an authoritative state or tick.
- Clients restore or replace sufficient complete state.
- Clients resimulate or discard invalid predictions according to profile.
- Presentation interpolation MAY smooth visual corrections.

## 29.5 Phase-Only Reconciliation

The following is non-conforming for deterministic correction:

```text
set local phase equal to remote phase
```

unless every other authoritative value is already proven identical.

Phase snapping MAY be used for presentation alignment only.

It MUST NOT be described as rollback.

## 29.6 Latency

PCAM does not eliminate network latency.

A late defensive input affects a prior interaction only when the active network profile provides a mechanism such as:

- Rollback
- Server rewind
- Input delay
- Explicit lag compensation
- Client authority
- Forgiveness policy

The mechanism and its limits MUST be declared.

---

# 30. Fault Model

## 30.1 Definition Faults

The validator MUST reject definitions containing:

- Missing references
- Duplicate identifiers
- Duplicate transition priorities within a source and evaluation point
- Predicate cycles
- Invalid node durations
- Invalid target steps
- Unsupported authoritative effect types
- Unbounded collection declarations
- Invalid arithmetic policy
- Unknown required extensions
- Impossible resource ranges
- Invalid profile mappings
- Zero-duration transition loops
- Missing completion paths
- Invalid canonical identifiers

## 30.2 Runtime Faults

Runtime faults include:

```text
INTEGER_OVERFLOW
DIVISION_BY_ZERO
QUANTUM_LIMIT_EXCEEDED
TRANSITION_LIMIT_EXCEEDED
NESTING_LIMIT_EXCEEDED
REDIRECT_LIMIT_EXCEEDED
INVALID_HOST_IMPORT
INVALID_CONTACT
UNKNOWN_EFFECT
SNAPSHOT_DEFINITION_MISMATCH
RNG_PROFILE_MISMATCH
CANONICALIZATION_FAILURE
STATE_INVARIANT_FAILURE
```

## 30.3 Fault Policy

The runtime profile MUST declare one policy:

```text
ABORT_SIMULATION
FAULT_ACTION
FAULT_ENTITY
```

All peers in a deterministic session MUST use the same policy.

The runtime MUST NOT silently ignore an authoritative fault.

A runtime fault is action-attributable when it arises while evaluating or applying an operation initiated by an existing action instance. It is entity-attributable when it is action-attributable or when a direct action-start operation identifies an owner entity. Validation, snapshot identity, global capacity, canonicalization, and multi-source reduction faults without one unique initiating action or entity are unattributable.

`ABORT_SIMULATION` preserves the complete tick-start state and does not advance the logical tick.

`FAULT_ACTION` contains only an action-attributable fault. The runtime MUST restore the complete tick-start state, move the initiating action to `FAULTED`, apply its declared child-termination policies, store the fault record, discard every other mutation and effect from the failed tick, and advance the logical tick once. If the fault is not action-attributable, the runtime MUST apply `ABORT_SIMULATION` behavior.

`FAULT_ENTITY` contains an entity-attributable fault. The runtime MUST restore the complete tick-start state, move every nonterminal action owned by the initiating entity to `FAULTED`, remove those actions from active slot usage, store the fault record on the entity and in simulation fault state, discard every other mutation and effect from the failed tick, and advance the logical tick once. Surviving cross-entity parent or child links to a faulted action MUST be detached. If the fault is not entity-attributable, the runtime MUST apply `ABORT_SIMULATION` behavior.

A contained fault produces a successful tick result whose trace identifies the fault, attribution, policy, and containment. Inputs assigned to the contained tick are consumed by the tick advance. No entry, exit, transition, interaction, authoritative, or presentation effect from the failed attempt is emitted. Fault containment itself MUST be deterministic and included in snapshots and state digests.

---

# 31. Required Limits

Every runtime profile MUST declare at least:

```text
max_actions_per_entity
max_action_nesting_depth
max_children_per_action
max_quanta_per_action_per_tick
max_internal_transitions_per_action_per_tick
max_buffer_entries_per_action
max_pending_events_per_entity
max_candidates_per_tick
max_effects_per_tick
max_redirects_per_candidate
max_definition_size_bytes
max_snapshot_size_bytes
max_extension_state_bytes
max_expression_depth
max_expression_nodes
```

`max_expression_depth` and `max_expression_nodes` MUST be positive. Every guard, predicate, interaction condition, and expression-valued effect payload uses these same profile limits. Exceeding either limit produces `STATE_INVARIANT_FAILURE` before expression results are applied.

The reference profile SHOULD initially use conservative finite values and expose them in its definition-set hash.

---

# 32. PCAM-24 Profile

## 32.1 Purpose

PCAM-24 is an optional authoring and visualization profile built on PCAM Core.

It provides:

- A 24-cell action wheel
- Familiar phase ranges
- Discrete phase visualization
- Compact action diagrams
- Migration support for earlier PCAM definitions

PCAM-24 does not make phase the complete action state.

## 32.2 Phase Domain

The projected phase is:

\[
\phi_{24}\in\{0,\ldots,23\}
\]

The projection MAY be absent for action states not mapped by the profile.

## 32.3 Authoring Model

A native PCAM-24 timeline contains exactly 24 authoring cells.

Each cell MAY contain zero or more semantic tags.

Example:

```yaml
profiles:
  pcam24:
    lifecycle: TERMINATE
    rate:
      scale: 5
      units_per_tick: 2
    tags:
      STARTUP:
        - [0, 10]
      ARMOR:
        - [6, 14]
      ACTIVE:
        - [10, 14]
      RECOVERY:
        - [14, 24]
```

Ranges are half-open:

\[
[start,end)
\]

Therefore:

```text
[10,14) = phases 10, 11, 12, 13
```

Wrapping ranges are forbidden.

A wrapping window MUST be represented by two non-wrapping ranges.

## 32.4 Overlapping Tags

Tags MAY overlap.

The preceding example means:

- Phases 6–9: startup and armor
- Phases 10–13: active and armor
- Phases 14–23: recovery

No precedence is implied by overlap.

## 32.5 Compilation

PCAM-24 authoring syntax MUST compile into an ordinary PCAM Core action definition.

A conforming compiler MUST generate:

- Core nodes or a seekable timeline node
- Core predicates corresponding to tags
- Explicit transitions
- Explicit lifecycle behavior
- Explicit cycle increments
- Full runtime state

The compiled Core definition is the normative execution artifact.

The original phase source is authoring syntax.

## 32.6 Rate Example

At a 60-tick host rate:

```yaml
scale: 5
units_per_tick: 2
```

produces:

\[
\frac{2}{5}
\]

PCAM-24 cells per logical tick.

Twenty-four cells therefore consume:

\[
24 \times \frac{5}{2}=60
\]

logical ticks.

No fractional authoritative phase is stored.

The accumulator is authoritative.

## 32.7 Lifecycle Policies

Core PCAM-24 lifecycle policies are:

```text
TERMINATE
LOOP
CLAMP
```

### `TERMINATE`

Advancing beyond cell 23 terminates the action.

### `LOOP`

Advancing beyond cell 23:

1. Increments `cycle`
2. Returns the timeline cursor to cell 0
3. Increments the applicable predicate-entry serials as predicates reactivate

### `CLAMP`

Upon reaching cell 23:

- The cursor remains at 23.
- Progression accrual is held.
- The action remains running.
- An explicit transition or termination condition is required.

## 32.8 Phase Skips

A PCAM-24 phase skip compiles to an explicit transition targeting a seekable timeline step.

No intermediate phase semantics fire automatically.

## 32.9 Projection State

The phase projection MAY be computed from:

```text
current_node
node_step
profile projection map
```

The projection is suitable for:

- Debuggers
- Animation sampling
- VFX
- Audio
- UI
- Network telemetry
- Designer tools

It is not sufficient for:

- Save state
- Rollback
- Hit history
- Stall state
- Input buffering
- Child relationships
- RNG
- Resource ownership
- Deterministic reconciliation

## 32.10 PCAM-24 Compatibility Statement

A conforming PCAM-24 implementation MUST state:

> The phase value is one projected coordinate of a larger authoritative action state. Equal phase values do not imply equal complete states.

---

# 33. Canonical Action Example

The machine-valid, executable repository artifact for this section is `examples/heavy-strike.action.yaml`, with its dependency in `examples/dodge.action.yaml` and pinned execution evidence in `examples/heavy-strike.scenario.json`. The listing below is the readable design form; repository conformance claims use the machine-valid artifact.

The following example defines a heavy strike with:

- Twenty-four semantic quanta
- Rational progression of two quanta every five logical ticks
- Armor overlapping startup and active periods
- One hit per target per action instance
- Explicit startup, active, and recovery nodes
- A PCAM-24 projection

```yaml
pcam_version: "3.0"
kind: action
id: greyforge.example.heavy_strike
revision: 1

metadata:
  display_name: Heavy Strike
  nominal_host_tick_rate: 60
  nominal_duration_ticks: 60

limits:
  max_internal_transitions_per_tick: 8
  buffer_capacity: 4
  buffer_overflow_policy: DROP_OLDEST

rate:
  scale: 5
  units_per_tick: 2

parameters:
  damage:
    type: I64
    required: false
    default: 30
    minimum: 0
    maximum: 10000

registers:
  charge_level:
    type: U64
    initial: 0
    minimum: 0
    maximum: 3
    overflow: FAULT

imports:
  grounded:
    type: BOOL
    authoritative: true

initial_node: startup

slot_claims:
  - slot: FULL_BODY
    amount: 1

nodes:
  startup:
    mode: TIMED
    duration_quanta: 10
    seekable: true
    entry_assignments: []
    entry_effects:
      - effect_type: presentation.animation
        authoritative: false
        payload:
          clip: heavy_strike

  active:
    mode: TIMED
    duration_quanta: 4
    seekable: true
    entry_assignments: []
    entry_effects: []

  recovery:
    mode: TIMED
    duration_quanta: 10
    seekable: true
    entry_assignments: []
    entry_effects: []

predicates:
  STARTUP:
    track_edges: true
    expression:
      op: eq
      args:
        - ref: action.node
        - literal: startup

  ACTIVE:
    track_edges: true
    expression:
      op: eq
      args:
        - ref: action.node
        - literal: active

  RECOVERY:
    track_edges: true
    expression:
      op: eq
      args:
        - ref: action.node
        - literal: recovery

  ARMOR:
    track_edges: true
    expression:
      op: or
      args:
        - op: and
          args:
            - op: eq
              args:
                - ref: action.node
                - literal: startup
            - op: gte
              args:
                - ref: action.node_step
                - literal: 6
        - op: eq
          args:
            - ref: action.node
            - literal: active

  LATE_CANCEL:
    track_edges: true
    expression:
      op: and
      args:
        - op: eq
          args:
            - ref: action.node
            - literal: recovery
        - op: gte
          args:
            - ref: action.node_step
            - literal: 7

semantic_facts:
  - id: heavy_strike_hit
    direction: OFFENSE
    when:
      ref: action.predicate.ACTIVE
    channels:
      - STRIKE
    tags:
      - HEAVY
    hit_policy:
      kind: ONCE_PER_ACTION_INSTANCE
      receipt_on: ON_IMPACT
    effect_templates:
      - effect_type: combat.damage
        effect_class: DAMAGE
        authoritative: true
        payload:
          amount:
            ref: action.parameter.damage

      - effect_type: combat.stagger
        effect_class: STAGGER
        authoritative: true
        payload:
          amount: 25

  - id: heavy_strike_armor
    direction: DEFENSE
    when:
      ref: action.predicate.ARMOR
    channels:
      - STRIKE
    tags:
      - ARMOR
      - SUPER_ARMOR
    attributes:
      armor_strength: 1

transitions:
  - id: startup_to_active
    source_node: startup
    evaluation_point: AFTER_QUANTUM
    priority: 100
    guard:
      op: gte
      args:
        - ref: action.node_step
        - literal: 10
    target:
      kind: NODE
      node: active

  - id: active_to_recovery
    source_node: active
    evaluation_point: AFTER_QUANTUM
    priority: 100
    guard:
      op: gte
      args:
        - ref: action.node_step
        - literal: 4
    target:
      kind: NODE
      node: recovery

  - id: recovery_to_terminate
    source_node: recovery
    evaluation_point: AFTER_QUANTUM
    priority: 100
    guard:
      op: gte
      args:
        - ref: action.node_step
        - literal: 10
    target:
      kind: TERMINATE

  - id: recovery_cancel_to_dodge
    source_node: recovery
    evaluation_point: POST_ADVANCE
    priority: 200
    guard:
      ref: action.predicate.LATE_CANCEL
    input_match:
      command_id: DODGE
    claims:
      - kind: RESOURCE
        resource: STAMINA
        amount: 20
    consume_policy: ON_ACCEPT
    target:
      kind: ACTION
      action: greyforge.example.dodge
      source_disposition: TERMINATE_SOURCE

profiles:
  pcam24:
    lifecycle: TERMINATE
    projection:
      - node: startup
        step_range: [0, 10]
        phase_range: [0, 10]

      - node: active
        step_range: [0, 4]
        phase_range: [10, 14]

      - node: recovery
        step_range: [0, 10]
        phase_range: [14, 24]

    tags:
      STARTUP:
        - [0, 10]
      ARMOR:
        - [6, 14]
      ACTIVE:
        - [10, 14]
      RECOVERY:
        - [14, 24]
```

---

# 34. Canonical Interaction Example

The machine-valid, executable repository artifact for this section is `examples/combat.interaction.yaml`. Its armor, parry, duplicate-contact, and independent-outgoing behavior is exercised by the pinned Heavy Strike scenario and reference tests.

The following interaction profile demonstrates typed parry and armor behavior without a global property hierarchy.

```yaml
pcam_version: "3.0"
kind: interaction_profile
id: greyforge.example.combat
revision: 1

rules:
  - id: reject_invalid_target
    stage: ADMISSION
    order: 10
    condition:
      op: eq
      args:
        - ref: target.lifecycle
        - literal: TERMINATED
    operations:
      - op: REJECT
        reason: INVALID_TARGET
    stop_pipeline: true

  - id: parry_strike
    stage: ROUTING
    order: 100
    condition:
      op: and
      args:
        - op: contains
          args:
            - ref: offense.channels
            - literal: STRIKE
        - op: contains
          args:
            - ref: defense.tags
            - literal: PARRY
    operations:
      - op: REJECT
        reason: PARRIED

      - op: APPEND_EFFECT_TEMPLATE
        effect:
          effect_type: combat.parry_success
          effect_class: REACTION
          authoritative: true
          target: candidate.target_entity_id
          payload:
            attacker:
              ref: candidate.source_entity_id

      - op: REQUEST_RECEIPT
        condition: ON_ACCEPT
    stop_pipeline: true

  - id: armor_reduces_stagger
    stage: MODIFICATION
    order: 200
    condition:
      op: and
      args:
        - op: contains
          args:
            - ref: offense.channels
            - literal: STRIKE
        - op: contains
          args:
            - ref: defense.tags
            - literal: ARMOR
    operations:
      - op: SCALE_EFFECT_CLASS
        effect_class: STAGGER
        numerator: 0
        denominator: 1

  - id: materialize_remaining_effects
    stage: MATERIALIZATION
    order: 1000
    condition:
      literal: true
    operations:
      - op: MATERIALIZE
```

In this example:

- Parry applies only to an incoming strike candidate.
- Armor removes stagger from an incoming strike candidate.
- Neither rule automatically removes the defender’s own separately generated outgoing attack candidate.
- Mutual attacks remain independently resolvable from the frozen semantic snapshot.

---

# 35. Observability and Deterministic Tracing

A conforming reference runtime MUST be capable of producing a deterministic trace containing:

```text
tick
input order
buffer changes
eligible transitions
selected transitions
rejected intents
claim failures
resource reservations
progression quanta
node changes
predicate changes
active semantic facts
contact candidates
candidate order
interaction rules fired
decision-record mutations
provisional receipts
effects emitted
effect reduction
state changes
faults
state digest
```

Trace data is non-authoritative.

For identical execution, trace records SHOULD be byte-identical after canonicalization.

The runtime SHOULD provide concise rejection reasons rather than merely reporting that a transition did not occur.

---

# 36. Extension Model

## 36.1 Namespaces

Extensions MUST use reverse-domain or organization-qualified namespaces.

Example:

```text
tech.greyforge.pcam.physics
```

## 36.2 Required and Optional Extensions

A definition MUST classify each extension as:

```text
REQUIRED
OPTIONAL
```

A runtime encountering an unknown required extension MUST reject the definition.

A runtime MAY ignore an unknown optional extension only when the extension declares that omission cannot alter authoritative semantics.

## 36.3 Authoritative Extensions

An authoritative extension MUST define:

- Schema
- Canonical encoding
- Validation
- Runtime semantics
- Ordering
- Fault behavior
- Snapshot state
- Rollback behavior
- Determinism vectors

## 36.4 Arbitrary Code

Portable PCAM definition files MUST NOT embed arbitrary executable code.

Host-native extension modules MAY execute code, but they reduce portability and MUST be included in the definition-set identity.

An authoritative host-native module MUST be loaded only through an explicit runtime registration. The host MUST verify the SHA-256 of the exact registered module source artifact against the declared implementation hash before execution. Runtime hook identifiers and ordering contracts MUST be allowlisted by the implementation and included in extension identity. Portable documents MUST NOT select filesystem paths, network locations, import names, or arbitrary callbacks. A missing source artifact, hash mismatch, or unknown hook MUST fail closed before simulation starts.

---

# 37. Conformance Classes

## 37.1 `PCAM-DEF-3`

Definition-tool conformance.

Requires:

- Schema validation
- Reference resolution
- Graph validation
- Predicate-cycle detection
- Priority validation
- Limit validation
- Canonical hashing
- Meaningful diagnostics

## 37.2 `PCAM-RUN-3`

Core runtime conformance.

Requires:

- Normative tick pipeline
- Action progression
- Transitions
- Predicates
- Buffers
- Intents and claims
- Parent-child actions
- Freeze tokens
- Interaction resolution
- Ledgers
- Effect reduction
- Snapshot and restore
- Canonical state digest

## 37.3 `PCAM-DET-3`

Full deterministic-host conformance.

Requires:

- `PCAM-RUN-3`
- Deterministic host imports
- Deterministic contact generation
- Deterministic host effects
- Deterministic numeric behavior
- Cross-run state-digest identity

## 37.4 `PCAM-RB-3`

Rollback conformance.

Requires:

- `PCAM-DET-3`
- Input history
- Snapshot history
- Restore and resimulation
- Prediction declaration
- Late-input correction
- Presentation-effect deduplication
- Rollback-equivalence vectors

## 37.5 `PCAM-24-3`

PCAM-24 profile conformance.

Requires:

- Valid 24-cell authoring schema
- Correct half-open range semantics
- Overlapping tags
- Correct lifecycle compilation
- Correct rational-rate advancement
- Correct phase projection
- Explicit migration warnings
- No phase-only state claims

---

# 38. Mandatory Conformance Tests

The official conformance suite MUST include at least the following tests.

## 38.1 State Sufficiency

Two states with equal phase but different stall counters MUST:

- Serialize differently
- Hash differently
- Produce their correct distinct future behavior

## 38.2 Cycle Distinction

Two looping instances at phase zero but different cycle values MUST remain distinct.

## 38.3 Once-Per-Action Hit During Freeze

An active attack frozen for multiple ticks MUST NOT repeatedly hit the same target under `ONCE_PER_ACTION_INSTANCE`.

## 38.4 Once-Per-Cycle

A looping attack MUST hit once per target per declared cycle and become eligible after cycle increment.

## 38.5 Predicate Reactivation

A once-per-predicate-activation attack MUST become eligible after its enabling predicate exits and re-enters.

## 38.6 Explicit Skip

Skipping from one seekable step to another MUST emit only explicitly declared transition behavior.

## 38.7 Buffer Expiration

Buffer TTL behavior MUST remain identical across freeze and non-freeze cases according to the selected freeze domains.

## 38.8 Resource Arbitration

Competing actions attempting to spend the same resource MUST produce the same accepted intent under every candidate enumeration order.

## 38.9 Slot Replacement

An action replacement MUST not terminate the source when the target cannot acquire its required slots.

## 38.10 Parent-Child Restore

Saving and restoring during a child action MUST preserve:

- Parent freeze
- Child identity
- Child slot
- Child result behavior
- Future state hashes

## 38.11 Simultaneous Trade

Two simultaneous lethal attacks MUST resolve according to the frozen candidate snapshot and declared effect reducer.

## 38.12 Armor with Outgoing Attack

An armored active attack MUST be able to mitigate an incoming candidate without deleting its separately generated outgoing candidate.

## 38.13 Candidate Permutation

Permuting raw host contact enumeration MUST not alter final state.

## 38.14 Same-Tick Duplicate Contact

Multiple duplicate contacts for one once-limited fact MUST produce one applicable effect according to canonical candidate order.

## 38.15 Redirect Loop

A reflection cycle MUST terminate deterministically through visited-target or redirect-limit enforcement.

## 38.16 Save-Restore Equivalence

Uninterrupted and restored execution MUST produce identical state digests.

## 38.17 Rollback Equivalence

A late corrected input followed by rollback and resimulation MUST produce the same final state as an execution that received the correct input initially.

## 38.18 RNG Restore

Restoring immediately before a random draw MUST reproduce the same draw and future stream state.

## 38.19 Cross-Architecture Digest

The reference suite MUST produce identical canonical digests on at least:

- x86-64
- ARM64

## 38.20 Invalid Definitions

The validator MUST reject malformed and ambiguous definitions using stable error codes.

---

# 39. Property-Based Testing Requirements

The reference implementation MUST include property-based or generated testing for:

- Random valid action graphs
- Random transition guards
- Random rate scales and units
- Random freeze-token combinations
- Random input order permutations
- Random candidate permutations
- Random save and restore points
- Random rollback corrections
- Random interaction-rule sets within defined bounds
- Random effect aggregation
- Random parent-child structures within limits

At minimum, generated tests MUST verify:

\[
\text{same state}+\text{same inputs}
\Rightarrow
\text{same digest}
\]

and:

\[
\text{save/restore}
\Rightarrow
\text{continuation equivalence}
\]

---

# 40. Migration from PCAM v1 and v2

| Legacy concept | PCAM v3 replacement |
|---|---|
| Sole authoritative phase | Complete action-instance state |
| \(\mathbb Z_{24}\) runtime ontology | Optional PCAM-24 profile |
| Phase-entry timestamp | Logical tick plus predicate/transition serial |
| Fixed phase progression | Integer quanta with rational-rate accumulator |
| Named windows | Named pure predicates |
| Overlapping windows | Simultaneously true predicates |
| Stall at phase | Explicit freeze token |
| Skip phase | Explicit transition to seekable target |
| Wrap | Explicit cycle boundary and lifecycle policy |
| Nested phase | Parent-child action instances |
| Global precedence matrix | Typed directed interaction rules |
| `ActionID + Phase` replication | Complete authoritative snapshot or deterministic input history |
| Phase snapping | Presentation correction or non-conforming approximation |
| Phase-based hit uniqueness | Authoritative contact ledger |
| Animation observes phase | Presentation observes complete semantic state and optional phase projection |
| Perfect determinism claim | Determinism conditioned on declared host contract |

## 40.1 Legacy Importer

A legacy importer MAY translate old PCAM YAML into a draft PCAM-24 v3 source definition.

The importer MUST emit warnings for:

- Overlapping or contradictory windows
- Missing stall state
- Missing hit policy
- Missing cycle identity
- Undefined skip effects
- Undefined nesting return behavior
- Universal precedence assumptions
- Phase-only networking declarations
- Floating timing assumptions
- Missing deterministic limits

Imported definitions MUST undergo manual review before being treated as normative.

## 40.2 Version Compatibility

PCAM v3 is not wire-compatible with PCAM v1 or v2.

A v3 implementation MUST NOT silently interpret a v1 or v2 definition as v3.

---

# 41. Repository Requirements

The PCAM v3 repository SHOULD use this structure:

```text
pcam/
├── README.md
├── STATUS.md
├── CHANGELOG.md
├── LICENSES/
├── spec/
│   ├── PCAM-v3.md
│   ├── state-model.md
│   ├── transition-model.md
│   ├── interaction-model.md
│   ├── networking-profiles.md
│   └── conformance.md
├── schemas/
│   ├── action.schema.json
│   ├── interaction-profile.schema.json
│   ├── runtime-profile.schema.json
│   ├── snapshot.schema.json
│   └── pcam24.schema.json
├── reference/
│   ├── runtime/
│   ├── validator/
│   ├── compiler/
│   ├── canonicalizer/
│   └── trace-viewer/
├── profiles/
│   └── pcam24/
├── tests/
│   ├── valid/
│   ├── invalid/
│   ├── vectors/
│   ├── rollback/
│   ├── generated/
│   └── cross-platform/
├── experiments/
│   ├── methodology/
│   ├── baselines/
│   └── results/
└── archive/
    ├── v1/
    ├── v2/
    └── legacy-claims/
```

Documentation builds alone MUST NOT be treated as proof of runtime correctness.

---

# 42. Reference Tooling Requirements

The initial PCAM v3 implementation SHOULD provide:

```text
pcam validate <definition>
pcam compile <source>
pcam canonicalize <file>
pcam definition-hash <file>
pcam run <vector>
pcam trace <vector>
pcam snapshot <vector>
pcam restore <snapshot>
pcam state-hash <snapshot>
pcam rollback-test <scenario>
pcam migrate-v2 <legacy-definition>
```

Every command MUST return stable machine-readable result codes.

---

# 43. Licensing Recommendation

To support implementation and adoption:

- The specification SHOULD use **CC BY 4.0**.
- Reference code SHOULD use **Apache-2.0** or **MIT**.
- Test vectors SHOULD permit unrestricted implementation use.
- Trademark policy SHOULD be separate from copyright licensing.
- Patent commitments, if any, SHOULD be explicit.

A no-derivatives license is not recommended for an executable technical standard intended to receive implementations and contributions.

---

# 44. Security and Robustness

PCAM definition files, snapshots, replays, and network inputs MUST be treated as untrusted data.

Implementations MUST validate:

- Collection lengths
- Recursion depth
- Definition size
- Snapshot size
- Integer bounds
- Identifier syntax
- Extension declarations
- Event counts
- Candidate counts
- Effect counts
- Redirect counts
- Buffer counts
- Child counts

Canonical state hashes provide integrity comparison, not authentication.

Authenticated multiplayer systems SHOULD sign or authenticate network messages separately.

Definition hashing does not make extension code safe.

---

# 45. Release Gates

PCAM v3 MUST NOT be labeled **Stable, Normative** until all of the following are complete.

## 45.1 Specification Gate

- No unresolved normative contradictions
- All core terms defined
- All algorithms bounded
- All ordering rules explicit
- All fault behavior explicit
- PCAM-24 clearly separated from Core

## 45.2 Schema Gate

- Machine-readable schema for every normative definition type
- Positive and negative schema vectors
- Canonical-hash vectors
- Version validation
- Extension validation

## 45.3 Reference Runtime Gate

- Complete reference interpreter
- Complete save and restore
- State hashing
- Deterministic tracing
- Interaction resolver
- PCAM-24 compiler
- No known divergence in normative vectors

## 45.4 Independent Implementation Gate

At least one implementation independent of the reference runtime MUST pass the normative vector suite.

A language port sharing the same execution code through bindings does not count as independent.

## 45.5 Cross-Platform Gate

Identical state digests MUST be demonstrated on at least:

- Linux x86-64
- Linux ARM64

Additional Windows and macOS validation is RECOMMENDED.

## 45.6 Rollback Gate

The rollback suite MUST demonstrate:

- Late input
- Mis-predicted input
- Multi-tick rewind
- Action start during rewind
- Hit-stop during rewind
- Child action during rewind
- RNG during rewind
- Interaction-ledger restoration
- Presentation-event deduplication

## 45.7 Comparative Experiment Gate

PCAM v3 SHOULD be compared against:

1. A conventional fixed-tick finite-state machine
2. A statechart with state-local counters
3. An animation-independent frame-data action system
4. PCAM Core without the PCAM-24 profile
5. PCAM Core with the PCAM-24 profile

Measurements SHOULD include:

- Runtime state size
- Snapshot size
- Resimulation cost
- Definition complexity
- Validation coverage
- Replay divergence rate
- Authoring effort
- Debug trace clarity
- Number of hidden assumptions
- Number of ambiguous interaction cases

## 45.8 Claims Gate

No project documentation may claim:

- Perfect determinism
- Elimination of latency
- Elimination of rollback
- Universally minimal network state
- Superior performance
- Production readiness
- Industry novelty

unless the exact claim is supported by reproducible evidence.

---

# 46. Normative Summary

A conforming PCAM v3 system obeys the following compact contract:

1. Logical ticks provide authoritative order.
2. Complete machine state is authoritative.
3. Phase is an optional projection, never the whole state.
4. Identical complete state and input produce identical results.
5. Presentation observes simulation and does not drive it.
6. Action progression uses bounded integer quanta.
7. Fractional rates use deterministic integer accumulators.
8. Semantic windows are pure named predicates.
9. Overlapping predicates are legal.
10. Transitions, cancellations, skips, and replacements are explicit.
11. Resource and slot conflicts use deterministic intent arbitration.
12. Stalls and hit-stop use explicit freeze tokens.
13. Nested actions use explicit parent-child instances.
14. Interactions are directed and resolved from a frozen snapshot.
15. Defensive properties affect specific incoming candidates rather than globally dominating all behavior.
16. Repeated contacts are controlled by authoritative ledgers.
17. Effects are declarative, reduced canonically, and committed after candidate resolution.
18. RNG, identifiers, buffers, freezes, ledgers, and relationships are snapshotted.
19. Rollback restores complete state and resimulates.
20. Phase-only correction is not rollback.
21. Full determinism depends on a deterministic host contract.
22. Every algorithm is bounded and every overflow or limit violation faults deterministically.
23. PCAM-24 remains available as a 24-cell authoring and visualization profile.
24. Conformance is established by executable vectors, not documentation claims.

---

# 47. Final Architectural Position

PCAM v3 is not a model in which one number replaces time, state, history, and networking.

It is a deterministic semantic action-machine standard.

Its central abstraction is:

\[
\text{Action Meaning}
=
\text{Control State}
+
\text{Discrete Progress}
+
\text{Explicit Predicates}
+
\text{Explicit History}
+
\text{Explicit Interaction Rules}
\]

Its central execution contract is:

\[
(S_{t+1},E_t)=F(S_t,I_t)
\]

Its relationship to phase is:

\[
\text{Phase}=P(S_t)
\]

where \(P\) is a profile-defined projection.

Therefore:

\[
\text{Equal Phase}
\not\Rightarrow
\text{Equal State}
\]

but:

\[
\text{Equal Complete State}
+
\text{Equal Input}
\Rightarrow
\text{Equal Outcome}
\]

That is the governing law of PCAM v3.
