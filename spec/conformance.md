# PCAM v3 Conformance

Status: Normative Candidate companion

Owner: PCAM specification

The master authority is `PCAM-v3.md` §37-45.

Conformance classes and release status are evidence claims. The executable vectors, independent implementation, cross-platform digest manifests, rollback artifacts, experiment reports, and claims ledger determine which claims are available. Documentation builds and narrow smoke tests do not establish runtime conformance.

See `../release/requirements-matrix.md` for the live proof map.

The authoritative machine-readable claim surface is `../release/conformance-claims.json`, validated by `../schemas/conformance-manifest.schema.json` and semantic repository checks. Every §37 class and required capability must appear. A class may be marked claimed only when each capability is `PASS` with existing repository-relative evidence and any prerequisite class is also claimed.

The current manifest claims no conformance class. Partial evidence remains visible without converting incomplete implementation work into a conformance claim.
