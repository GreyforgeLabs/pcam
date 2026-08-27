# Independent Rust Code Audit

State: PASS for the recorded source tree

The machine audit covers `independent/rust/Cargo.toml`, `Cargo.lock`, and every Rust file under `independent/rust/src`.

It verifies the exact source inventory and SHA-256 values, rejects symlinked source, rejects build scripts and generated-source includes, restricts direct dependencies to serialization, hashing, and Unicode normalization crates, scans the complete lockfile for Python bridge packages, and rejects Python runtime paths, bindings, or subprocess execution from Rust source.

The Rust implementation consumes shared schemas and black-box JSON vectors only through its tests. Its execution source has no dependency on the Python package and no mechanism that can import, bind, spawn, include, or generate code from that package.

This is a source and dependency audit, not proof about historical authorship. Any Rust source or dependency change invalidates the pinned hashes and must update the audit through review. Runtime behavioral independence remains supported separately by cross-language black-box vectors and exact state digests.

Evidence: `independent-code-audit.json` and `../reference/python/tests/test_independent_code_audit.py`.
