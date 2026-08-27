# Cross-Platform Gate

State: CLOSED

Required: identical state digests demonstrated on Linux x86-64 and Linux ARM64.

## Evidence present

- `tests/cross-platform/linux-x86_64.json` records actual Linux x86-64 execution of Python and independent Rust over typed strike, mixed-stage child interaction, shared RNG call order, and parent-child lifecycle scenarios.
- `tests/cross-platform/linux-arm64.json` records actual GitHub-hosted Linux ARM64 execution of the same Python and independent Rust suite after the complete ARM64 Python and Rust gates passed.
- Both implementations match every definition-set hash, per-tick state digest, and final state digest. The architecture-independent case payload has suite digest `795bec98fc4e22d2127d64868af5ba1b806a42be62fd40f3fa8b90846b38046d`.
- `experiments/run_cross_platform.py` refuses non-Linux or unsupported reported architectures, executes both language implementations, rejects any divergence, and emits an architecture-named manifest.
- `reference/python/tests/test_cross_platform_manifest.py` reproduces the x86-64 semantic evidence and requires exact case and suite-digest identity across the committed x86-64 and ARM64 manifests.

## Closure

GitHub Actions run `33097510274` executed on `ubuntu-24.04-arm`. Its ARM64 job passed the complete Python and Rust gates, generated the committed manifest, and matched the pinned x86-64 suite digest exactly. This closes only the cross-platform execution gate. It does not claim any Section 37 conformance class.
