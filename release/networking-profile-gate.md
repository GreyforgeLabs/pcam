# Networking Profile Gate

State: OPEN

## Evidence present

- `schemas/network-profile.schema.json` declares local deterministic, lockstep, rollback, and server-authoritative prediction topologies.
- Networked declarations require explicit latency mechanisms and finite compensation limits.
- Lockstep declarations bind input availability, digest cadence, and desynchronization policy.
- Rollback declarations bind deterministic prediction, snapshot cadence, retained history, and stable-effect reconciliation policy.
- Server-authoritative prediction declarations bind correction policy.
- Runtime-profile hashes include every required §31 limit, RNG profile, extension state, and networking declaration in canonical identifier order.
- Schema and model tests reject incomplete and duplicate networking declarations.

## Remaining before closure

- Implement and test lockstep input readiness, digest exchange, and desynchronization behavior.
- Extend rollback from the current correction/resimulation helper to a bounded retained snapshot and input-history service.
- Implement server-authoritative correction and prediction discard/resimulation behavior.
- Add stable presentation-effect reconciliation evidence.
- Add profile-specific end-to-end vectors and cross-architecture digest manifests.

Phase-only reconciliation remains prohibited for deterministic correction.
