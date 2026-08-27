# Comparative Experiment Gate

State: CLOSED FOR THE CURRENT BOUNDED DRAFT EXPERIMENT

The reproducible `heavy-strike-trade-v1` experiment includes every §45.7 subject:

1. fixed-tick FSM
2. statechart with local counters
3. animation-independent frame data
4. PCAM Core
5. PCAM Core with PCAM-24

Evidence:

- subject manifest: `../experiments/baselines/subjects.json`
- executable harness: `../experiments/run_comparison.py`
- methodology and limitations: `../experiments/methodology/README.md`
- raw Linux x86-64 result: `../experiments/results/linux-x86_64.json`
- deterministic test: `../reference/python/tests/test_comparative_experiment.py`

Every named measurement is present. Human authoring time and subjective trace clarity were not available, so the experiment uses explicitly labeled definition-size and trace-field proxies. Host timing is environment-specific and excluded from the deterministic report digest. The result supports no general performance or superiority claim.

This gate reopens if the shared scenario, subject adapters, measurement definitions, or source definitions change without repinned evidence.
