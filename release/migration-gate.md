# Legacy Migration Gate

State: SATISFIED

## Supported boundary

`pcam migrate-v2` accepts only documents that explicitly identify PCAM v1 or v2. The command name is retained for the §42 interface, but both legacy versions use the same warning-first importer.

The bounded legacy surface accepts:

- a canonical identifier
- 24-cell `phases` or `windows` ranges
- `TERMINATE`, `LOOP`, or `CLAMP` lifecycle
- exact integer `scale` and `units_per_tick`

The output is a schema-valid PCAM-24 v3 draft with `manual_review_required=true` and `wire_compatible=false`.

## Evidence

- v1 and v2 fixtures migrate deterministically.
- Overlapping windows emit `OVERLAPPING_OR_CONTRADICTORY_WINDOWS`.
- Missing stall, hit-policy, cycle, skip, nesting, and deterministic-limit semantics emit stable warnings.
- Universal precedence and phase-only networking declarations emit explicit review warnings.
- Floating or invalid timing is never copied into v3 authoritative data; it is replaced by a conservative integer draft rate and flagged.
- Every result carries a deterministic non-authoritative source evidence hash.
- Manual review is always required.
- Missing, v3, malformed, and unknown version declarations fail with `UNSUPPORTED_LEGACY_VERSION`.
- Ordinary v3 validation rejects legacy documents rather than silently interpreting them.

Migration does not provide wire compatibility or active-instance state migration.
