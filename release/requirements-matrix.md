# PCAM v3 Requirements Matrix

Status: ACTIVE

Owner: PCAM release integration

This matrix preserves the complete target. A row is complete only when its named evidence directly proves the requirement.

| Spec area | Required evidence | Current state |
|---|---|---|
| §1-6 language, scope, invariants, determinism boundary, formal model | contradiction-free specification audit | missing |
| §7 authoritative state | snapshot schema plus complete-state round-trip vectors | partial: initial schema and slice round-trip |
| §8 definitions | action schema, immutable hash binding, positive and negative vectors | missing |
| §9 numeric semantics | arithmetic unit/property vectors including Euclidean division and overflow | partial: Python and independent Rust agree on shared checked I64/U64 overflow, Euclidean division, exact ratio, negative-floor, and checked-intermediate vectors; broader generated cross-language arithmetic remains open |
| §10 progression | rational accumulator and bounded quantum vectors | partial: targeted rational-rate, HOLD/ACCRUE deferred-state, and limit slice |
| §11-12 expressions and predicates | pure evaluator, cycle validator, edge serial vectors | partial: Python and independent Rust agree on every bounded pure expression operator and core faults; Python also has cycle validation and runtime edge serials, while independent predicate-graph execution remains open |
| §13 inputs | canonical ordering, buffering, TTL, overflow, and consumption vectors | partial: runtime capture/consume/expiry plus pure capacity and policy vectors |
| §14 transitions | all evaluation points, priorities, targets, mutation order, seek/skip vectors | missing |
| §15-16 intents, claims, slots | atomic arbitration and replacement vectors | partial: runtime-integrated resource/slot starts, permutation invariance, atomic replacement, and ID allocation; child/capacity/exclusive integration and group semantics open |
| §17 parent-child | lifecycle, freeze, result event, nesting, restore vectors | partial: runtime child slots, relationships, nesting bounds, parent freezes, termination policy, next-tick result, and restore equivalence; two policy precedence gaps open |
| §18 freezes | domains, timing, expiry, stacking, accrual vectors | partial: runtime progression, transition, capture, and expiry domains plus provisional stacking; normative gap open |
| §19-22 facts, candidates, interactions, ledgers | frozen snapshot, typed stages, redirection, receipt vectors | partial: runtime-integrated semantic facts, five-stage resolver, all ledger policies, provisional receipts, reducers, and defense ambiguity fault; defense-selection semantics remain open |
| §23 effects | identifiers, canonical order, reducers, exclusive/custom vectors | partial: runtime-integrated authoritative registry commits plus all core reducer primitives and rejection traces |
| §24 tick pipeline | deterministic twelve-stage trace vectors | partial: ordered vertical-slice trace |
| §25 events | delivery order, modes, and lifetime vectors | partial: canonical next-tick scheduling, snapshot round trip, duplicate rejection, and provisional freeze deferral |
| §26 RNG | PCG32 vectors, snapshot state, restore vectors | partial: Python and independent Rust agree on canonical PCG32 outputs, snapshot state, profile validation, restore continuation, and draw-count overflow policy; runtime stream integration breadth remains open |
| §27 canonicalization and hashes | PCAM-CJ1 corpus and exact digest vectors | partial: Python and independent Rust serializers agree on shared exact-byte and SHA-256 vectors, including a real definition; wider hostile and cross-architecture corpora remain open |
| §28 save and restore | schema, round-trip, continuation equivalence | partial: slice round-trip and correction equivalence |
| §29 networking | declared local, lockstep, rollback, and server prediction profile artifacts | partial: machine-readable topology declarations, required mechanism/limit fields, canonical profile hashing, and rejection vectors; executable network services remain open |
| §30-31 faults and limits | stable fault codes and every declared bound tested | partial: full core runtime fault enum, validated fault-policy declaration, canonically hashed required limits, extension-state bound, and several runtime bounds; policy execution and exhaustive bound enforcement remain open |
| §32 PCAM-24 | schema, compiler, lifecycle, projection, migration warnings | partial: schema, explicit TERMINATE/LOOP/CLAMP compiler, expression-backed projections, and warning-first v1/v2 migration; broader profile lifecycle vectors remain open |
| §33-34 examples | examples validate and execute with expected trace/digests | complete: schema-valid Heavy Strike, Dodge, and combat interaction documents execute for 60 ticks with pinned document, definition-set, trace, and final-state digests plus parry, armor, duplicate-contact, and trade assertions |
| §35 tracing | complete deterministic trace contract and canonicalized vectors | partial: canonical 60-tick example trace and vertical-slice trace digests are pinned; complete field coverage and rejection-reason vectors remain open |
| §36 extensions | namespace, required/optional, authoritative extension validation | partial: namespace and omission rules, declarative authoritative contracts, payload schemas, bounded state, registry identity hashing, and negative vectors; an end-to-end authoritative extension remains open |
| §37 classes | evidence manifest for each claimed class | missing |
| §38 mandatory tests | all 20 tests implemented and passing | partial: coverage map committed; 38.19 missing and several rows still composed/partial |
| §39 generated tests | all listed generators plus determinism and continuation properties | partial: deterministic generated surfaces cover every listed category; breadth and independent execution remain open |
| §40 migration | v1/v2 importer warnings and version rejection vectors | complete: bounded explicit-version importer, all required warning classes, deterministic evidence hashes, valid review-only PCAM-24 output, and fail-closed compatibility vectors |
| §41 repository | required structure and documentation | partial: required lanes and authority files exist |
| §42 tooling | all eleven commands with stable machine-readable result codes | partial: all eleven command paths execute with JSON envelopes; broader normative vectors and diagnostics remain open |
| §43 licenses | CC BY 4.0 spec, Apache-2.0 or MIT code, vector permissions, trademark separation | complete: per-path license map, full CC BY 4.0, MIT, and CC0 1.0 texts, attribution, separate trademark policy, and explicit patent statement |
| §44 security | bounded untrusted-data validation and adversarial vectors | partial: document/tick/expression/runtime bounds and schema checks; exhaustive hostile corpus pending |
| §45 release gates | eight evidence reports with no unresolved requirement | partial: independent-language PCAM-CJ1 evidence exists; the independent runtime, cross-architecture manifests, experiments, audits, and remaining gates are open |

## Completion rule

Search results, passing smoke tests, and plausible behavior are not enough. Each row requires the authoritative artifact and validation scope named above.
