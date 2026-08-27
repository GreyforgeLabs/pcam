# Shared Generated Conformance

`core-properties-v1.json` is the checked-in deterministic corpus generated from seed `0x5043414D39` by `experiments/generate_core_properties.py`.

It currently contains 160 cases:

- 24 rational-rate cases with repeated execution and save/restore continuation
- 24 random valid linear action graphs
- 24 random transition-guard thresholds
- 32 SUM effect-aggregation permutations
- 32 interaction-candidate permutations
- 24 bounded interaction-rule sets with shuffled definition order

Regenerate intentionally with:

```text
python experiments/generate_core_properties.py --write
```

Verify the committed artifact without mutation with:

```text
python experiments/generate_core_properties.py --check
```

Python and independent Rust both execute the same artifact. This is partial §39 coverage. Shared independent generation for freeze-token combinations, raw input-order permutations, rollback corrections, and parent-child structures remains open.
