"""Deterministic authoritative input buffering."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .errors import PCAMError, PCAMFault, ResultCode
from .model import TickInput

OverflowPolicy = Literal["DROP_OLDEST", "DROP_NEWEST", "FAULT"]
ConsumePolicy = Literal["ON_ACCEPT", "ON_ATTEMPT", "NEVER"]


@dataclass(frozen=True)
class BufferEntry:
    buffer_entry_id: str
    input_id: str
    command_id: str
    payload: dict[str, object]
    captured_tick: int
    remaining_eligibility_ticks: int
    priority: int
    sequence: int

    @classmethod
    def capture(cls, tick_input: TickInput, lifetime: int, priority: int = 0) -> "BufferEntry":
        if lifetime <= 0:
            raise PCAMError(
                ResultCode.RUNTIME_FAULT,
                PCAMFault.STATE_INVARIANT_FAILURE,
                "buffer lifetime must be positive",
            )
        return cls(
            buffer_entry_id=f"buffer:{tick_input.input_id}",
            input_id=tick_input.input_id,
            command_id=tick_input.command_id,
            payload=dict(tick_input.payload),
            captured_tick=tick_input.assigned_tick,
            remaining_eligibility_ticks=lifetime,
            priority=priority,
            sequence=tick_input.sequence,
        )


def capture_entry(
    entries: tuple[BufferEntry, ...],
    entry: BufferEntry,
    capacity: int,
    overflow_policy: OverflowPolicy,
) -> tuple[BufferEntry, ...]:
    if capacity < 0:
        raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "negative buffer capacity")
    if any(item.input_id == entry.input_id for item in entries):
        return canonical_entries(entries)
    if len(entries) < capacity:
        return canonical_entries((*entries, entry))
    if overflow_policy == "DROP_NEWEST" or capacity == 0:
        return canonical_entries(entries)
    if overflow_policy == "FAULT":
        raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "input buffer capacity exceeded")
    oldest = min(entries, key=lambda item: (item.captured_tick, item.sequence, item.buffer_entry_id.encode("utf-8")))
    return canonical_entries((*tuple(item for item in entries if item != oldest), entry))


def select_entry(entries: tuple[BufferEntry, ...], command_id: str) -> BufferEntry | None:
    matching = [item for item in entries if item.command_id == command_id]
    if not matching:
        return None
    return min(
        matching,
        key=lambda item: (-item.priority, item.captured_tick, item.sequence, item.input_id.encode("utf-8")),
    )


def apply_consumption(
    entries: tuple[BufferEntry, ...],
    entry: BufferEntry | None,
    policy: ConsumePolicy,
    accepted: bool,
    attempted: bool,
) -> tuple[BufferEntry, ...]:
    if entry is None or policy == "NEVER":
        return entries
    consume = policy == "ON_ACCEPT" and accepted or policy == "ON_ATTEMPT" and attempted
    if not consume:
        return entries
    return tuple(item for item in entries if item.buffer_entry_id != entry.buffer_entry_id)


def end_tick(entries: tuple[BufferEntry, ...], expiry_frozen: bool = False) -> tuple[BufferEntry, ...]:
    if expiry_frozen:
        return canonical_entries(entries)
    updated = tuple(
        replace(item, remaining_eligibility_ticks=item.remaining_eligibility_ticks - 1)
        for item in entries
        if item.remaining_eligibility_ticks > 1
    )
    return canonical_entries(updated)


def canonical_entries(entries: tuple[BufferEntry, ...]) -> tuple[BufferEntry, ...]:
    return tuple(
        sorted(
            entries,
            key=lambda item: (
                item.captured_tick,
                item.sequence,
                item.command_id.encode("utf-8"),
                item.input_id.encode("utf-8"),
            ),
        )
    )
