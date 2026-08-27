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
- `tests/vectors/action-runtime.json` drives independent Python and Rust runtime paths through rational progression, PRE_ADVANCE, AFTER_QUANTUM, POST_ADVANCE, priority selection, explicit seek, terminal entry, predicate dependencies and edge serials, canonical input buffering and consumption, HOLD/ACCRUE and domain freezes, invalid-definition rejection, deterministic runtime-limit and buffer-capacity faults, and canonical node/transition assignment and effect order with immutable matched-input context.
- `tests/vectors/extension-tick-counter.json` drives the source-hash-verified authoritative extension pilot through the same counter outputs, restore continuation, tamper rejection, and checked overflow in Python and Rust.
- `tests/vectors/effects.json` drives all eight non-custom Core reducers, canonical group and source ordering, exclusive-effect rejection tracing, mixed-reducer rejection, unregistered-custom rejection, and checked SUM overflow in Python and Rust.
- The unchanged `tests/vectors/typed-strike.json` now drives independent Python and Rust simulation runtimes through direct start, semantic predicate activation, canonical contact ordering, duplicate-contact ledger suppression, interaction effect materialization, SUM reduction, authoritative resource commit, complete-state PCAM-CJ1 digests for three ticks, snapshot round-trip, continuation, and corrected-input rollback equivalence. Rust independently derives the pinned definition and definition-set hashes.
- Every successful shared runtime case pins the same PCAM-CJ1 action-state projection digest in both languages, restores that state, advances one more tick, and pins the same continuation digest.
- Validation command: `cargo test --manifest-path independent/rust/Cargo.toml`.

## Remaining before closure

- Generalize the bounded independent simulation path to the complete tick stages, arbitration, the full interaction language, events, parent-child behavior, fault policies, snapshots, restore, and retained rollback.
- Run the shared mandatory and generated conformance corpus against both implementations.
- Produce matching Linux x86-64 and Linux ARM64 digest manifests.
- Audit that no Python runtime execution code or behavior-specific generated source is shared.

The current evidence covers independent PCAM-CJ1, core numeric, PCG32, pure expressions, every non-custom Core effect reducer, the bounded authoritative extension pilot, a bounded local progression and transition-operation runtime, and one complete-state simulation vector integrating interaction resolution, ledger suppression, authoritative commit, snapshot restore, continuation, and rollback correction. It does not yet cover independent arbitration, the general interaction language, events, parent-child behavior, fault policies, retained rollback, or the complete tick pipeline breadth, so the independent action-runtime gate remains open.
