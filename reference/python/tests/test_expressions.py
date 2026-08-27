import pytest

from pcam_runtime import evaluate
from pcam_runtime.errors import PCAMError


def test_core_expression_operators_are_pure_and_exact():
    expression = {
        "op": "and",
        "args": [
            {"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": 10}]},
            {"op": "contains", "args": [{"ref": "owner.tags"}, {"literal": "READY"}]},
        ],
    }
    context = {"action.node_step": 12, "owner.tags": frozenset({"READY", "ARMORED"})}
    assert evaluate(expression, context) is True


def test_expression_division_is_euclidean_and_float_is_rejected():
    assert evaluate({"op": "div", "args": [{"literal": -7}, {"literal": 3}]}, {}) == -3
    assert evaluate({"op": "mod", "args": [{"literal": -7}, {"literal": 3}]}, {}) == 2
    with pytest.raises(PCAMError):
        evaluate({"literal": 1.5}, {})


def test_expression_limits_fault_deterministically():
    expression = {"literal": 1}
    for _ in range(5):
        expression = {"op": "abs", "args": [expression]}
    with pytest.raises(PCAMError) as raised:
        evaluate(expression, {}, max_depth=2)
    assert raised.value.fault.value == "STATE_INVARIANT_FAILURE"
