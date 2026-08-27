#!/usr/bin/env python3
"""Execute the shared digest suite on the host's reported Linux architecture."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/python"))

from pcam_runtime import canonical_hash, run_vector  # noqa: E402

VECTOR_PATHS = (
    "tests/vectors/typed-strike.json",
    "tests/vectors/mixed-stage-runtime.json",
    "tests/vectors/rng-call-order-runtime.json",
    "tests/vectors/parent-child.json",
)
ARCHITECTURES = {"x86_64": "linux-x86_64", "aarch64": "linux-arm64", "arm64": "linux-arm64"}


def _command(*arguments: str) -> str:
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _rust_manifest(path: Path) -> dict[str, object]:
    source = _command(
        "cargo",
        "run",
        "--quiet",
        "--manifest-path",
        str(ROOT / "independent/rust/Cargo.toml"),
        "--",
        "simulation-manifest",
        str(path),
    )
    result = json.loads(source)
    if result.get("code") != "OK":
        raise RuntimeError(f"Rust manifest failed for {path}: {result}")
    return result


def build_manifest() -> dict[str, object]:
    machine = platform.machine().lower()
    architecture = ARCHITECTURES.get(machine)
    if platform.system() != "Linux" or architecture is None:
        raise RuntimeError("cross-platform evidence requires reported Linux x86-64 or ARM64 execution")
    cases = []
    for relative in VECTOR_PATHS:
        path = ROOT / relative
        document = json.loads(path.read_text(encoding="utf-8"))
        python_run = run_vector(document)
        python_result = {
            "definition_set_hash": python_run.executor.definition_set_hash,
            "final_state_digest": python_run.final_state.state_hash(),
            "tick_state_digests": [trace["state_digest"] for trace in python_run.traces],
        }
        rust_result = _rust_manifest(path)
        rust_result.pop("code")
        if rust_result != python_result:
            raise RuntimeError(f"Python/Rust digest divergence for {relative}")
        cases.append({"id": path.stem, **python_result})
    return {
        "manifest_version": "1",
        "environment": {
            "architecture": architecture,
            "byteorder": sys.byteorder,
            "machine": machine,
            "os": platform.system(),
            "python": platform.python_version(),
            "rustc": _command("rustc", "--version"),
        },
        "cases": cases,
        "suite_digest": canonical_hash(cases),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", type=Path)
    mode.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    manifest = build_manifest()
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.check is not None:
        matches = arguments.check.read_text(encoding="utf-8") == encoded
        print(json.dumps({"matches": matches, "suite_digest": manifest["suite_digest"]}))
        return 0 if matches else 1
    if arguments.output is not None:
        expected_name = f"{manifest['environment']['architecture']}.json"
        if arguments.output.name != expected_name:
            raise RuntimeError(f"output must be named {expected_name}")
        arguments.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({"output": str(arguments.output), "suite_digest": manifest["suite_digest"]}))
        return 0
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
