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
- Added a directed five-stage typed interaction resolver with canonical candidate order, parry, armor modification, independent outgoing attacks, simultaneous trade, deterministic redirection limits, materialization, and interaction-spec gap tracking.
- Added all six core hit-policy key strategies, explicit receipt timing, same-tick provisional receipt behavior, cooldown eligibility, cycle distinction, and predicate-reactivation vectors.
- Integrated typed semantic facts, interaction rules, ledger policies, canonical reducers, and effect registry commits into stages 7-10; canonicalized host contact snapshots so raw enumeration permutations produce identical state digests.
- Integrated resource and action-slot intents into pre/post arbitration, deterministic competing starts, source-slot provisional release, and atomic action replacement that preserves the source when any target claim fails.
- Added canonical next-tick event scheduling, delivery, duplicate rejection, snapshot round trips, and explicit tracking for the underspecified interaction between one-tick lifetime and delivery freezes.
- Integrated child-slot arbitration, parent-child identity, nesting bounds, relationship freezes, child-result events, parent termination policy, event-driven parent transitions, and parent-child save/restore continuation equivalence.
- Implemented all eleven reference CLI paths with bounded runtime-vector loading, pinned digest verification, canonical trace and snapshot output, restore round trips, migration warnings, and rollback resimulation equivalence.
- Added deterministic generated/property tests across every §39 category, explicit state-sufficiency and cycle-distinction tests, and a requirement-by-requirement §38 coverage map that keeps cross-architecture and partial rows open.
- Resolved Vulcan review findings by enforcing `max_actions_per_entity` for slotless and replacement starts, aligning keyed runtime snapshot collections with the snapshot schema, and adding direct regressions for both.
- Added an independent Rust PCAM-CJ1 canonicalizer and hasher with shared exact-byte, digest, definition, integer-boundary, Unicode-normalization, escaping, and floating-point-rejection vectors; the independent runtime gate remains open.
- Added machine-readable networking topology declarations, required latency and correction fields, duplicate-ID rejection, and canonical runtime-profile hashes that bind all §31 limits; executable network services remain open.
- Adopted CC BY 4.0 for the specification and documentation, MIT for implementation code and schemas, and CC0 1.0 for reusable conformance vectors, with separate trademark and patent statements.
- Added bounded declarative extension registration, safe optional omission, unknown-required rejection, authoritative contract and payload validation, registry identity hashing, and snapshot extension-state limits; end-to-end authoritative extension semantics remain open.
