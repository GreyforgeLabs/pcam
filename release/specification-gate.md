# Specification Gate

State: OPEN

## Resolved contradiction

The source draft header pointed to release gates in §27. Release gates are defined in §45, while §27 defines canonical serialization and hashing. The repository specification now points to §45. A complete contradiction audit remains open.

The source draft also required actions to enter an initial node without declaring how that node was selected. The repository specification and action schema now require an explicit `initial_node`; map insertion order has no semantic effect.

## Required evidence

- no unresolved normative contradictions
- all core terms defined
- all algorithms bounded
- all ordering rules explicit
- all fault behavior explicit
- PCAM-24 clearly separated from Core

Open normative gaps are tracked in `../spec/open-issues.md`.
