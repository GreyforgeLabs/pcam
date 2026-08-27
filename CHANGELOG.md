# Changelog

## Unreleased

- Began the PCAM v3 conformance-first repository.
- Imported the `3.0.0-draft.1` master specification.
- Established draft status, release evidence, schema, reference runtime, independent implementation, vector, and experiment lanes.
- Corrected the source draft's stability reference from §27 to the actual release gates in §45.
- Added initial Draft 2020-12 schemas, positive and negative vectors, semantic validation, stable JSON command envelopes, PCAM-CJ1 hashing, PCAM-24 compilation, and a tested Python runtime vertical slice.
- Added checked integer policies, Euclidean division, exact ratio scaling, a bounded pure expression evaluator, the canonical PCG32 stream with restore vectors, logical-map canonicalization, and Unicode key-collision rejection.
- Added deterministic input-buffer and freeze-token primitives, including TTL, overflow, consumption, activation, expiry, provisional stacking, and explicit open-issue tracking for underspecified stack semantics.
- Integrated authoritative buffers and freeze tokens into the tick pipeline, including capture, transition consumption, expiry, progression HOLD, serialized deferred ACCRUE quanta, and snapshot round trips.
- Added permutation-invariant atomic intent arbitration, deterministic instance-ID allocation, all core effect reducer primitives, exclusive-effect rejection traces, and open-issue tracking for undefined cross-intent atomic groups.
