# PCAM v3 Specification Audit

State: CLOSED for `3.0.0-draft.1`

Scope: master specification structure, terminology, deterministic boundaries, authoritative state, bounded algorithms, canonical ordering, fault behavior, Core versus PCAM-24 separation, and the normative issue ledger.

## Method

The audit compared every normative issue against the master text and the executable reference behavior, searched every specification and gate artifact for active ambiguity markers, checked all numbered top-level sections, traced each canonical ordering key back to its declared structure, and verified every security or recursion boundary against a declared runtime limit.

## Resolved findings

| Finding | Resolution |
|---|---|
| Release-gate pointer referred to §27 | Header points to §45 |
| Initial-node selection was implicit | `initial_node` is required; map order is non-authoritative |
| ACCRUE state omitted deferred quanta | §7.3 requires `deferred_quanta` |
| Intent group behavior was undefined | `atomic_group_id` is correlation-only in Core |
| Freeze stacking was incomplete | §18.5 defines group keys, compatibility, schedules, and precedence |
| `FREEZE_ALL_ACTION_LOGIC` was not expanded | §17.2 enumerates its exact domains |
| Parent termination precedence was undefined | §17.4 defines old-child and new-child ordering |
| Defense selection was ambiguous | §20.6 defines zero, one, and multiple-match behavior |
| `MATERIALIZE` was absent from the registry | §21.5 defines accepted and rejected-status materialization |
| Rejected reaction behavior was implicit | Append is non-emitting; explicit bounded materialization is required |
| Frozen event lifetime was undefined | §25.4 defines authoritative one-tick deferral |
| Intent ordering used an undeclared field | §15.2 includes `input_id` |
| Canonical example used an undeclared reference family | §11.3 includes `target.<field>` |
| Expression budgets were implementation defaults | §31 requires hashed depth and node limits |
| Canonical transition list conflicted with omitted empty design fields | §14.1 requires explicit machine-document defaults while allowing labeled readable shorthand |
| Required transition operations had no execution position | §8.5, §14.6, §14.7, and §23.1 define assignment targets, complete mutation order, initial entry, effect defaults, and payload timing |
| Fault policies named scopes without containment semantics | §30.3 defines attribution, tick-start rollback, scope mutation, tick advancement, records, discarded output, and escalation |
| Parameter declarations had no portable start binding | §8.4 defines direct-input bindings, validation timing, deep capture, and transition-target defaults |
| Host imports had no exact snapshot binding | §8.6 defines the host `imports` object, supplied/default resolution, validation, capture, faulting, and serialization |
| Owner references had no exact state paths or missing-value rule | §7.2 binds resource and register references to authoritative maps and fails missing identifiers |

## Gate conclusion

The current Normative Candidate text has no known internal contradiction. Its top-level sections are complete and uniquely ordered, Core and PCAM-24 claims are separated, and the issue ledger is closed. This audit closes only §45.1; every other gate retains its own current evidence state, and this audit does not permit a Stable, Normative label.
