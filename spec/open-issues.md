# PCAM v3 Open Normative Issues

Status: ACTIVE

Owner: PCAM specification gate

These issues prevent Stable, Normative status even when a reference behavior exists.

## Freeze stack merge semantics

Section 18.5 names `INDEPENDENT`, `MAX_DURATION`, `SUM_DURATION`, `REPLACE`, and `REJECT_NEW`, but does not completely define:

- the stack-group identity key
- whether tokens merge or remain individually serialized
- behavior when one group mixes domains or accrual policies
- which source identity and metadata survive a merge
- the exact activation schedule for summed durations

The Python reference currently uses `(target_id, stack_group)` as the group key, keeps tokens individually serialized, queues compatible `SUM_DURATION` tokens, lets `HOLD` dominate overlapping progression freezes, and faults incompatible `MAX_DURATION` or `SUM_DURATION` groups. This is provisional reference policy, not a closed normative decision.

## Deferred progression state

Section 10.3 requires generated quanta under `ACCRUE` to remain authoritative state. The §7.3 minimum action-instance field list does not name a deferred-quanta field. The Python reference now serializes `deferred_quanta`; the specification should still name it explicitly before the issue closes.

## Intent atomic groups

Section 15.2 includes `atomic_group_id` in the intent structure, while §15.4 defines atomicity only for all claims within one intent. Cross-intent group acceptance, rejection, ordering, and identifier allocation are not defined. The Python reference currently arbitrates each intent atomically and preserves the group identifier without assigning cross-intent behavior.

## Defense-fact selection

The interaction expression vocabulary includes `defense.<field>`, but the candidate structure identifies only the offense fact and target entity. The specification does not define how one defense fact is selected when a target emits several simultaneous defense facts, nor how conflicting defense attributes combine. The Python reference currently requires an explicit defense fact per target for the pure interaction resolver.

## Materialization operation registry

Section 21.5 lists core rule operations but omits `MATERIALIZE`, while the canonical interaction example uses `op: MATERIALIZE` and §21.3 requires a materialization stage. The Python reference recognizes `MATERIALIZE` provisionally. The master operation registry must be corrected before the specification gate closes.

## Event-delivery freeze lifetime

Sections 18.2 and 25 define `EVENT_DELIVERY` freezes and one-tick event availability, but do not state whether an event frozen on its delivery tick expires, faults, or moves to a later delivery tick. The Python reference provisionally defers the event by one tick and serializes the changed `delivery_tick`.

## Terminate-parent composition

Section 17.2 allows a child start to use `TERMINATE_PARENT`, while §17.4 independently requires a parent termination policy for each child slot. The ordering and precedence between the newly started child's parent policy and that slot's termination policy are not stated. The Python reference lets the newly started child continue when `TERMINATE_PARENT` is the launch policy and applies slot termination policies to later parent termination paths.

## Freeze-all action domains

`FREEZE_ALL_ACTION_LOGIC` is named but its exact domain expansion is not enumerated. The Python reference provisionally expands it to progression, pre/post transitions, input capture, and interaction emission/reception. Event delivery and buffer expiry remain separate explicit domains.
