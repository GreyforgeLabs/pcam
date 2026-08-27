import pytest

from pcam_runtime import OverflowPolicy, apply_i64, apply_u64, euclidean_divmod, scale_ratio
from pcam_runtime.errors import PCAMError
from pcam_runtime.numeric import I64_MAX, I64_MIN, U64_MAX


def test_overflow_policies_are_explicit_and_deterministic():
    with pytest.raises(PCAMError):
        apply_i64(I64_MAX + 1)
    assert apply_i64(I64_MAX + 1, OverflowPolicy.SATURATE) == I64_MAX
    assert apply_i64(I64_MAX + 1, OverflowPolicy.WRAP) == I64_MIN
    assert apply_u64(U64_MAX + 1, OverflowPolicy.WRAP) == 0


def test_euclidean_division_with_positive_divisor():
    assert euclidean_divmod(-7, 3) == (-3, 2)
    assert euclidean_divmod(7, 3) == (2, 1)
    with pytest.raises(PCAMError):
        euclidean_divmod(7, 0)


def test_ratio_scaling_uses_exact_checked_floor_semantics():
    assert scale_ratio(25, 1, 2) == 12
    assert scale_ratio(-25, 1, 2) == -13
