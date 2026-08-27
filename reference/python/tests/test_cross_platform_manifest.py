import importlib.util
import json
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "experiments/run_cross_platform.py"
X86_MANIFEST = ROOT / "tests/cross-platform/linux-x86_64.json"
ARM64_MANIFEST = ROOT / "tests/cross-platform/linux-arm64.json"


def _module():
    spec = importlib.util.spec_from_file_location("run_cross_platform", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_x86_manifest_is_reproducible_and_cross_language_exact():
    committed = json.loads(X86_MANIFEST.read_text(encoding="utf-8"))
    assert committed["environment"]["architecture"] == "linux-x86_64"
    assert committed["suite_digest"] == "795bec98fc4e22d2127d64868af5ba1b806a42be62fd40f3fa8b90846b38046d"
    if platform.machine().lower() == "x86_64":
        assert _module().build_manifest() == committed


def test_arm64_gate_cannot_close_without_a_real_arm64_manifest():
    assert not ARM64_MANIFEST.exists()
    gate = (ROOT / "release/cross-platform-gate.md").read_text(encoding="utf-8")
    assert "State: OPEN" in gate
    assert "Linux ARM64" in gate
