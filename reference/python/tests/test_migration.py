import json
from pathlib import Path

import pytest

from pcam_runtime import PCAMError, canonical_dumps, load_document, migrate_legacy, validate_document
from pcam_runtime.cli import main

ROOT = Path(__file__).resolve().parents[3]


def test_v1_migration_produces_valid_review_only_pcam24():
    source = load_document(ROOT / "tests/legacy/v1-basic.json")
    result = migrate_legacy(source)
    assert result.source_version == "1"
    assert result.definition["lifecycle"] == "LOOP"
    assert result.definition["rate"] == {"scale": 5, "units_per_tick": 2}
    assert result.definition["metadata"]["wire_compatible"] is False
    assert validate_document(result.definition) == []
    assert [warning.code for warning in result.warnings] == ["MANUAL_REVIEW_REQUIRED"]


def test_v2_migration_emits_complete_deterministic_warning_report():
    source = load_document(ROOT / "tests/legacy/v2-overlap-floating.json")
    first = migrate_legacy(source)
    second = migrate_legacy(source)
    codes = [warning.code for warning in first.warnings]
    assert codes == [
        "FLOATING_TIMING_REVIEW",
        "MANUAL_REVIEW_REQUIRED",
        "MISSING_CYCLE_IDENTITY",
        "MISSING_DETERMINISTIC_LIMITS",
        "MISSING_HIT_POLICY",
        "MISSING_STALL_STATE",
        "OVERLAPPING_OR_CONTRADICTORY_WINDOWS",
        "PHASE_ONLY_NETWORKING_REVIEW",
        "UNDEFINED_NESTING_RETURN",
        "UNDEFINED_SKIP_EFFECTS",
        "UNIVERSAL_PRECEDENCE_ASSUMPTION_REVIEW",
        "UNSUPPORTED_LIFECYCLE_DEFAULTED",
    ]
    assert first.definition["rate"] == {"scale": 1, "units_per_tick": 1}
    assert first.definition["lifecycle"] == "TERMINATE"
    assert canonical_dumps(first) == canonical_dumps(second)
    assert validate_document(first.definition) == []


def test_migration_rejects_missing_current_and_unknown_versions():
    with pytest.raises(PCAMError) as raised:
        migrate_legacy(load_document(ROOT / "tests/legacy/unsupported-v3.json"))
    assert raised.value.fault.value == "UNSUPPORTED_LEGACY_VERSION"

    with pytest.raises(PCAMError):
        migrate_legacy({"pcam_version": {}, "id": "greyforge.legacy.invalid", "phases": {}})


def test_migrate_v2_cli_returns_stable_machine_readable_report(capsys):
    path = ROOT / "tests/legacy/v2-overlap-floating.json"
    code = main(["migrate-v2", str(path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["code"] == "OK"
    assert payload["source_version"] == "2"
    assert payload["definition"]["metadata"]["manual_review_required"] is True
    assert payload["source_evidence_hash"] == payload["definition"]["metadata"]["source_evidence_hash"]
    assert payload["warnings"][-1]["code"] == "UNSUPPORTED_LIFECYCLE_DEFAULTED"


def test_v3_validator_does_not_silently_interpret_legacy_document():
    legacy = load_document(ROOT / "tests/legacy/v1-basic.json")
    diagnostics = validate_document(legacy)
    assert diagnostics
    assert diagnostics[0].code == "SCHEMA_VALIDATION_FAILED"
