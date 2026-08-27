"""Canonical `pcam.pcg32.v1` deterministic random stream."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .numeric import U64_MAX, apply_u64

PCG32_MULTIPLIER = 6364136223846793005


@dataclass(frozen=True)
class PCG32Stream:
    state: int
    stream_selector: int
    draw_count: int = 0
    algorithm_id: str = "pcam.pcg32.v1"

    @classmethod
    def seeded(cls, seed: int, stream_selector: int) -> "PCG32Stream":
        seed = apply_u64(seed)
        stream_selector = apply_u64(stream_selector)
        stream = cls(state=0, stream_selector=stream_selector)
        stream, _ = stream.draw_u32(count_draw=False)
        stream = replace(stream, state=(stream.state + seed) & U64_MAX)
        stream, _ = stream.draw_u32(count_draw=False)
        return stream

    @property
    def increment(self) -> int:
        return ((self.stream_selector << 1) | 1) & U64_MAX

    def draw_u32(self, count_draw: bool = True) -> tuple["PCG32Stream", int]:
        old_state = apply_u64(self.state)
        new_state = (old_state * PCG32_MULTIPLIER + self.increment) & U64_MAX
        xor_shifted = (((old_state >> 18) ^ old_state) >> 27) & 0xFFFFFFFF
        rotation = (old_state >> 59) & 31
        value = ((xor_shifted >> rotation) | (xor_shifted << ((-rotation) & 31))) & 0xFFFFFFFF
        return replace(self, state=new_state, draw_count=self.draw_count + int(count_draw)), value

    def to_snapshot(self) -> dict[str, int | str]:
        return {
            "algorithm_id": self.algorithm_id,
            "draw_count": self.draw_count,
            "state": self.state,
            "stream_selector": self.stream_selector,
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, object]) -> "PCG32Stream":
        if snapshot.get("algorithm_id") != "pcam.pcg32.v1":
            raise ValueError("RNG algorithm mismatch")
        return cls(
            state=apply_u64(int(snapshot["state"])),
            stream_selector=apply_u64(int(snapshot["stream_selector"])),
            draw_count=apply_u64(int(snapshot["draw_count"])),
        )
