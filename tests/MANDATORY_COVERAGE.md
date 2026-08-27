# Mandatory Conformance Coverage

Status: ACTIVE

Owner: PCAM conformance suite

This map names current executable evidence for specification §38. A mapped test is not automatically complete evidence if its implementation surface is narrower than the normative requirement.

| Requirement | Current executable evidence | State |
|---|---|---|
| 38.1 State sufficiency | `test_mandatory_conformance.py::test_38_1_*` | implemented for freeze state and future behavior |
| 38.2 Cycle distinction | `test_mandatory_conformance.py::test_38_2_*` | implemented |
| 38.3 Once per action during freeze | `vectors/once-freeze-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with one hit, two frozen emission ticks, post-freeze ledger suppression, and four exact state digests |
| 38.4 Once per cycle | `vectors/ledger-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with same-cycle duplicate rejection, explicit checked cycle increment, renewed eligibility, a second same-cycle rejection, and exact per-tick digests |
| 38.5 Predicate reactivation | same shared complete-state vector, predicate-activation case | implemented directly with same-activation duplicate rejection, predicate exit and re-entry serials, renewed eligibility, a second same-activation rejection, and exact per-tick digests |
| 38.6 Explicit skip | `vectors/explicit-skip-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with seekable target step 3, one declared resource effect, no implicit continuation effect, snapshot restore, and three exact state digests |
| 38.7 Buffer expiration | `test_buffers.py` and runtime freeze integration | implemented for normal/frozen expiry primitives |
| 38.8 Resource arbitration | `test_intents.py` and competing start runtime test | implemented |
| 38.9 Slot replacement | runtime failed/successful atomic replacement tests | implemented |
| 38.10 Parent-child restore | `vectors/parent-child.json` in Python and independent Rust complete-state runtimes | implemented directly with a mid-child snapshot preserving the running child identity, parent link, child slot, parent progression freeze, future child-result delivery, and every remaining state digest |
| 38.11 Simultaneous trade | `vectors/simultaneous-trade-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with two lethal candidates, frozen semantic facts, two authoritative commits, reversed raw order, and one exact final digest |
| 38.12 Armor with outgoing attack | same shared complete-state vector, armored case | implemented directly with incoming damage halved, outgoing lethal damage preserved, reversed raw order, and one exact final digest |
| 38.13 Candidate permutation | both cases in the same vector execute forward and reversed raw contacts | implemented directly with identical canonical order, summaries, resources, effects, and digests in both runtimes |
| 38.14 Same-tick duplicate | typed runtime receipt test | implemented |
| 38.15 Redirect loop | pure resolver fault/reject test | implemented |
| 38.16 Save-restore equivalence | runtime and generated continuation tests | implemented for current supported state |
| 38.17 Rollback equivalence | retained-history gate suite plus CLI and generated corrections | implemented directly across every §45.6 rewind case |
| 38.18 RNG restore | shared Python/Rust PCG32 output, snapshot, restore, and next-draw vector | implemented independently in both languages |
| 38.19 Cross-architecture digest | no Linux ARM64 execution evidence | missing |
| 38.20 Invalid definitions | schema negative vectors and semantic validator tests | partial breadth |

Release conformance remains open until every row is direct, complete evidence against the full normative behavior.
