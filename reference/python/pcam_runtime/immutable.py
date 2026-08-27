"""Recursive immutable containers for hash-bound definition data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FrozenDict(dict):
    """A dict-compatible mapping that rejects every in-place mutation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("hash-bound definition data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        del memo
        return self


class FrozenList(list):
    """A list-compatible sequence that rejects every in-place mutation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("hash-bound definition data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __copy__(self) -> FrozenList:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenList:
        del memo
        return self


def freeze_value(value: Any) -> Any:
    """Deep-capture JSON-like data without changing dict/list type checks."""

    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, Mapping):
        return FrozenDict((key, freeze_value(item)) for key, item in value.items())
    if isinstance(value, list):
        return FrozenList(freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(item) for item in value)
    return value
