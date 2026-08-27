"""Pure bounded evaluator for the PCAM v3 core expression language."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .errors import PCAMError, PCAMFault, ResultCode
from .numeric import add_i64, euclidean_divmod, mul_i64, sub_i64

Resolver = Callable[[str], Any]


def evaluate(expression: Any, resolve: Resolver | Mapping[str, Any], max_depth: int = 64, max_nodes: int = 4096) -> Any:
    resolver = resolve.__getitem__ if isinstance(resolve, Mapping) else resolve
    budget = [max_nodes]
    return _evaluate(expression, resolver, 0, max_depth, budget)


def _evaluate(expression: Any, resolve: Resolver, depth: int, max_depth: int, budget: list[int]) -> Any:
    budget[0] -= 1
    if budget[0] < 0 or depth > max_depth:
        raise PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, "expression limit exceeded")
    if not isinstance(expression, dict):
        raise _invalid("expression must be an object")
    if set(expression) == {"literal"}:
        literal = expression["literal"]
        if isinstance(literal, float):
            raise _invalid("floating-point literal is forbidden")
        return literal
    if set(expression) == {"ref"}:
        reference = expression["ref"]
        if not isinstance(reference, str):
            raise _invalid("reference must be a string")
        try:
            return resolve(reference)
        except (KeyError, LookupError) as exc:
            raise _invalid(f"unresolved reference: {reference}") from exc
    if set(expression) != {"op", "args"}:
        raise _invalid("expression must contain exactly literal, ref, or op plus args")
    operator = expression["op"]
    raw_args = expression["args"]
    if not isinstance(operator, str) or not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes)):
        raise _invalid("invalid operator expression")
    args = [_evaluate(item, resolve, depth + 1, max_depth, budget) for item in raw_args]
    return _apply(operator, args)


def _apply(operator: str, args: list[Any]) -> Any:
    if operator == "and":
        return all(_bool(item) for item in args)
    if operator == "or":
        return any(_bool(item) for item in args)
    if operator == "not":
        _arity(operator, args, 1)
        return not _bool(args[0])
    if operator == "xor":
        _arity(operator, args, 2)
        return _bool(args[0]) != _bool(args[1])
    if operator in {"eq", "ne", "lt", "lte", "gt", "gte"}:
        _arity(operator, args, 2)
        operations = {
            "eq": lambda: args[0] == args[1],
            "ne": lambda: args[0] != args[1],
            "lt": lambda: args[0] < args[1],
            "lte": lambda: args[0] <= args[1],
            "gt": lambda: args[0] > args[1],
            "gte": lambda: args[0] >= args[1],
        }
        return operations[operator]()
    if operator in {"add", "sub", "mul", "div", "mod"}:
        _arity(operator, args, 2)
        left, right = _int(args[0]), _int(args[1])
        if operator == "add":
            return add_i64(left, right)
        if operator == "sub":
            return sub_i64(left, right)
        if operator == "mul":
            return mul_i64(left, right)
        quotient, remainder = euclidean_divmod(left, right)
        return quotient if operator == "div" else remainder
    if operator in {"min", "max"}:
        if not args:
            raise _invalid(f"{operator} requires at least one argument")
        values = [_int(item) for item in args]
        return min(values) if operator == "min" else max(values)
    if operator == "clamp":
        _arity(operator, args, 3)
        value, lower, upper = (_int(item) for item in args)
        if lower > upper:
            raise _invalid("clamp lower bound exceeds upper bound")
        return min(max(value, lower), upper)
    if operator == "abs":
        _arity(operator, args, 1)
        value = _int(args[0])
        return sub_i64(0, value) if value < 0 else value
    if operator in {"contains", "intersects", "subset", "union", "difference"}:
        _arity(operator, args, 2)
        if operator == "contains":
            return args[1] in _set(args[0])
        left, right = _set(args[0]), _set(args[1])
        if operator == "intersects":
            return bool(left.intersection(right))
        if operator == "subset":
            return left.issubset(right)
        if operator == "union":
            return frozenset(left.union(right))
        return frozenset(left.difference(right))
    if operator == "if":
        _arity(operator, args, 3)
        return args[1] if _bool(args[0]) else args[2]
    if operator == "coalesce":
        if not args:
            raise _invalid("coalesce requires at least one argument")
        return next((item for item in args if item is not None), None)
    raise _invalid(f"unknown operator: {operator}")


def _arity(operator: str, args: list[Any], count: int) -> None:
    if len(args) != count:
        raise _invalid(f"{operator} requires {count} arguments")


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise _invalid("Boolean operator received a non-Boolean value")
    return value


def _int(value: Any) -> int:
    if type(value) is not int:
        raise _invalid("integer operator received a non-integer value")
    return value


def _set(value: Any) -> frozenset[Any]:
    if not isinstance(value, (set, frozenset, list, tuple)):
        raise _invalid("set operator received a non-set value")
    return frozenset(value)


def _invalid(message: str) -> PCAMError:
    return PCAMError(ResultCode.RUNTIME_FAULT, PCAMFault.STATE_INVARIANT_FAILURE, message)
