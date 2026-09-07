# Claims Gate

State: CLOSED FOR THE CURRENT DOCUMENTATION SET

The repository must not claim perfect determinism, latency elimination, rollback elimination, universally minimal network state, superior performance, production readiness, or industry novelty without exact reproducible evidence.

Current approved claims:

- PCAM v3 is a draft deterministic semantic action-model specification.
- The project is retired and archival-only at `v3.0.0-draft.1`.
- Complete state, logical ticks, profile separation, and presentation non-authority are design requirements, not completed conformance claims.

Machine-readable conformance authority: `conformance-claims.json`. It currently marks `PCAM-DEF-3`, `PCAM-RUN-3`, `PCAM-DET-3`, `PCAM-RB-3`, and `PCAM-24-3` as unclaimed. Prose must not contradict that manifest.

Evidence: `claims-audit.json`, `claims-audit.md`, and `../reference/python/tests/test_claims_audit.py`. The audit scans all Markdown, allowlists only exact normative or disclaimer contexts, validates the conformance manifest, and fails if any class becomes claimed.

This gate reopens on any documentation or conformance-claim change. Closure means only that current documentation avoids unsupported claims; it does not approve any prohibited claim or conformance class.
