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
