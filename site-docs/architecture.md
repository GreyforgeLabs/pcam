# Architecture

## Complete-state authority

The complete PCAM state determines what happens next. That includes action instances, immutable definition identities, current nodes, progress, cycles, registers, buffers, freeze tokens, semantic edges, parent-child relationships, interaction ledgers, events, resources, slots, monotonic identifiers, and random-stream state.

Presentation may observe this state and submit declared inputs. Presentation timing, animation state, interpolation, and rendering callbacks do not silently mutate simulation authority.

## Twelve-stage logical tick

The Core runtime orders each logical tick through twelve declared stages:

1. tick-start snapshot
2. input ingestion
3. pre-advance intent evaluation
4. pre-advance arbitration
5. action progression
6. post-advance intent evaluation and arbitration
7. semantic snapshot
8. contact and candidate generation
9. interaction resolution
10. effect reduction and commit
11. maintenance
12. snapshot and digest

This order makes simultaneous work reviewable and testable. It also keeps interaction decisions, authoritative effects, and presentation effects separate.

## Profiles, not hidden authority

PCAM Core defines the state and semantic execution model. PCAM-24 is an optional 24-cell authoring and projection profile. Networking profiles declare local deterministic, lockstep, rollback, and server-authoritative prediction behavior without pretending that phase-only reconciliation is sufficient.

## Canonical evidence

The readable Python implementation and independent Rust implementation execute shared vectors over canonicalization, numeric behavior, progression, transitions, predicates, arbitration, parent-child actions, freeze domains, typed interactions, effects, events, snapshots, faults, networking services, and retained rollback.

The full normative definition remains in the [PCAM v3 master specification](https://github.com/GreyforgeLabs/pcam/blob/main/spec/PCAM-v3.md).

