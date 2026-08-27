# Extension Gate

State: CLOSED for `3.0.0-draft.1`

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
- The verified `TICK_START_COUNTER` pilot executes checked U64 state updates in declared order, stores state in canonical snapshots, restores identically, and matches direct execution after retained-history rollback.
- The pilot's exact inert module contract is SHA-256 verified before execution; runtime hooks are compiled allowlist values, and portable declarations cannot select paths, imports, network locations, or callbacks.
- `../tests/vectors/extension-tick-counter.json` is the shared deterministic input/output corpus for the pilot.
- The independent Rust lane verifies the same module bytes and vector hash, reproduces the counter sequence and restore continuation, and fails closed on source mismatch and U64 overflow.
- Hostile vectors cover unknown required declarations, unsafe optional declarations, contract and payload mismatch, source tampering, encoded-size overflow, and iterative depth rejection before canonical recursion.

## Gate conclusion

The bounded reference extension requirement is complete for the current candidate. This closure proves one allowlisted authoritative extension end to end; it does not imply that arbitrary native modules are portable, safe, or supported.

Definition hashing authenticates neither extension modules nor network messages.
