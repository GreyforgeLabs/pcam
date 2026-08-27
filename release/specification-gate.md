# Specification Gate

State: CLOSED for `3.0.0-draft.1`

## Resolved contradictions and ambiguities

The source draft header pointed to release gates in §27. Release gates are defined in §45, while §27 defines canonical serialization and hashing. The repository specification now points to §45. The complete contradiction audit is recorded in `specification-audit.md`.

The source draft also required actions to enter an initial node without declaring how that node was selected. The repository specification and action schema now require an explicit `initial_node`; map insertion order has no semantic effect.

The complete audit resolved deferred progression state, atomic-group scope, freeze stacking and domain expansion, parent termination precedence, defense selection, materialization and rejected reactions, frozen-event lifetime, undeclared ordering/reference fields, and expression evaluation budgets. Exact decisions remain recorded in `../spec/open-issues.md`.

The schema-completeness audit later identified one additional conflict between the §14.1 canonical transition field list and omitted empty forms in the readable design example. §14.1 now requires explicit `null`, empty arrays, zero cycle delta, and empty metadata in machine documents while preserving the listing as labeled non-normative shorthand. The machine-valid examples contain every canonical field.

Reference-runtime work then exposed that three required transition operation fields lacked an execution position. §8.5, §14.6, §14.7, and §23.1 now define assignment targets, the complete operation order, source versus target ownership, initial-node entry behavior, effect defaults, and payload materialization timing.

Fault-policy implementation exposed a second executable ambiguity: the three declared policies had no attribution, rollback, tick-advance, or containment semantics. §30.3 now defines these behaviors and fail-closed escalation for unattributable faults.

Parameter execution exposed that declarations had no portable direct-start binding. §8.4 now binds direct inputs through a `parameters` payload object, requires validation before allocation and deep capture, and defines the default-only rule for action and child transition targets.

Host-import execution exposed that declarations had no exact tick-snapshot binding. §8.6 now defines the host `imports` object, typed supplied/default resolution, deep capture, fault behavior, and authoritative serialization.

## Required evidence

- no unresolved normative contradictions
- all core terms defined
- all algorithms bounded
- all ordering rules explicit
- all fault behavior explicit
- PCAM-24 clearly separated from Core

Evidence: `specification-audit.md` and `../reference/python/tests/test_specification_audit.py`.

This gate closure applies only to the current Normative Candidate text. Any new normative issue reopens the gate. It does not permit Stable, Normative status while the other §45 gates remain open.
