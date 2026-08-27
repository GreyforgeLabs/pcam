import json
from pathlib import Path

import pytest

from pcam_runtime import EffectEnvelope, reduce_effects
from pcam_runtime.errors import PCAMError

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/effects.json").read_text(encoding="utf-8"))


def _effects(values):
    return tuple(EffectEnvelope(**value) for value in values)


def _json_record(value):
    record = dict(value.__dict__)
    if isinstance(record.get("value"), tuple):
        record["value"] = list(record["value"])
    if isinstance(record.get("source_effect_ids"), tuple):
        record["source_effect_ids"] = list(record["source_effect_ids"])
    return record


def test_python_effect_reduction_matches_all_shared_core_reducers():
    for case in _vectors()["cases"]:
        reduced, rejected = reduce_effects(_effects(case["effects"]))
        assert [_json_record(item) for item in reduced] == case["reduced"], case["id"]
        assert [_json_record(item) for item in rejected] == case["rejected"], case["id"]


def test_python_effect_reduction_matches_shared_faults():
    for case in _vectors()["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            reduce_effects(_effects(case["effects"]))
        assert raised.value.fault.value == case["fault"], case["id"]
