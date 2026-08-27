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


def test_reserved_cli_surface_fails_explicitly(capsys):
    code = main(["run", str(ROOT / "tests" / "valid" / "minimal-action.json")])
    result = json.loads(capsys.readouterr().out)
    assert code == 3
    assert result["code"] == "NOT_IMPLEMENTED"
