import json
from pathlib import Path

from pcam_runtime.cli import main

ROOT = Path(__file__).resolve().parents[3]


def test_validate_cli_returns_stable_json_result(capsys):
    code = main(["validate", str(ROOT / "tests" / "valid" / "minimal-action.json")])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result == {"code": "OK", "diagnostics": []}


def test_compile_cli_returns_core_definition(capsys):
    code = main(["compile", str(ROOT / "tests" / "valid" / "minimal-pcam24.json")])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["code"] == "OK"
    assert result["definition"]["kind"] == "action"


def test_runtime_cli_run_trace_snapshot_and_rollback(capsys):
    vector = ROOT / "tests" / "vectors" / "typed-strike.json"
    code = main(["run", str(vector)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["code"] == "OK"
    assert result["final_tick"] == 3

    code = main(["trace", str(vector)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(result["traces"]) == 3
    assert result["traces"][0]["candidate_order"] == ["c1", "c2"]

    code = main(["snapshot", str(vector)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["snapshot"]["tick"] == 3

    code = main(["rollback-test", str(vector)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["equivalent"] is True


def test_runtime_cli_accepts_executable_example_scenario(capsys):
    scenario = ROOT / "examples" / "heavy-strike.scenario.json"

    code = main(["trace", str(scenario)])
    trace_result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert trace_result["code"] == "OK"
    assert trace_result["final_state_digest"] == "292abcece1c74f7db576821ac9b985b3c5662b53846a66e0939e64988314ac91"
    assert trace_result["traces"][24]["candidate_order"] == ["a-to-b", "a-to-b-dup", "b-to-a"]

    code = main(["run", str(scenario)])
    run_result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert run_result["code"] == "OK"
    assert run_result["final_tick"] == 60

    code = main(["snapshot", str(scenario)])
    snapshot_result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert snapshot_result["code"] == "OK"
    assert snapshot_result["snapshot"]["tick"] == 60


def test_restore_cli_round_trips_snapshot(tmp_path, capsys):
    vector = ROOT / "tests" / "vectors" / "typed-strike.json"
    main(["snapshot", str(vector)])
    generated = json.loads(capsys.readouterr().out)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(generated["snapshot"]), encoding="utf-8")
    code = main(["restore", str(snapshot_path)])
    restored = json.loads(capsys.readouterr().out)
    assert code == 0
    assert restored["snapshot"] == generated["snapshot"]
    assert restored["state_hash"] == generated["state_hash"]
