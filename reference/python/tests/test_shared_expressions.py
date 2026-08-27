import json
from pathlib import Path

import pytest

from pcam_runtime import PCAMError, canonical_dumps, evaluate

ROOT = Path(__file__).resolve().parents[3]


def test_python_expression_evaluator_matches_shared_vectors():
    vectors = json.loads((ROOT / "tests/vectors/expressions.json").read_text(encoding="utf-8"))
    for case in vectors["cases"]:
        actual = evaluate(case["expression"], case["context"])
        assert canonical_dumps(actual) == canonical_dumps(case["result"]), case["id"]

    for case in vectors["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            evaluate(case["expression"], case["context"])
        assert raised.value.fault.value == case["fault"], case["id"]
