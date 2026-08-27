"""Bounded snapshot history, correction replay, and stable presentation reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from .model import HostSnapshot, TickInput
from .runtime import TickExecutor
from .state import SimulationState


class RollbackManager:
    def __init__(self, executor: TickExecutor):
        self.executor = executor

    def correct_and_resimulate(
        self,
        baseline_snapshot: dict[str, object],
        input_history: dict[int, tuple[TickInput, ...]],
        host_history: dict[int, HostSnapshot],
        corrected_tick: int,
        corrected_inputs: tuple[TickInput, ...],
        until_tick: int,
    ) -> tuple[SimulationState, list[dict[str, object]]]:
        state = self.executor.restore(baseline_snapshot)
        traces: list[dict[str, object]] = []
        history = dict(input_history)
        history[corrected_tick] = corrected_inputs
        while state.tick < until_tick:
            tick_inputs = history.get(state.tick, ())
            host = host_history.get(state.tick, HostSnapshot())
            state, trace = self.executor.tick(state, tick_inputs, host)
            traces.append(trace)
        return state, traces


@dataclass(frozen=True)
class RollbackFrame:
    tick: int
    snapshot: dict[str, object]
    inputs: tuple[TickInput, ...]
    host: HostSnapshot
    presentation_effect_ids: tuple[str, ...]


@dataclass(frozen=True)
class RollbackCorrection:
    state: SimulationState
    traces: tuple[dict[str, object], ...]
    rewind_ticks: int
    presentation_emit: tuple[str, ...]
    presentation_invalidated: tuple[str, ...]
    presentation_suppressed: tuple[str, ...]


class RetainedRollbackHistory:
    """Snapshot-every-tick rollback profile with a finite correction window."""

    def __init__(self, executor: TickExecutor, retained_history_ticks: int):
        if retained_history_ticks <= 0:
            raise ValueError("retained_history_ticks must be positive")
        self.executor = executor
        self.retained_history_ticks = retained_history_ticks
        self.frames: dict[int, RollbackFrame] = {}
        self.head_state: SimulationState | None = None
        self.presented_effect_ids: set[str] = set()

    def advance(
        self,
        state: SimulationState,
        inputs: tuple[TickInput, ...] = (),
        host: HostSnapshot | None = None,
    ) -> tuple[SimulationState, dict[str, object], tuple[str, ...]]:
        if self.head_state is not None and state.to_snapshot() != self.head_state.to_snapshot():
            raise ValueError("advance state does not match rollback head")
        actual_host = host or HostSnapshot()
        canonical_inputs = _canonical_inputs(state.tick, inputs)
        snapshot = self.executor.save(state)
        next_state, trace = self.executor.tick(state, canonical_inputs, actual_host)
        presentation_ids = _presentation_effect_ids(trace)
        self.frames[state.tick] = RollbackFrame(
            tick=state.tick,
            snapshot=snapshot,
            inputs=canonical_inputs,
            host=actual_host,
            presentation_effect_ids=presentation_ids,
        )
        self.presented_effect_ids.update(presentation_ids)
        self.head_state = next_state
        self._prune(next_state.tick)
        return next_state, trace, presentation_ids

    def correct_and_resimulate(
        self,
        corrected_tick: int,
        corrected_inputs: tuple[TickInput, ...],
        corrected_host: HostSnapshot | None = None,
    ) -> RollbackCorrection:
        if self.head_state is None:
            raise ValueError("rollback history is empty")
        corrected_inputs = _canonical_inputs(corrected_tick, corrected_inputs)
        frame = self.frames.get(corrected_tick)
        if frame is None:
            raise ValueError("corrected tick is outside retained history")
        until_tick = self.head_state.tick
        required = tuple(range(corrected_tick, until_tick))
        if any(tick not in self.frames for tick in required):
            raise ValueError("rollback history is not contiguous")
        old_frames = {tick: self.frames[tick] for tick in required}
        old_presentation = {
            identifier
            for old_frame in old_frames.values()
            for identifier in old_frame.presentation_effect_ids
        }
        base_presented = self.presented_effect_ids - old_presentation
        state = self.executor.restore(frame.snapshot)
        traces: list[dict[str, object]] = []
        replayed_presentation: set[str] = set()
        replacement_frames: dict[int, RollbackFrame] = {}
        for tick in required:
            old = old_frames[tick]
            inputs = corrected_inputs if tick == corrected_tick else old.inputs
            host = corrected_host if tick == corrected_tick and corrected_host is not None else old.host
            snapshot = self.executor.save(state)
            state, trace = self.executor.tick(state, inputs, host)
            presentation_ids = _presentation_effect_ids(trace)
            replayed_presentation.update(presentation_ids)
            replacement_frames[tick] = RollbackFrame(tick, snapshot, inputs, host, presentation_ids)
            traces.append(trace)
        invalidated = old_presentation - replayed_presentation
        suppressed = old_presentation.intersection(replayed_presentation)
        emitted = replayed_presentation - old_presentation - base_presented
        self.frames.update(replacement_frames)
        self.presented_effect_ids = base_presented.union(replayed_presentation)
        self.head_state = state
        return RollbackCorrection(
            state=state,
            traces=tuple(traces),
            rewind_ticks=until_tick - corrected_tick,
            presentation_emit=_canonical_ids(emitted),
            presentation_invalidated=_canonical_ids(invalidated),
            presentation_suppressed=_canonical_ids(suppressed),
        )

    def _prune(self, head_tick: int) -> None:
        earliest = max(0, head_tick - self.retained_history_ticks)
        for tick in tuple(self.frames):
            if tick < earliest:
                del self.frames[tick]


def _presentation_effect_ids(trace: dict[str, object]) -> tuple[str, ...]:
    raw = trace.get("typed_effects_emitted", ())
    if not isinstance(raw, list):
        return ()
    identifiers = {
        str(effect["effect_id"])
        for effect in raw
        if isinstance(effect, dict) and effect.get("authoritative") is False and "effect_id" in effect
    }
    return _canonical_ids(identifiers)


def _canonical_ids(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda item: item.encode("utf-8")))


def _canonical_inputs(tick: int, inputs: tuple[TickInput, ...]) -> tuple[TickInput, ...]:
    if any(item.assigned_tick != tick for item in inputs):
        raise ValueError("corrected input assigned_tick does not match corrected tick")
    identifiers = [item.input_id for item in inputs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("rollback input history contains duplicate input_id")
    return tuple(
        sorted(
            inputs,
            key=lambda item: (
                item.source_entity_id,
                item.sequence,
                item.command_id.encode("utf-8"),
                item.input_id.encode("utf-8"),
            ),
        )
    )
