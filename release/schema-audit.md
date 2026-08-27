# Schema Audit

State: PASS for `3.0.0-draft.1`

## Normative definition coverage

`schema-audit.json` maps every §8 and §45.2 portable definition category to machine-readable Draft 2020-12 schemas and positive documents:

- action definitions
- interaction profiles
- simulation profiles
- networking profiles
- PCAM-24 compatibility profiles
- extension declarations embedded in definitions and profiles

Snapshot and conformance-manifest schemas are additional machine-document coverage. Extension runtime registrations are implementation records rather than portable definition documents; portable extension declarations are governed by `common.schema.json#/$defs/extensionMap`.

## Structural and semantic coverage

The action schema now types canonical node operations, semantic facts, hit policies, effect templates, transitions, targets, matches, claims, assignments, effects, cycle deltas, slot claims, and embedded PCAM-24 projections. The interaction schema types every Core rule operation. Runtime and networking schemas enforce topology-specific fields and every declared limit. Extension schemas enforce optional omission safety and the full authoritative contract.

Semantic validation covers node and initial-node references, node-map identity, timed completion paths, transition and fact identity, priority uniqueness, seekability, contested AFTER_QUANTUM claims, parameter and register bounds, predicate cycles and fact references, policy-dependent hit fields, PCAM-24 range coverage, network-profile identity, rejected materialization bounds, conformance dependencies, and the global floating-point prohibition.

## Vectors

- Nine positive documents cover the six normative categories, including every network topology and a valid optional extension.
- `../tests/invalid/schema-mutations.json` contains 23 deterministic structural and semantic mutations with stable expected result or fault codes.
- Dedicated invalid fixtures cover version rejection, wrapping PCAM-24 ranges, and incomplete rollback networking declarations.
- PCAM-CJ1, typed-strike, and Heavy Strike vectors pin canonical hashes beyond schema acceptance.

Executable evidence: `../reference/python/tests/test_schema.py`, `../reference/python/tests/test_schema_audit.py`, and `../reference/python/tests/test_extensions.py`.

This gate proves definition-document schema coverage. It does not claim that either interpreter executes every structurally valid nonempty assignment, effect, extension, or profile behavior; those remain reference, independent, extension, and networking runtime gate concerns.
