"""Canonical all-or-nothing intent and claim arbitration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from .errors import PCAMError, PCAMFault, ResultCode
from .numeric import apply_u64

ClaimKind = Literal["RESOURCE", "ACTION_SLOT", "CHILD_SLOT", "EXCLUSIVE_KEY", "CAPACITY"]


@dataclass(frozen=True)
class Claim:
    kind: ClaimKind
    key: str
    amount: int = 1
    owner_id: int | None = None

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "claim amount is negative")


@dataclass(frozen=True)
class Intent:
    intent_kind: str
    intent_priority: int
    owner_entity_id: int
    source_action_instance_id: int
    transition_id: str
    input_sequence: int
    input_id: str
    claims: tuple[Claim, ...] = ()
    releases: tuple[Claim, ...] = ()
    operations: tuple[dict[str, object], ...] = ()
    atomic_group_id: str = "default"

    @property
    def identity(self) -> str:
        return (
            f"{self.owner_entity_id}:{self.source_action_instance_id}:"
            f"{self.transition_id}:{self.input_sequence}:{self.input_id}"
        )


@dataclass(frozen=True)
class ArbitrationState:
    resource_banks: dict[int, dict[str, int]] = field(default_factory=dict)
    capacities: dict[tuple[str, int, str], int] = field(default_factory=dict)
    usages: dict[tuple[str, int, str], int] = field(default_factory=dict)
    exclusive_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    accepted: bool
    reason: str


def canonical_intents(intents: tuple[Intent, ...]) -> tuple[Intent, ...]:
    return tuple(
        sorted(
            intents,
            key=lambda item: (
                -item.intent_priority,
                item.owner_entity_id,
                item.source_action_instance_id,
                item.transition_id.encode("utf-8"),
                item.input_sequence,
                item.input_id.encode("utf-8"),
            ),
        )
    )


def arbitrate(
    intents: tuple[Intent, ...],
    state: ArbitrationState,
) -> tuple[ArbitrationState, tuple[IntentDecision, ...]]:
    work = ArbitrationState(
        resource_banks={owner: dict(bank) for owner, bank in state.resource_banks.items()},
        capacities=dict(state.capacities),
        usages=dict(state.usages),
        exclusive_keys=frozenset(state.exclusive_keys),
    )
    decisions: list[IntentDecision] = []
    for intent in canonical_intents(intents):
        claims = _aggregate_claims(intent)
        releases = _aggregate_claims(intent, release=True)
        failure = _first_failure(intent, claims, releases, work)
        if failure is not None:
            decisions.append(IntentDecision(intent, False, failure))
            continue
        work = _reserve(intent, claims, releases, work)
        decisions.append(IntentDecision(intent, True, "ACCEPTED"))
    return work, tuple(decisions)


def allocate_action_instance_ids(
    decisions: tuple[IntentDecision, ...],
    next_action_instance_id: int,
) -> tuple[dict[str, int], int]:
    next_id = apply_u64(next_action_instance_id)
    allocated: dict[str, int] = {}
    for decision in decisions:
        if not decision.accepted:
            continue
        starts = sum(1 for operation in decision.intent.operations if "start_action" in operation)
        if starts:
            allocated[decision.intent.identity] = next_id
            next_id = apply_u64(next_id + starts)
    return allocated, next_id


def _aggregate_claims(intent: Intent, release: bool = False) -> tuple[Claim, ...]:
    aggregated: dict[tuple[str, int | None, str], int] = {}
    for claim in intent.releases if release else intent.claims:
        key = (claim.kind, claim.owner_id, claim.key)
        aggregated[key] = apply_u64(aggregated.get(key, 0) + claim.amount)
    return tuple(
        Claim(kind=kind, owner_id=owner_id, key=key, amount=amount)  # type: ignore[arg-type]
        for (kind, owner_id, key), amount in sorted(
            aggregated.items(),
            key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1], item[0][2].encode("utf-8")),
        )
    )


def _claim_owner(intent: Intent, claim: Claim) -> int:
    if claim.owner_id is not None:
        return claim.owner_id
    if claim.kind == "CHILD_SLOT":
        return intent.source_action_instance_id
    return intent.owner_entity_id


def _first_failure(
    intent: Intent,
    claims: tuple[Claim, ...],
    releases: tuple[Claim, ...],
    state: ArbitrationState,
) -> str | None:
    release_amounts = {
        (claim.kind, _claim_owner(intent, claim), claim.key): claim.amount
        for claim in releases
    }
    for claim in claims:
        owner = _claim_owner(intent, claim)
        if claim.kind == "RESOURCE":
            available = state.resource_banks.get(owner, {}).get(claim.key, 0)
            available += release_amounts.get((claim.kind, owner, claim.key), 0)
            if claim.amount > available:
                return f"RESOURCE_UNAVAILABLE:{owner}:{claim.key}"
        elif claim.kind == "EXCLUSIVE_KEY":
            if claim.key in state.exclusive_keys:
                return f"EXCLUSIVE_KEY_UNAVAILABLE:{claim.key}"
        else:
            capacity_key = (claim.kind, owner, claim.key)
            capacity = state.capacities.get(capacity_key, 0)
            usage = state.usages.get(capacity_key, 0)
            usage -= release_amounts.get((claim.kind, owner, claim.key), 0)
            if usage + claim.amount > capacity:
                return f"CAPACITY_UNAVAILABLE:{claim.kind}:{owner}:{claim.key}"
    return None


def _reserve(
    intent: Intent,
    claims: tuple[Claim, ...],
    releases: tuple[Claim, ...],
    state: ArbitrationState,
) -> ArbitrationState:
    banks = {owner: dict(bank) for owner, bank in state.resource_banks.items()}
    usages = dict(state.usages)
    exclusive = set(state.exclusive_keys)
    for release in releases:
        owner = _claim_owner(intent, release)
        if release.kind == "RESOURCE":
            banks.setdefault(owner, {})
            banks[owner][release.key] = apply_u64(banks[owner].get(release.key, 0) + release.amount)
        elif release.kind == "EXCLUSIVE_KEY":
            exclusive.discard(release.key)
        else:
            key = (release.kind, owner, release.key)
            usages[key] = max(0, usages.get(key, 0) - release.amount)
    for claim in claims:
        owner = _claim_owner(intent, claim)
        if claim.kind == "RESOURCE":
            banks.setdefault(owner, {})
            banks[owner][claim.key] = banks[owner].get(claim.key, 0) - claim.amount
        elif claim.kind == "EXCLUSIVE_KEY":
            exclusive.add(claim.key)
        else:
            key = (claim.kind, owner, claim.key)
            usages[key] = usages.get(key, 0) + claim.amount
    return replace(state, resource_banks=banks, usages=usages, exclusive_keys=frozenset(exclusive))
