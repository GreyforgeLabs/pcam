# Target-State Contract

Status: ACTIVE

Owner: Codex orchestrator

## Desired end state

Implement the complete PCAM v3 specification as a conformance-first repository, including every repository and tooling deliverable in §41-42 and evidence for every release gate in §45.

## Owners and paths

- Specification and schemas: `spec/`, `schemas/`
- Reference behavior: `reference/python/`
- Independent behavior: `independent/rust/`
- Shared black-box evidence: `tests/`
- Comparative evidence: `experiments/`
- Gate decisions: `release/`

One implementation may consume shared schemas and vectors, but the independent implementation must not share runtime execution code with the Python reference.

## Constraints and gates

- Complete action state, not phase, is authoritative.
- PCAM Core and PCAM-24 remain separate.
- All ordering, limits, fault behavior, RNG, identifiers, and state are explicit.
- No floating point enters authoritative definitions or Core state.
- Untrusted definitions, snapshots, replays, and inputs are bounded and validated.
- Draft status remains until every §45 gate has direct evidence.
- No deployment or public release is implied by local completion.

## Validation path

1. Targeted Python and Rust unit tests.
2. Schema positive and negative vectors with stable result codes.
3. Shared mandatory conformance and generated property vectors.
4. Save-restore and rollback continuation equivalence.
5. Independent implementation digest agreement.
6. Linux x86-64 and Linux ARM64 digest manifests.
7. Comparative experiment artifacts.
8. Requirement-by-requirement release audit.

## Recovery path

Each coherent implementation increment is committed separately. Failed experimental work remains isolated from the conformance vectors and can be reverted by commit without touching external runtime state.
