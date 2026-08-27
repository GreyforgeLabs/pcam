import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit():
    return json.loads((ROOT / "release/independent-code-audit.json").read_text())


def test_independent_rust_source_inventory_and_hashes_are_pinned():
    audit = _audit()
    implementation = ROOT / audit["implementation_root"]
    source = implementation / "src"
    actual = {
        path.relative_to(implementation).as_posix(): _sha256(path)
        for path in sorted(source.glob("*.rs"))
    }

    assert actual == audit["source_sha256"]
    assert _sha256(implementation / "Cargo.toml") == audit["manifest_sha256"]
    assert _sha256(implementation / "Cargo.lock") == audit["lockfile_sha256"]
    assert not (implementation / "build.rs").exists()
    assert all(not path.is_symlink() for path in source.iterdir())


def test_independent_rust_dependencies_have_no_python_execution_bridge():
    audit = _audit()
    implementation = ROOT / audit["implementation_root"]
    manifest = tomllib.loads((implementation / "Cargo.toml").read_text())
    lockfile = tomllib.loads((implementation / "Cargo.lock").read_text())

    assert set(manifest.get("dependencies", {})) == set(audit["allowed_direct_dependencies"])
    assert set(manifest.get("dev-dependencies", {})) == set(audit["allowed_dev_dependencies"])
    assert manifest.get("build-dependencies", {}) == {}
    forbidden = re.compile(audit["forbidden_package_regex"])
    assert [package["name"] for package in lockfile["package"] if forbidden.search(package["name"])] == []


def test_independent_rust_source_has_no_reference_runtime_or_generated_code_path():
    audit = _audit()
    implementation = ROOT / audit["implementation_root"]
    failures = []
    for relative in sorted(audit["source_sha256"]):
        text = (implementation / relative).read_text()
        for pattern in audit["forbidden_source_patterns"]:
            if re.search(pattern["regex"], text):
                failures.append(f"{relative}:{pattern['id']}")
    assert failures == []
