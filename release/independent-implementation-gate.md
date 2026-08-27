# Independent Implementation Gate

State: OPEN

Required: an implementation built from the specification and shared black-box vectors without sharing Python runtime execution code.

## Evidence present

- `independent/rust/` is a separately implemented Rust crate with no dependency on the Python runtime.
- `tests/vectors/pcam-cj1.json` supplies shared black-box canonical-byte and SHA-256 expectations.
- The Rust implementation passes all three PCAM-CJ1 cases, a real action-definition hash, and floating-point rejection.
- Validation command: `cargo test --manifest-path independent/rust/Cargo.toml`.

## Remaining before closure

- Implement the authoritative action runtime independently, including tick stages, arbitration, interactions, effects, events, snapshots, restore, and rollback.
- Run the shared mandatory and generated conformance corpus against both implementations.
- Produce matching Linux x86-64 and Linux ARM64 digest manifests.
- Audit that no Python runtime execution code or behavior-specific generated source is shared.

The current evidence closes only the independent PCAM-CJ1 serializer/hash slice. It does not satisfy the independent implementation release gate.
