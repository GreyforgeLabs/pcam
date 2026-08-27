"""Small rollback-correction helper for deterministic replay tests."""

from __future__ import annotations

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
