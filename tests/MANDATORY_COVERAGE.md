# Mandatory Conformance Coverage

Status: ACTIVE

Owner: PCAM conformance suite

This map names current executable evidence for specification §38. A mapped test is not automatically complete evidence if its implementation surface is narrower than the normative requirement.

| Requirement | Current executable evidence | State |
|---|---|---|
| 38.1 State sufficiency | `vectors/state-distinction-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with equal action phase, freeze-token stall counters 4 and 1, distinct canonical serializations and hashes, and pinned divergent future progression |
| 38.2 Cycle distinction | same shared complete-state vector, cycle-distinction case | implemented directly with equal action phase, cycle values 0 and 12, distinct canonical serializations and hashes, and pinned distinct continuation digests |
| 38.3 Once per action during freeze | `vectors/once-freeze-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with one hit, two frozen emission ticks, post-freeze ledger suppression, and four exact state digests |
| 38.4 Once per cycle | `vectors/ledger-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with same-cycle duplicate rejection, explicit checked cycle increment, renewed eligibility, a second same-cycle rejection, and exact per-tick digests |
| 38.5 Predicate reactivation | same shared complete-state vector, predicate-activation case | implemented directly with same-activation duplicate rejection, predicate exit and re-entry serials, renewed eligibility, a second same-activation rejection, and exact per-tick digests |
| 38.6 Explicit skip | `vectors/explicit-skip-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with seekable target step 3, one declared resource effect, no implicit continuation effect, snapshot restore, and three exact state digests |
| 38.7 Buffer expiration | paired `buffer-expiry-normal` and `buffer-expiry-frozen` cases in `vectors/action-runtime.json`, executed by Python and independent Rust | implemented directly with the same TTL-1 input expiring in its capture tick normally, surviving exactly one `BUFFER_EXPIRY`-frozen tick, then expiring after the freeze |
| 38.8 Resource arbitration | `vectors/contended-starts.json` in Python and independent Rust complete-state runtimes | implemented directly across both raw input permutations with the same canonical winner, one atomic resource-and-slot reservation, no losing allocation, identical snapshots, and one exact digest |
| 38.9 Slot replacement | accepted and rejected cases in `vectors/transition-replacement.json`, executed by both complete-state runtimes | implemented directly: success releases and reacquires the slot atomically, while insufficient target resources preserve the source lifecycle, slot ownership, bank, transition serial, and identifier counter exactly |
| 38.10 Parent-child restore | `vectors/parent-child.json` in Python and independent Rust complete-state runtimes | implemented directly with a mid-child snapshot preserving the running child identity, parent link, child slot, parent progression freeze, future child-result delivery, and every remaining state digest |
| 38.11 Simultaneous trade | `vectors/simultaneous-trade-runtime.json` in Python and independent Rust complete-state runtimes | implemented directly with two lethal candidates, frozen semantic facts, two authoritative commits, reversed raw order, and one exact final digest |
| 38.12 Armor with outgoing attack | same shared complete-state vector, armored case | implemented directly with incoming damage halved, outgoing lethal damage preserved, reversed raw order, and one exact final digest |
| 38.13 Candidate permutation | both cases in the same vector execute forward and reversed raw contacts | implemented directly with identical canonical order, summaries, resources, effects, and digests in both runtimes |
| 38.14 Same-tick duplicate | `vectors/typed-strike.json` in both complete-state runtimes | implemented directly with reversed raw duplicate contacts, canonical `c1` acceptance, `c2` rejection, one receipt, one effect, one resource commit, and exact state digests |
| 38.15 Redirect loop | `vectors/interaction-fault-runtime.json` plus the reject-mode case in `vectors/interactions.json`, executed by Python and independent Rust | implemented directly with deterministic visited-target or redirect-limit termination, stable contextual fault data, atomic tick rollback, and all three fault policies |
| 38.16 Save-restore equivalence | shared typed-strike, parent-child, RNG, event-delivery, and action-runtime vectors | implemented directly across complete-state snapshots and bounded action snapshots with identical continuation digests; parent-child restoration occurs while the child and parent freeze are live |
| 38.17 Rollback equivalence | `vectors/typed-strike.json` retained-history correction in Python and independent Rust plus the §45.6 rollback gate | implemented directly with corrected replay equal to direct execution, atomic correction failure, retained-window rejection, and every required rewind case |
| 38.18 RNG restore | `vectors/rng-runtime.json` and `vectors/numeric-rng.json` in Python and independent Rust | implemented directly with pre-draw snapshot restoration, identical draw value and count, exact stream state, complete-state continuation, and pinned digests |
| 38.19 Cross-architecture digest | no Linux ARM64 execution evidence | missing |
| 38.20 Invalid definitions | 14 shared `definition_fault_cases` in `vectors/action-runtime.json`, 23 cases in `invalid/schema-mutations.json`, and dedicated invalid fixtures | implemented directly with stable `DEFINITION_REJECTED` across Python and independent Rust for bounded action semantics, plus repeat-identical schema diagnostics with a pinned code or fault for every structural/semantic mutation and dedicated version, range, and rollback-profile fixtures |

Release conformance remains open until every row is direct, complete evidence against the full normative behavior.
