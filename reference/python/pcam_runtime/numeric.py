"""Exact bounded integer and ratio semantics for PCAM Core."""

from __future__ import annotations

from enum import Enum

from .errors import PCAMError, PCAMFault, ResultCode

I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
U64_MIN = 0
U64_MAX = (1 << 64) - 1


class OverflowPolicy(str, Enum):
    FAULT = "FAULT"
    SATURATE = "SATURATE"
    WRAP = "WRAP"


def apply_i64(value: int, policy: OverflowPolicy = OverflowPolicy.FAULT) -> int:
    if I64_MIN <= value <= I64_MAX:
        return value
    if policy == OverflowPolicy.SATURATE:
        return min(max(value, I64_MIN), I64_MAX)
    if policy == OverflowPolicy.WRAP:
        unsigned = value & U64_MAX
        return unsigned if unsigned <= I64_MAX else unsigned - (1 << 64)
    raise _overflow(value, "I64")


def apply_u64(value: int, policy: OverflowPolicy = OverflowPolicy.FAULT) -> int:
    if U64_MIN <= value <= U64_MAX:
        return value
    if policy == OverflowPolicy.SATURATE:
        return min(max(value, U64_MIN), U64_MAX)
    if policy == OverflowPolicy.WRAP:
        return value & U64_MAX
    raise _overflow(value, "U64")


def add_i64(left: int, right: int, policy: OverflowPolicy = OverflowPolicy.FAULT) -> int:
    return apply_i64(left + right, policy)


def sub_i64(left: int, right: int, policy: OverflowPolicy = OverflowPolicy.FAULT) -> int:
    return apply_i64(left - right, policy)


def mul_i64(left: int, right: int, policy: OverflowPolicy = OverflowPolicy.FAULT) -> int:
    return apply_i64(left * right, policy)


def euclidean_divmod(dividend: int, divisor: int) -> tuple[int, int]:
    if divisor == 0:
        raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.DIVISION_BY_ZERO, "integer divisor is zero")
    if divisor < 0:
        raise PCAMError(
            ResultCode.RUNTIME_FAULT,
            PCAMFault.STATE_INVARIANT_FAILURE,
            "PCAM Core Euclidean division requires a positive divisor",
        )
    quotient, remainder = divmod(dividend, divisor)
    return apply_i64(quotient), apply_i64(remainder)


def scale_ratio(value: int, numerator: int, denominator: int) -> int:
    """Scale with deterministic floor rounding and checked I64 intermediates."""

    if denominator <= 0:
        fault = PCAMFault.DIVISION_BY_ZERO if denominator == 0 else PCAMFault.STATE_INVARIANT_FAILURE
        raise PCAMError(ResultCode.RUNTIME_FAULT, fault, "ratio denominator must be positive")
    product = mul_i64(value, numerator)
    quotient, _ = euclidean_divmod(product, denominator)
    return quotient


def _overflow(value: int, type_name: str) -> PCAMError:
    return PCAMError(
        ResultCode.RUNTIME_FAULT,
        PCAMFault.INTEGER_OVERFLOW,
        f"{value} is outside {type_name}",
    )
