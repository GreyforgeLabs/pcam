import json
from pathlib import Path

import pytest

from pcam_runtime import (
    PCAMError,
    canonical_dumps,
    canonical_hash,
    canonical_hash_json,
    canonicalize_json,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR = ROOT / "tests/vectors/pcam-cj1-hostile.json"


def _vector():
    return json.loads(VECTOR.read_text(encoding="utf-8"))


def _source(case):
    if "source_hex" in case:
        return bytes.fromhex(case["source_hex"])
    return case["source"].encode("utf-8")


def _assert_error(case, raised):
    detail = raised.value.message.lower()
    expected = case["error"]
    if expected == "NEGATIVE_ZERO":
        assert "negative zero" in detail
    elif expected == "FLOATING_POINT":
        assert "floating-point" in detail
    elif expected == "INTEGER_DOMAIN":
        assert "i64/u64 domain" in detail
    elif expected == "KEY_COLLISION":
        assert "collide" in detail
    elif expected == "SET_COLLISION":
        assert "set entries collide" in detail
    elif expected == "LOGICAL_KEY_COLLISION":
        assert "logical map keys collide" in detail


def test_hostile_corpus_names_evidence_for_every_pcam_cj1_rule():
    vector = _vector()
    coverage = vector["rule_coverage"]
    assert set(coverage) == {str(number) for number in range(1, 19)}
    assert all(case_ids for case_ids in coverage.values())
    assert all((ROOT / path).is_file() for path in vector["external_evidence"].values())


def test_python_matches_hostile_exact_value_vectors():
    for case in _vector()["value_cases"]:
        assert canonical_dumps(case["input"]).decode("utf-8") == case["canonical"], case["id"]
        assert canonical_hash(case["input"]) == case["sha256"], case["id"]


def test_python_raw_json_preserves_rejection_information_and_exact_bytes():
    for case in _vector()["raw_json_cases"]:
        source = _source(case)
        if case["outcome"] == "OK":
            assert canonicalize_json(source).decode("utf-8") == case["canonical"], case["id"]
            assert canonical_hash_json(source) == case["sha256"], case["id"]
        else:
            with pytest.raises(PCAMError) as raised:
                canonicalize_json(source)
            _assert_error(case, raised)


def test_python_native_sets_sort_canonically_and_reject_normalized_collisions():
    for case in _vector()["set_cases"]:
        value = set(case["items"])
        if case["outcome"] == "OK":
            assert canonical_dumps(value).decode("utf-8") == case["canonical"], case["id"]
            assert canonical_hash(value) == case["sha256"], case["id"]
        else:
            with pytest.raises(PCAMError) as raised:
                canonical_dumps(value)
            _assert_error(case, raised)


def test_python_non_string_logical_maps_sort_and_reject_key_collisions():
    for case in _vector()["logical_map_cases"]:
        value = dict((entry[0], entry[1]) for entry in case["entries"])
        if case["outcome"] == "OK":
            assert canonical_dumps(value).decode("utf-8") == case["canonical"], case["id"]
            assert canonical_hash(value) == case["sha256"], case["id"]
        else:
            with pytest.raises(PCAMError) as raised:
                canonical_dumps(value)
            _assert_error(case, raised)
