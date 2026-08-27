# Cross-Platform Gate

State: OPEN

Required: identical state digests demonstrated on Linux x86-64 and Linux ARM64. Local x86-64 evidence alone cannot close this gate.

## Evidence present

- `tests/cross-platform/linux-x86_64.json` records actual Linux x86-64 execution of Python and independent Rust over typed strike, mixed-stage child interaction, shared RNG call order, and parent-child lifecycle scenarios.
- Both implementations match every definition-set hash, per-tick state digest, and final state digest. The architecture-independent case payload has suite digest `795bec98fc4e22d2127d64868af5ba1b806a42be62fd40f3fa8b90846b38046d`.
- `experiments/run_cross_platform.py` refuses non-Linux or unsupported reported architectures, executes both language implementations, rejects any divergence, and emits an architecture-named manifest.
- `reference/python/tests/test_cross_platform_manifest.py` reproduces the x86-64 manifest and prevents this gate from closing while the ARM64 manifest is absent.

## Remaining before closure

- Execute the same runner on a real or transparently emulated Linux ARM64 host.
- Commit `tests/cross-platform/linux-arm64.json` only if its suite digest exactly matches the pinned x86-64 suite digest.
- Run the full Python and Rust gates on that ARM64 host before changing this gate state.
