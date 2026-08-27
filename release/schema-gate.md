# Schema Gate

State: CLOSED FOR `3.0.0-draft.1`

Required: schemas for every normative definition type, positive and negative vectors, canonical-hash vectors, version checks, and extension checks.

Evidence: `schema-audit.json`, `schema-audit.md`, `../tests/invalid/schema-mutations.json`, and the schema, extension, canonicalization, example, and audit tests.

Eight Draft 2020-12 schema documents cover all six normative portable definition categories plus snapshots and conformance manifests. Nine positive documents, 23 mutation vectors, dedicated invalid fixtures, canonical-hash vectors, version checks, and extension checks pass.

An end-to-end authoritative extension remains required by the separate extension and runtime gates, not by structural declaration validation. This schema gate reopens if a normative definition type, canonical field, schema, or referenced semantic invariant changes without aligned vectors and audit evidence.
