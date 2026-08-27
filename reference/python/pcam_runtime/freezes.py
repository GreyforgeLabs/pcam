"""Explicit freeze-token activation, stacking, querying, and expiry."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .errors import PCAMError, PCAMFault, ResultCode

FreezeDomain = Literal[
    "PROGRESSION",
    "PRE_ADVANCE_TRANSITIONS",
    "POST_ADVANCE_TRANSITIONS",
    "INPUT_CAPTURE",
    "BUFFER_EXPIRY",
    "EVENT_DELIVERY",
    "INTERACTION_EMISSION",
    "INTERACTION_RECEPTION",
    "RESOURCE_REGENERATION",
    "RNG_CONSUMPTION",
]
AccrualPolicy = Literal["HOLD", "ACCRUE"]
StackPolicy = Literal["INDEPENDENT", "MAX_DURATION", "SUM_DURATION", "REPLACE", "REJECT_NEW"]


@dataclass(frozen=True)
class FreezeToken:
    token_id: int
    source_id: int
    target_id: int
    activation_tick: int
    remaining_ticks: int
    domains: tuple[FreezeDomain, ...]
    accrual_policy: AccrualPolicy = "HOLD"
    stack_group: str = "default"
    stack_policy: StackPolicy = "INDEPENDENT"
    metadata: dict[str, object] | None = None

    @classmethod
    def created(
        cls,
        token_id: int,
        source_id: int,
        target_id: int,
        creation_tick: int,
        duration: int,
        domains: tuple[FreezeDomain, ...],
        accrual_policy: AccrualPolicy = "HOLD",
        stack_group: str = "default",
        stack_policy: StackPolicy = "INDEPENDENT",
        metadata: dict[str, object] | None = None,
    ) -> "FreezeToken":
        if duration <= 0:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "freeze duration must be positive")
        if not domains or len(domains) != len(set(domains)):
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "freeze domains must be nonempty and unique")
        return cls(
            token_id=token_id,
            source_id=source_id,
            target_id=target_id,
            activation_tick=creation_tick + 1,
            remaining_ticks=duration,
            domains=tuple(sorted(domains)),
            accrual_policy=accrual_policy,
            stack_group=stack_group,
            stack_policy=stack_policy,
            metadata=metadata,
        )

    @property
    def expiration_tick(self) -> int:
        return self.activation_tick + self.remaining_ticks


def add_token(tokens: tuple[FreezeToken, ...], token: FreezeToken) -> tuple[FreezeToken, ...]:
    group = tuple(
        item for item in tokens if item.target_id == token.target_id and item.stack_group == token.stack_group
    )
    if token.stack_policy == "REJECT_NEW" and group:
        return canonical_tokens(tokens)
    if token.stack_policy == "REPLACE":
        tokens = tuple(item for item in tokens if item not in group)
        return canonical_tokens((*tokens, token))
    if token.stack_policy in {"MAX_DURATION", "SUM_DURATION"} and group:
        _require_compatible_group(group, token)
        if token.stack_policy == "SUM_DURATION":
            current_tick = token.activation_tick - 1
            latest_expiration = max(_expiration_exclusive(item, current_tick) for item in group)
            token = replace(token, activation_tick=max(token.activation_tick, latest_expiration))
    return canonical_tokens((*tokens, token))


def active_tokens(
    tokens: tuple[FreezeToken, ...],
    tick: int,
    target_id: int,
    domain: FreezeDomain,
) -> tuple[FreezeToken, ...]:
    return tuple(
        item
        for item in canonical_tokens(tokens)
        if item.target_id == target_id
        and item.activation_tick <= tick
        and item.remaining_ticks > 0
        and domain in item.domains
    )


def is_frozen(tokens: tuple[FreezeToken, ...], tick: int, target_id: int, domain: FreezeDomain) -> bool:
    return bool(active_tokens(tokens, tick, target_id, domain))


def progression_accrual(tokens: tuple[FreezeToken, ...], tick: int, target_id: int) -> AccrualPolicy | None:
    active = active_tokens(tokens, tick, target_id, "PROGRESSION")
    if not active:
        return None
    return "HOLD" if any(item.accrual_policy == "HOLD" for item in active) else "ACCRUE"


def end_tick(tokens: tuple[FreezeToken, ...], tick: int) -> tuple[FreezeToken, ...]:
    updated = []
    for token in canonical_tokens(tokens):
        if token.activation_tick <= tick:
            remaining = token.remaining_ticks - 1
            if remaining > 0:
                updated.append(replace(token, remaining_ticks=remaining))
        else:
            updated.append(token)
    return canonical_tokens(tuple(updated))


def canonical_tokens(tokens: tuple[FreezeToken, ...]) -> tuple[FreezeToken, ...]:
    return tuple(sorted(tokens, key=lambda item: item.token_id))


def _require_compatible_group(group: tuple[FreezeToken, ...], token: FreezeToken) -> None:
    for existing in group:
        if (
            existing.domains != token.domains
            or existing.accrual_policy != token.accrual_policy
            or existing.stack_policy != token.stack_policy
        ):
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "MAX_DURATION and SUM_DURATION groups require identical domains, accrual, and stack policy",
            )


def _expiration_exclusive(token: FreezeToken, current_tick: int) -> int:
    if token.activation_tick > current_tick:
        return token.activation_tick + token.remaining_ticks
    return current_tick + token.remaining_ticks
