# Extension Gate

State: PARTIAL

## Evidence present

- Extension namespaces require at least two organization-qualified segments and bounded canonical names.
- Every declaration is classified `REQUIRED` or `OPTIONAL`.
- Unknown required extensions fail with `UNKNOWN_REQUIRED_EXTENSION`.
- Optional extensions may be omitted only when they are non-authoritative and explicitly declare that omission preserves authoritative semantics.
- Authoritative declarations bind schema, PCAM-CJ1 encoding, validation, runtime semantics, ordering, fault behavior, snapshot schema, rollback behavior, and at least one deterministic vector digest.
- Registered payloads are checked with Draft 2020-12 JSON Schema and bounded canonical encoding.
- The extension registry is declarative and stores no executable callback from portable definition data.
- Registry schema and implementation hashes are included in the definition-set identity in canonical namespace order.
- Authoritative simulation and per-action extension state is bounded on tick and restore.

## Remaining before closure

- Implement at least one authoritative extension's runtime semantics, snapshot state, rollback behavior, and shared determinism vectors end to end.
- Add portable host-module loading policy and prove that native module identity matches its declared implementation hash.
- Expand hostile extension payload and recursive-depth vectors.

Definition hashing authenticates neither extension modules nor network messages.
