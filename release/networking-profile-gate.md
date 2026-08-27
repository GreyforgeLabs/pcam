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
- A bounded snapshot-every-tick rollback history retains canonical input and host evidence, replaces late or mispredicted input, resimulates atomically, rejects exhausted history, and reconciles presentation effects by stable identifier.
- The §45.6 suite covers action starts, hit-stop, children, RNG draws, ledgers, and presentation deduplication during rewind.

## Remaining before closure

- Implement and test lockstep input readiness, digest exchange, and desynchronization behavior.
- Implement server-authoritative correction and prediction discard/resimulation behavior.
- Add profile-specific end-to-end vectors and cross-architecture digest manifests.

Phase-only reconciliation remains prohibited for deterministic correction.
