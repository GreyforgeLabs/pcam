# Independent Implementation Gate

State: OPEN

Required: an implementation built from the specification and shared black-box vectors without sharing Python runtime execution code.

## Evidence present

- `independent/rust/` is a separately implemented Rust crate with no dependency on the Python runtime.
- `tests/vectors/pcam-cj1.json` supplies shared black-box canonical-byte and SHA-256 expectations.
- The Rust implementation passes all three PCAM-CJ1 cases, a real action-definition hash, and floating-point rejection.
- `tests/vectors/numeric-rng.json` supplies shared overflow, Euclidean division, checked ratio, PCG32 output, snapshot, and continuation expectations.
- Python and Rust independently agree on I64/U64 overflow policy, negative-floor division, checked intermediate overflow, five PCG32 draws, serialized stream state, restore, and the next draw.
- `tests/vectors/expressions.json` exercises every core expression operator plus unresolved-reference, arity, float, division, overflow, depth, and node-budget failures in both languages.
- `tests/vectors/action-runtime.json` drives independent Python and Rust runtime paths through rational progression, PRE_ADVANCE, AFTER_QUANTUM, POST_ADVANCE, priority selection, explicit seek, terminal entry, predicate dependencies and edge serials, canonical input buffering and consumption, HOLD/ACCRUE and domain freezes, invalid-definition rejection, and deterministic runtime-limit and buffer-capacity faults.
- `tests/vectors/extension-tick-counter.json` drives the source-hash-verified authoritative extension pilot through the same counter outputs, restore continuation, tamper rejection, and checked overflow in Python and Rust.
- Every successful shared runtime case pins the same PCAM-CJ1 action-state projection digest in both languages, restores that state, advances one more tick, and pins the same continuation digest.
- Validation command: `cargo test --manifest-path independent/rust/Cargo.toml`.

## Remaining before closure

- Implement the authoritative action runtime independently, including tick stages, arbitration, interactions, effects, events, snapshots, restore, and rollback.
- Run the shared mandatory and generated conformance corpus against both implementations.
- Produce matching Linux x86-64 and Linux ARM64 digest manifests.
- Audit that no Python runtime execution code or behavior-specific generated source is shared.

The current evidence covers independent PCAM-CJ1, core numeric, PCG32, pure expressions, the bounded authoritative extension pilot, and a bounded local progression, transition, predicate, input-buffer, freeze, and action-state continuation runtime. It does not yet cover independent arbitration, general effects, interactions, events, parent-child behavior, complete simulation snapshots, or the full tick pipeline, so the independent action-runtime gate remains open.
