import json
from pathlib import Path

import pytest

from pcam_runtime import OverflowPolicy, PCAMError, PCG32Stream, apply_i64, apply_u64, euclidean_divmod, scale_ratio

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/numeric-rng.json").read_text(encoding="utf-8"))


def test_python_numeric_semantics_match_shared_vectors():
    vectors = _vectors()
    operations = {"I64": apply_i64, "U64": apply_u64}
    for case in vectors["overflow_cases"]:
        operation = operations[case["domain"]]
        if "fault" in case:
            with pytest.raises(PCAMError) as raised:
                operation(int(case["input"]), OverflowPolicy(case["policy"]))
            assert raised.value.fault.value == case["fault"], case["id"]
        else:
            assert operation(int(case["input"]), OverflowPolicy(case["policy"])) == case["result"], case["id"]

    for case in vectors["division_cases"]:
        if "fault" in case:
            with pytest.raises(PCAMError) as raised:
                euclidean_divmod(case["dividend"], case["divisor"])
            assert raised.value.fault.value == case["fault"], case["id"]
        else:
            assert euclidean_divmod(case["dividend"], case["divisor"]) == (
                case["quotient"],
                case["remainder"],
            )

    for case in vectors["ratio_cases"]:
        if "fault" in case:
            with pytest.raises(PCAMError) as raised:
                scale_ratio(case["value"], case["numerator"], case["denominator"])
            assert raised.value.fault.value == case["fault"], case["id"]
        else:
            assert scale_ratio(case["value"], case["numerator"], case["denominator"]) == case["result"]


def test_python_pcg32_matches_shared_outputs_and_restore_state():
    vector = _vectors()["pcg32"]
    stream = PCG32Stream.seeded(vector["seed"], vector["stream_selector"])
    values = []
    for _ in vector["values"]:
        stream, value = stream.draw_u32()
        values.append(value)
    assert values == vector["values"]
    assert stream.to_snapshot() == vector["snapshot"]

    restored = PCG32Stream.from_snapshot(vector["snapshot"])
    restored, value = restored.draw_u32()
    assert value == vector["next_value"]
    assert restored.state == vector["next_state"]
    assert restored.draw_count == 6


def test_python_pcg32_rejects_profile_mismatch_and_draw_count_overflow():
    with pytest.raises(ValueError):
        PCG32Stream.from_snapshot(
            {"algorithm_id": "pcam.unknown", "draw_count": 0, "state": 1, "stream_selector": 1}
        )

    exhausted = PCG32Stream(state=1, stream_selector=1, draw_count=(1 << 64) - 1)
    with pytest.raises(PCAMError) as raised:
        exhausted.draw_u32()
    assert raised.value.fault.value == "INTEGER_OVERFLOW"
