# Comparative Experiment Methodology

Status: REPRODUCIBLE BOUNDED EXPERIMENT

The §45.7 experiment compares:

1. a conventional fixed-tick finite-state machine
2. a statechart with state-local counters
3. an animation-independent frame-data action system
4. PCAM Core without PCAM-24
5. PCAM Core with PCAM-24

## Shared contract

Every subject executes `heavy-strike-trade-v1`: two 60-tick Heavy Strike actions, rational `400/1000` progression, startup, active, and recovery intervals of 10, 4, and 10 quanta, three same-tick contacts with one duplicate, active armor, once-per-action contact limits, and mutual 30-point damage. The expected observable result is 70 HP and zero stagger for each entity, with both actions terminated.

All six permutations of the three raw contacts are replayed. A subject fails before measurement if it does not reach the shared observable result.

## Measurements

- Runtime state and snapshot size are canonical JSON byte counts of the subject's normalized logical state. They are representation measurements, not process-memory measurements.
- Resimulation reports 60 logical ticks, 129 normalized semantic work units, and host wall-clock samples. A work unit is one action-tick, canonical candidate, or node-transition commit. Host timing uses 11 complete replays after one warmup and records minimum, median, and maximum `perf_counter_ns` values.
- Definition complexity reports canonical bytes and leaf values.
- Validation coverage reports the subject's declared checks against the ten-item comparison universe. It is not a claim that each subject has equivalent validation depth.
- Replay divergence is the number of the six contact permutations that differ from the first observable digest.
- Authoring effort uses definition bytes and leaf values as disclosed proxies. No human labor time was captured, so the experiment does not claim to measure actual authoring effort.
- Debug trace clarity uses declared §35 trace-field coverage as a disclosed proxy. It is not a subjective quality score.
- Hidden assumptions and ambiguous interaction cases are reviewed manifest entries, not inferred quality rankings.

## Reproduction

From the repository root:

```text
python3 experiments/run_comparison.py --check experiments/results/linux-x86_64.json
python3 experiments/run_comparison.py --timing --timing-repetitions 11
```

The first command verifies deterministic report content while ignoring the environment-specific timing block. The second prints a new host timing sample. Raw x86-64 evidence records the exact Python version, machine architecture, and timing clock.

## Interpretation limits

The five adapters do not perform equal internal work. In particular, the reference PCAM adapter performs schema-derived execution, canonical trace construction, snapshot construction, expression evaluation, interaction resolution, and hashing that the small comparison baselines do not implement. Wall-clock values therefore describe these exact adapters only and do not establish general performance, production readiness, novelty, or superiority.
