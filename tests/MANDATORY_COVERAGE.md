# Mandatory Conformance Coverage

Status: ACTIVE

Owner: PCAM conformance suite

This map names current executable evidence for specification §38. A mapped test is not automatically complete evidence if its implementation surface is narrower than the normative requirement.

| Requirement | Current executable evidence | State |
|---|---|---|
| 38.1 State sufficiency | `test_mandatory_conformance.py::test_38_1_*` | implemented for freeze state and future behavior |
| 38.2 Cycle distinction | `test_mandatory_conformance.py::test_38_2_*` | implemented |
| 38.3 Once per action during freeze | runtime freeze, typed interaction, and ledger tests | implemented across composed unit surfaces; dedicated integrated vector pending |
| 38.4 Once per cycle | `test_ledgers.py::test_cycle_and_predicate_activation_are_part_of_policy_key` | implemented key eligibility; full looping runtime vector pending |
| 38.5 Predicate reactivation | same ledger test plus predicate edge runtime tests | implemented across composed unit surfaces |
| 38.6 Explicit skip | seekable validation and transition target-step runtime behavior | partial; entry/exit effect model breadth pending |
| 38.7 Buffer expiration | `test_buffers.py` and runtime freeze integration | implemented for normal/frozen expiry primitives |
| 38.8 Resource arbitration | `test_intents.py` and competing start runtime test | implemented |
| 38.9 Slot replacement | runtime failed/successful atomic replacement tests | implemented |
| 38.10 Parent-child restore | runtime parent-child restore-equivalence test | implemented |
| 38.11 Simultaneous trade | `test_interactions.py::test_candidate_order_*` | implemented on frozen pure resolver surface |
| 38.12 Armor with outgoing attack | parry/armor/independent outgoing interaction tests | implemented on pure resolver surface |
| 38.13 Candidate permutation | runtime digest-permutation test | implemented |
| 38.14 Same-tick duplicate | typed runtime receipt test | implemented |
| 38.15 Redirect loop | pure resolver fault/reject test | implemented |
| 38.16 Save-restore equivalence | runtime and generated continuation tests | implemented for current supported state |
| 38.17 Rollback equivalence | CLI pinned vector and generated corrections | implemented for current supported state |
| 38.18 RNG restore | shared Python/Rust PCG32 output, snapshot, restore, and next-draw vector | implemented independently in both languages |
| 38.19 Cross-architecture digest | no Linux ARM64 execution evidence | missing |
| 38.20 Invalid definitions | schema negative vectors and semantic validator tests | partial breadth |

Release conformance remains open until every row is direct, complete evidence against the full normative behavior.
