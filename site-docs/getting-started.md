# Run the Reference

PCAM v3 targets Python 3.12 for the readable reference runtime and stable Rust for the independent implementation.

## Install the Python reference

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
```

## Validate and trace the canonical scenario

```bash
pcam validate examples/heavy-strike.scenario.json
pcam trace examples/heavy-strike.scenario.json
pcam snapshot examples/heavy-strike.scenario.json
```

## Run both implementation suites

```bash
python -m pytest reference/python/tests
cargo test --manifest-path independent/rust/Cargo.toml --locked
```

## Verify the local cross-language digest

On Linux x86-64:

```bash
python experiments/run_cross_platform.py --check tests/cross-platform/linux-x86_64.json
```

On Linux ARM64, generate candidate evidence:

```bash
python experiments/run_cross_platform.py --output tests/cross-platform/linux-arm64.json
```

The ARM64 result is valid only when the runner detects actual Linux ARM64 execution, Python and Rust agree, and the suite digest matches the pinned x86-64 evidence.

