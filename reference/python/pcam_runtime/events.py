"""Canonical next-tick authoritative event scheduling and delivery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .errors import PCAMError, PCAMFault, ResultCode

DeliveryMode = Literal["TARGET_ACTION", "TARGET_ENTITY", "BROADCAST", "PARENT", "CHILD"]


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    source_id: int
    target_id: int
    origin_tick: int
    delivery_tick: int
    payload: dict[str, object]
    delivery_mode: DeliveryMode

    @classmethod
    def next_tick(
        cls,
        event_id: str,
        event_type: str,
        source_id: int,
        target_id: int,
        origin_tick: int,
        payload: dict[str, object],
        delivery_mode: DeliveryMode,
    ) -> "EventEnvelope":
        return cls(
            event_id=event_id,
            event_type=event_type,
            source_id=source_id,
            target_id=target_id,
            origin_tick=origin_tick,
            delivery_tick=origin_tick + 1,
            payload=payload,
            delivery_mode=delivery_mode,
        )


def canonical_events(events: tuple[EventEnvelope, ...]) -> tuple[EventEnvelope, ...]:
    identifiers: set[str] = set()
    for event in events:
        if event.event_id in identifiers:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, event.event_id)
        identifiers.add(event.event_id)
    return tuple(
        sorted(
            events,
            key=lambda item: (
                item.delivery_tick,
                item.target_id,
                item.delivery_mode.encode("utf-8"),
                item.source_id,
                item.event_type.encode("utf-8"),
                item.event_id.encode("utf-8"),
            ),
        )
    )


def deliver_due(
    events: tuple[EventEnvelope, ...],
    tick: int,
    frozen_target_action_ids: frozenset[int] = frozenset(),
) -> tuple[tuple[EventEnvelope, ...], tuple[EventEnvelope, ...]]:
    delivered: list[EventEnvelope] = []
    pending: list[EventEnvelope] = []
    for event in canonical_events(events):
        if event.delivery_tick < tick:
            raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, event.event_id)
        if event.delivery_tick > tick:
            pending.append(event)
            continue
        if event.delivery_mode in {"TARGET_ACTION", "PARENT", "CHILD"} and event.target_id in frozen_target_action_ids:
            pending.append(replace(event, delivery_tick=tick + 1))
            continue
        delivered.append(event)
    return canonical_events(tuple(delivered)), canonical_events(tuple(pending))


def event_snapshot(event: EventEnvelope) -> dict[str, object]:
    return {
        "delivery_mode": event.delivery_mode,
        "delivery_tick": event.delivery_tick,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "origin_tick": event.origin_tick,
        "payload": event.payload,
        "source_id": event.source_id,
        "target_id": event.target_id,
    }


def event_from_snapshot(snapshot: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(snapshot["event_id"]),
        event_type=str(snapshot["event_type"]),
        source_id=int(snapshot["source_id"]),
        target_id=int(snapshot["target_id"]),
        origin_tick=int(snapshot["origin_tick"]),
        delivery_tick=int(snapshot["delivery_tick"]),
        payload=dict(snapshot["payload"]),
        delivery_mode=str(snapshot["delivery_mode"]),  # type: ignore[arg-type]
    )
