import importlib.util
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULT = ROOT / "experiments/results/linux-x86_64.json"


def _module():
    path = ROOT / "experiments/run_comparison.py"
    spec = importlib.util.spec_from_file_location("pcam_comparison", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_comparative_experiment_replays_all_five_subjects_without_divergence():
    report = _module().build_report()
    assert [item["subject_id"] for item in report["results"]] == [
        "fixed-tick-fsm",
        "statechart-local-counters",
        "frame-data",
        "pcam-core",
        "pcam-core-pcam24",
    ]
    assert len({item["observable_digest"] for item in report["results"]}) == 1
    assert all(item["replay_divergence"] == {"contact_permutations": 6, "divergent_runs": 0} for item in report["results"])
    assert all(item["resimulation_cost"]["logical_ticks"] == 60 for item in report["results"])


def test_committed_host_result_is_reproducible_on_its_declared_architecture():
    committed = json.loads(RESULT.read_text())
    assert committed["environment"]["machine"] == "x86_64"
    if platform.machine() == "x86_64":
        committed.pop("host_timing")
        assert _module().build_report() == committed
