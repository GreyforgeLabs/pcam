# Evidence and Gates

PCAM v3 separates implementation progress from conformance claims. Passing tests do not silently promote a draft into a standard.

## Current gate state

| Gate | State |
|---|---|
| Specification | Closed for `3.0.0-draft.1` |
| Schemas | Closed for `3.0.0-draft.1` |
| Tooling | Closed for Section 42 |
| Extension profile | Closed for `3.0.0-draft.1` |
| Licensing | Satisfied for draft distribution |
| Migration | Satisfied |
| Rollback | Closed for the final archived draft candidate |
| Comparative experiment | Closed for the current bounded draft experiment |
| Documentation claims | Closed for the current documentation set |
| Reference runtime | Administratively closed; remaining class work not pursued |
| Independent implementation | Closed for the final draft candidate |
| Networking profile | Closed |
| Cross-platform | Closed |

## Zero conformance claims

The machine-readable ledger currently marks every Section 37 class unclaimed:

- `PCAM-DEF-3` is unclaimed.
- `PCAM-RUN-3` is unclaimed.
- `PCAM-DET-3` is unclaimed.
- `PCAM-RB-3` is unclaimed.
- `PCAM-24-3` is unclaimed.

The claims audit rejects prose that outruns this ledger.

## Cross-platform boundary

Actual Linux x86-64 and Linux ARM64 execution pin the same shared Python and Rust suite digest. Cross-compilation alone is not evidence.

The final manifests are committed archival evidence. Public CI reruns both architectures and verifies their pinned manifests without replacing them.

## Inspect the proof

- [Release requirements](https://github.com/GreyforgeLabs/pcam/blob/main/release/requirements-matrix.md)
- [Conformance ledger](https://github.com/GreyforgeLabs/pcam/blob/main/release/conformance-claims.json)
- [Cross-platform gate](https://github.com/GreyforgeLabs/pcam/blob/main/release/cross-platform-gate.md)
- [Reference-runtime gate](https://github.com/GreyforgeLabs/pcam/blob/main/release/reference-runtime-gate.md)
- [Independent-implementation gate](https://github.com/GreyforgeLabs/pcam/blob/main/release/independent-implementation-gate.md)
- [Security and robustness map](https://github.com/GreyforgeLabs/pcam/blob/main/release/security-robustness.json)
