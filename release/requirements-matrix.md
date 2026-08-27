# PCAM v3 Requirements Matrix

Status: ACTIVE

Owner: PCAM release integration

This matrix preserves the complete target. A row is complete only when its named evidence directly proves the requirement.

| Spec area | Required evidence | Current state |
|---|---|---|
| §1-6 language, scope, invariants, determinism boundary, formal model | contradiction-free specification audit | missing |
| §7 authoritative state | snapshot schema plus complete-state round-trip vectors | partial: initial schema and slice round-trip |
| §8 definitions | action schema, immutable hash binding, positive and negative vectors | missing |
| §9 numeric semantics | arithmetic unit/property vectors including Euclidean division and overflow | partial: checked I64/U64 policies, Euclidean division, exact ratio vectors |
| §10 progression | rational accumulator and bounded quantum vectors | partial: targeted rational-rate and limit slice |
| §11-12 expressions and predicates | pure evaluator, cycle validator, edge serial vectors | partial: bounded core evaluator, cycle validation, slice edge serials |
| §13 inputs | canonical ordering, buffering, TTL, overflow, and consumption vectors | partial: pure capacity, TTL, ordering, and consumption primitives |
| §14 transitions | all evaluation points, priorities, targets, mutation order, seek/skip vectors | missing |
| §15-16 intents, claims, slots | atomic arbitration and replacement vectors | missing |
| §17 parent-child | lifecycle, freeze, result event, nesting, restore vectors | missing |
| §18 freezes | domains, timing, expiry, stacking, accrual vectors | partial: pure activation, expiry, provisional stacking, and accrual primitives; normative gap open |
| §19-22 facts, candidates, interactions, ledgers | frozen snapshot, typed stages, redirection, receipt vectors | partial: directed once-per-action slice only |
| §23 effects | identifiers, canonical order, reducers, exclusive/custom vectors | missing |
| §24 tick pipeline | deterministic twelve-stage trace vectors | partial: ordered vertical-slice trace |
| §25 events | delivery order, modes, and lifetime vectors | missing |
| §26 RNG | PCG32 vectors, snapshot state, restore vectors | partial: canonical PCG32 vector and snapshot restore |
| §27 canonicalization and hashes | PCAM-CJ1 corpus and exact digest vectors | partial: canonical serializer and unit vectors |
| §28 save and restore | schema, round-trip, continuation equivalence | partial: slice round-trip and correction equivalence |
| §29 networking | declared local, lockstep, rollback, and server prediction profile artifacts | missing |
| §30-31 faults and limits | stable fault codes and every declared bound tested | missing |
| §32 PCAM-24 | schema, compiler, lifecycle, projection, migration warnings | partial: schema and explicit TERMINATE/LOOP/CLAMP compiler |
| §33-34 examples | examples validate and execute with expected trace/digests | missing |
| §35 tracing | complete deterministic trace contract and canonicalized vectors | missing |
| §36 extensions | namespace, required/optional, authoritative extension validation | missing |
| §37 classes | evidence manifest for each claimed class | missing |
| §38 mandatory tests | all 20 tests implemented and passing | missing |
| §39 generated tests | all listed generators plus determinism and continuation properties | missing |
| §40 migration | v1/v2 importer warnings and version rejection vectors | missing |
| §41 repository | required structure and documentation | partial: required lanes and authority files exist |
| §42 tooling | all eleven commands with stable machine-readable result codes | partial: six implemented, five explicit reserved failures |
| §43 licenses | CC BY 4.0 spec, Apache-2.0 or MIT code, vector permissions, trademark separation | missing |
| §44 security | bounded untrusted-data validation and adversarial vectors | missing |
| §45 release gates | eight evidence reports with no unresolved requirement | missing |

## Completion rule

Search results, passing smoke tests, and plausible behavior are not enough. Each row requires the authoritative artifact and validation scope named above.
