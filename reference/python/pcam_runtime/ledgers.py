"""Authoritative interaction-ledger keys, eligibility, and provisional receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .canonical import canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode

HitPolicyKind = Literal[
    "UNBOUNDED",
    "ONCE_PER_ACTION_INSTANCE",
    "ONCE_PER_CYCLE",
    "ONCE_PER_PREDICATE_ACTIVATION",
    "COOLDOWN_TICKS",
    "ONCE_PER_CONTACT_PARTITION",
]
ReceiptCondition = Literal["ON_CONTACT", "ON_ACCEPT", "ON_IMPACT"]


@dataclass(frozen=True)
class HitPolicy:
    kind: HitPolicyKind
    receipt_on: ReceiptCondition
    cooldown_ticks: int | None = None
    predicate_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {
            "UNBOUNDED",
            "ONCE_PER_ACTION_INSTANCE",
            "ONCE_PER_CYCLE",
            "ONCE_PER_PREDICATE_ACTIVATION",
            "COOLDOWN_TICKS",
            "ONCE_PER_CONTACT_PARTITION",
        }:
            raise _fault(f"unknown hit policy: {self.kind}")
        if self.receipt_on not in {"ON_CONTACT", "ON_ACCEPT", "ON_IMPACT"}:
            raise _fault(f"unknown receipt condition: {self.receipt_on}")
        if self.kind == "COOLDOWN_TICKS" and (self.cooldown_ticks is None or self.cooldown_ticks <= 0):
            raise _fault("COOLDOWN_TICKS requires a positive cooldown")
        if self.kind == "ONCE_PER_PREDICATE_ACTIVATION" and not self.predicate_id:
            raise _fault("ONCE_PER_PREDICATE_ACTIVATION requires predicate_id")


@dataclass(frozen=True)
class LedgerContext:
    tick: int
    source_action_instance_id: int
    offense_fact_id: str
    target_entity_id: int
    cycle: int
    predicate_entry_serials: dict[str, int]
    contact_partition: str


@dataclass(frozen=True)
class Receipt:
    ledger_key: str
    origin_tick: int
    candidate_id: str
    condition: ReceiptCondition


def ledger_key(policy: HitPolicy, context: LedgerContext) -> str | None:
    if policy.kind == "UNBOUNDED":
        return None
    fields: dict[str, object] = {
        "fact": context.offense_fact_id,
        "instance": context.source_action_instance_id,
        "policy": policy.kind,
        "target": context.target_entity_id,
    }
    if policy.kind == "ONCE_PER_CYCLE":
        fields["cycle"] = context.cycle
    elif policy.kind == "ONCE_PER_PREDICATE_ACTIVATION":
        assert policy.predicate_id is not None
        fields["predicate"] = policy.predicate_id
        fields["predicate_entry_serial"] = context.predicate_entry_serials.get(policy.predicate_id, 0)
    elif policy.kind == "ONCE_PER_CONTACT_PARTITION":
        fields["contact_partition"] = context.contact_partition
    return canonical_hash(fields)


def is_eligible(
    ledger: dict[str, dict[str, object]],
    policy: HitPolicy,
    context: LedgerContext,
) -> bool:
    key = ledger_key(policy, context)
    if key is None:
        return True
    existing = ledger.get(key)
    if existing is None:
        return True
    if policy.kind == "COOLDOWN_TICKS":
        assert policy.cooldown_ticks is not None
        return context.tick - int(existing["origin_tick"]) >= policy.cooldown_ticks
    return False


def receipt_required(
    condition: ReceiptCondition,
    accepted_after_routing: bool,
    authoritative_impact_materialized: bool,
) -> bool:
    if condition == "ON_CONTACT":
        return True
    if condition == "ON_ACCEPT":
        return accepted_after_routing
    return authoritative_impact_materialized


def write_receipt(
    ledger: dict[str, dict[str, object]],
    policy: HitPolicy,
    context: LedgerContext,
    candidate_id: str,
) -> tuple[dict[str, dict[str, object]], Receipt | None]:
    key = ledger_key(policy, context)
    if key is None:
        return ledger, None
    updated = {item: dict(value) for item, value in ledger.items()}
    updated[key] = {
        "candidate_id": candidate_id,
        "condition": policy.receipt_on,
        "origin_tick": context.tick,
    }
    return updated, Receipt(key, context.tick, candidate_id, policy.receipt_on)


def _fault(message: str) -> PCAMError:
    return PCAMError(ResultCode.DEFINITION_REJECTED, PCAMFault.STATE_INVARIANT_FAILURE, message)
