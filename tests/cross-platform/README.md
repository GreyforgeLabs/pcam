# Cross-Platform Digest Evidence

The committed Linux x86-64 manifest was produced by actual Python and Rust execution on an x86-64 host.

The committed `linux-arm64.json` was produced by actual GitHub-hosted Linux ARM64 execution after the complete Python and Rust gates passed. To reproduce it on another host whose operating system reports Linux and whose machine architecture reports `aarch64` or `arm64`, run:

```bash
python3 experiments/run_cross_platform.py --output tests/cross-platform/linux-arm64.json
PYTHONPATH=reference/python pytest -q
cargo fmt --check --manifest-path independent/rust/Cargo.toml
cargo check --manifest-path independent/rust/Cargo.toml
cargo test --manifest-path independent/rust/Cargo.toml
```

The runner executes both implementations and refuses to emit a manifest when they diverge. The resulting `suite_digest` must equal `795bec98fc4e22d2127d64868af5ba1b806a42be62fd40f3fa8b90846b38046d`.

Cross-compilation without ARM64 execution is not evidence for §38.19.
