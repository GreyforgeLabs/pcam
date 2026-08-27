# Comparative Experiment Methodology

Status: DRAFT

The §45.7 experiment must compare:

1. a conventional fixed-tick finite-state machine
2. a statechart with state-local counters
3. an animation-independent frame-data action system
4. PCAM Core without PCAM-24
5. PCAM Core with PCAM-24

Every subject must implement the same declared scenario set and host contract. Measurements include runtime state size, snapshot size, resimulation cost, definition complexity, validation coverage, replay divergence rate, authoring effort, trace clarity, hidden assumptions, and ambiguous interaction cases.

No performance or superiority conclusion is available until reproducible baselines, environment metadata, raw results, and analysis are committed.
