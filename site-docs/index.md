# PCAM v3

PCAM v3 is a deterministic semantic action-model standard for interactive simulation. It makes the complete action-machine state authoritative, uses logical ticks for ordering, and keeps presentation outside the authority boundary.

PCAM-24 remains available as an optional authoring and visualization profile. It is not the authoritative simulation state.

!!! warning "Normative Candidate"

    The current version is `3.0.0-draft.1`. It is not Stable or Normative, and it claims no PCAM conformance class. The reference-runtime, independent-implementation, networking-profile, and cross-platform gates remain open.

## Why complete state matters

A projected phase can hide differences that change future behavior. Two actions can appear to occupy the same phase while carrying different cycle counters, buffers, freezes, contacts, child relationships, ledgers, random-stream state, or rollback history.

PCAM v3 treats those differences as authoritative. The model defines canonical ordering, bounded execution, snapshots, state digests, typed interactions, explicit effects, faults, networking profiles, and retained rollback requirements around that complete state.

## Public artifacts

- [Master specification](https://github.com/GreyforgeLabs/pcam/blob/main/spec/PCAM-v3.md)
- [Current status](https://github.com/GreyforgeLabs/pcam/blob/main/STATUS.md)
- [Requirement matrix](https://github.com/GreyforgeLabs/pcam/blob/main/release/requirements-matrix.md)
- [Machine-readable conformance ledger](https://github.com/GreyforgeLabs/pcam/blob/main/release/conformance-claims.json)
- [Canonical examples](https://github.com/GreyforgeLabs/pcam/tree/main/examples)
- [Shared test vectors](https://github.com/GreyforgeLabs/pcam/tree/main/tests)

Autonomy, Engineered.

