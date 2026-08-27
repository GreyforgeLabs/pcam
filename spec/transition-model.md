# PCAM v3 Transition Model

Status: Normative Candidate companion

Owner: PCAM specification

The master authority is `PCAM-v3.md`, especially §10-18 and the §24 execution pipeline.

Transitions execute at explicit `PRE_ADVANCE`, `AFTER_QUANTUM`, or `POST_ADVANCE` points. Contested operations become atomically arbitrated intents. Node mutation order, entry behavior, skips, claims, replacement, parent-child composition, and freezes are explicit and bounded.

This companion is an index, not a second normative definition.
