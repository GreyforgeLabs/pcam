# Networking Profile Gate

State: CLOSED

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
- `tests/vectors/network-services.json` drives Python and independent Rust lockstep coordinators through WAIT and PREDICT readiness, canonical peer-input merge, definition and host mismatch rejection, periodic digest match, declared desynchronization abort, and post-abort fail-closed behavior.
- The same shared vector drives server-authoritative correction planners through bounded restore-and-resimulate and complete-state replace-and-discard paths. Both reach the exact direct server state, while future, out-of-window, and incomplete replacement corrections are rejected.

## Closure

The matching Linux x86-64 and Linux ARM64 digest manifests close the final cross-architecture execution requirement for this bounded networking profile gate.

Phase-only reconciliation remains prohibited for deterministic correction.
