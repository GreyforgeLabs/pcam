# PCAM v3

PCAM v3 is a draft deterministic semantic action-model standard for interactive simulation.

The authoritative state is the complete action-machine state. Logical ticks provide ordering. PCAM-24 is an optional authoring and visualization profile. Presentation observes simulation state and never drives authoritative outcomes.

This repository is under active implementation. It does not claim Stable, Normative, production-ready, cross-platform, rollback, performance, or novelty status. See [STATUS.md](STATUS.md) and the evidence ledger under `release/`.

## Repository map

- `spec/` - the master specification and focused model documents
- `schemas/` - machine-readable definition and snapshot schemas
- `reference/python/` - readable reference implementation
- `independent/rust/` - independent implementation lane
- `profiles/pcam24/` - 24-cell authoring profile
- `tests/` - positive, negative, deterministic, rollback, generated, and cross-platform vectors
- `experiments/` - comparative methodology, baselines, and results
- `release/` - requirement traceability and release-gate evidence

## Current execution target

The first vertical slice is one strike action that exercises schema validation, canonicalization, PCAM-24 compilation, integer progression, predicates, buffering, a directed contact, an interaction ledger, canonical effects, save and restore, trace output, state digests, and rollback correction. It uses the same architecture intended for the complete implementation.

## Development

The project targets Python 3.12 for the reference runtime and Rust for the independent implementation.

```bash
python3 -m pytest reference/python/tests
cargo test --manifest-path independent/rust/Cargo.toml
```

The Rust lane currently covers only independent PCAM-CJ1 canonicalization and hashing. Additional commands become authoritative only when their implementation and machine-readable result contracts are covered by vectors.

## Authority

- Specification: `spec/PCAM-v3.md`
- Status and gates: `STATUS.md`
- Requirement map: `release/requirements-matrix.md`
- Claims ledger: `release/claims-gate.md`

Autonomy, Engineered.
