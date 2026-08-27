import json
from pathlib import Path

from pcam_runtime.cli import main

ROOT = Path(__file__).resolve().parents[3]
VECTOR = json.loads((ROOT / "tests/vectors/cli-result-codes.json").read_text())


def _invoke(capsys, command: str, path: Path | None = None) -> tuple[int, dict[str, object]]:
    arguments = [command] if path is None else [command, str(path)]
    exit_code = main(arguments)
    captured = capsys.readouterr()
    assert captured.err == ""
    return exit_code, json.loads(captured.out)


def _assert_case(capsys, case: dict[str, object], generated_snapshot: Path) -> None:
    source = case["file"]
    path = generated_snapshot if source == "$generated_snapshot" else ROOT / str(source)
    exit_code, result = _invoke(capsys, str(case["command"]), path)
    assert exit_code == case["exit_code"], case["command"]
    assert result["code"] == case["result_code"], case["command"]


def test_every_reference_command_has_stable_success_and_failure_codes(tmp_path, capsys):
    snapshot_exit, snapshot_result = _invoke(capsys, "snapshot", ROOT / "tests/vectors/typed-strike.json")
    assert snapshot_exit == 0
    generated_snapshot = tmp_path / "snapshot.json"
    generated_snapshot.write_text(json.dumps(snapshot_result["snapshot"]), encoding="utf-8")

    assert [case["command"] for case in VECTOR["success_cases"]] == VECTOR["commands"]
    assert [case["command"] for case in VECTOR["failure_cases"]] == VECTOR["commands"]
    for case in VECTOR["success_cases"]:
        _assert_case(capsys, case, generated_snapshot)
    for case in VECTOR["failure_cases"]:
        _assert_case(capsys, case, generated_snapshot)


def test_every_reference_command_returns_json_for_argument_errors(capsys):
    expected = VECTOR["argument_error"]
    for command in VECTOR["commands"]:
        exit_code, result = _invoke(capsys, command)
        assert exit_code == expected["exit_code"], command
        assert result["code"] == expected["result_code"], command


def test_reference_command_has_stable_io_error_code(capsys):
    case = VECTOR["io_error"]
    exit_code, result = _invoke(capsys, case["command"], ROOT / case["file"])
    assert exit_code == case["exit_code"]
    assert result["code"] == case["result_code"]
