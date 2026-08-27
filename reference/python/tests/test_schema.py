from pathlib import Path

from pcam_runtime.schema import load_document, validate_document

ROOT = Path(__file__).resolve().parents[3]


def test_positive_schema_vectors_validate():
    for path in sorted((ROOT / "tests" / "valid").glob("*.json")):
        assert validate_document(load_document(path)) == [], path


def test_negative_schema_vectors_are_rejected_with_stable_faults():
    version = validate_document(load_document(ROOT / "tests" / "invalid" / "action-wrong-version.json"))
    assert version[0].code == "SCHEMA_VALIDATION_FAILED"

    wrapping = validate_document(load_document(ROOT / "tests" / "invalid" / "pcam24-wrapping-range.json"))
    assert wrapping[0].fault == "INVALID_PROFILE_RANGE"
