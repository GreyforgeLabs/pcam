# Rollback Gate

State: CLOSED FOR THE CURRENT NORMATIVE CANDIDATE

## Runtime evidence

`RetainedRollbackHistory` records a complete pre-tick snapshot plus canonical input history and deterministic host history for every retained tick. It:

- enforces a positive finite history window
- rejects corrections outside that window
- restores the snapshot immediately preceding the earliest changed tick
- replaces corrected inputs and optional corrected host evidence
- resimulates every affected tick to the prior head
- stages replacement history atomically, so a replay fault does not partially rewrite the retained timeline
- recomputes state digests through the ordinary tick executor
- reconciles non-authoritative presentation effects by stable effect identifier

The reference transition effect `RNG_DRAW` performs one explicit `pcam.pcg32.v1` draw, snapshots the updated stream and draw count, and emits the draw value in deterministic reduction trace evidence.

## Required cases

Machine-readable coverage is in `../tests/rollback/coverage.json`. Direct tests in `../reference/python/tests/test_rollback_gate.py` demonstrate:

- late authoritative input replacing a prediction
- wrong predicted action replaced during a five-tick rewind
- action start and deterministic instance identity during rewind
- active hit-stop freeze state, expiry, and continuation
- child start, parent-child identity, slot, and relationship freeze
- RNG draw value, draw count, and future stream state
- interaction-ledger restoration
- presentation-effect suppression on identical replay and invalidation when a predicted effect disappears
- correction-window exhaustion and fault-atomic history replacement

Each corrected result is compared with direct execution from the same pre-correction snapshot. This gate does not close the wider networking gate: lockstep exchange, server-authoritative prediction, and stable presentation transport remain separate work.
