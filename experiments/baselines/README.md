# Experiment Baselines

`subjects.json` is the reviewed subject manifest. `../run_comparison.py` contains bounded adapters for the conventional fixed-tick FSM, statechart with local counters, animation-independent frame data, the reference PCAM Core runtime, and the same PCAM runtime with a non-authoritative PCAM-24 projection.

The three small baselines exist only for `heavy-strike-trade-v1`. They are not general-purpose implementations and are not conformance candidates. Their host-coded contact, armor, and ledger behavior is listed as assumptions in the manifest.

The PCAM subjects execute the repository's schema-valid Heavy Strike, Dodge, and combat interaction documents through the reference runtime. The Core measurement strips the optional projection from its complexity artifact. The PCAM-24 measurement retains it and emits a non-authoritative phase projection without changing authoritative snapshot state.
