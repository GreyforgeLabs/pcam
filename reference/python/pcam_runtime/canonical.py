"""PCAM-CJ1 canonical JSON and SHA-256 helpers."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .errors import PCAMError, PCAMFault, ResultCode

I64_MIN = -(1 << 63)
U64_MAX = (1 << 64) - 1


def canonical_dumps(value: Any) -> bytes:
    """Encode a value with the PCAM-CJ1 JSON profile.

    Supported values are dataclasses, mappings, sets, sequences, strings,
    bounded PCAM integers, booleans, and null. Floats are rejected.
    """

    try:
        return _encode(_normalize(value)).encode("utf-8")
    except PCAMError:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapping
        raise PCAMError(
            ResultCode.CANONICALIZATION_FAILURE,
            PCAMFault.CANONICALIZATION_FAILURE,
            str(exc),
        ) from exc


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value)).hexdigest()


def canonicalize_json(source: str | bytes) -> bytes:
    """Parse UTF-8 JSON without losing PCAM-CJ1 rejection information."""

    try:
        if isinstance(source, bytes):
            if source.startswith(b"\xef\xbb\xbf"):
                raise _failure("UTF-8 BOM is not canonical JSON input")
            text = source.decode("utf-8")
        else:
            text = source
            if text.startswith("\ufeff"):
                raise _failure("UTF-8 BOM is not canonical JSON input")
        value = json.loads(
            text,
            parse_int=_parse_json_integer,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
        return canonical_dumps(value)
    except PCAMError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _failure(f"invalid UTF-8 JSON: {exc}") from exc


def canonical_hash_json(source: str | bytes) -> str:
    return hashlib.sha256(canonicalize_json(source)).hexdigest()


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        if value < I64_MIN or value > U64_MAX:
            raise _failure("integer is outside the PCAM I64/U64 domain")
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            detail = "non-finite float"
        else:
            detail = "floating-point literal"
        raise PCAMError(
            ResultCode.CANONICALIZATION_FAILURE,
            PCAMFault.CANONICALIZATION_FAILURE,
            f"PCAM-CJ1 forbids {detail}",
        )
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            pairs = [[_normalize(key), _normalize(item)] for key, item in value.items()]
            keyed = [(canonical_dumps(pair[0]), pair) for pair in pairs]
            keyed.sort(key=lambda item: item[0])
            if any(left[0] == right[0] for left, right in zip(keyed, keyed[1:])):
                raise _failure("logical map keys collide after canonical normalization")
            return [pair for _, pair in keyed]
        out: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in out:
                raise PCAMError(
                    ResultCode.CANONICALIZATION_FAILURE,
                    PCAMFault.CANONICALIZATION_FAILURE,
                    "object keys collide after Unicode NFC normalization",
                )
            out[normalized_key] = _normalize(item)
        return out
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize(item) for item in value]
        keyed = [(canonical_dumps(item), item) for item in normalized]
        keyed.sort(key=lambda item: item[0])
        if any(left[0] == right[0] for left, right in zip(keyed, keyed[1:])):
            raise _failure("set entries collide after canonical normalization")
        return [item for _, item in keyed]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize(item) for item in value]
    raise PCAMError(
        ResultCode.CANONICALIZATION_FAILURE,
        PCAMFault.CANONICALIZATION_FAILURE,
        f"unsupported canonical value type: {type(value).__name__}",
    )


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda item: item.encode("utf-8"))
        return "{" + ",".join(_encode_string(key) + ":" + _encode(value[key]) for key in keys) + "}"
    raise TypeError(type(value).__name__)


def _encode_string(value: str) -> str:
    chunks = ['"']
    for char in value:
        codepoint = ord(char)
        if char == '"':
            chunks.append('\\"')
        elif char == "\\":
            chunks.append("\\\\")
        elif char == "\b":
            chunks.append("\\b")
        elif char == "\f":
            chunks.append("\\f")
        elif char == "\n":
            chunks.append("\\n")
        elif char == "\r":
            chunks.append("\\r")
        elif char == "\t":
            chunks.append("\\t")
        elif codepoint < 0x20:
            chunks.append(f"\\u{codepoint:04x}")
        else:
            chunks.append(char)
    chunks.append('"')
    return "".join(chunks)


def _failure(detail: str) -> PCAMError:
    return PCAMError(
        ResultCode.CANONICALIZATION_FAILURE,
        PCAMFault.CANONICALIZATION_FAILURE,
        detail,
    )


def _parse_json_integer(raw: str) -> int:
    if raw == "-0":
        raise _failure("PCAM-CJ1 forbids negative zero")
    return int(raw)


def _reject_json_float(raw: str) -> None:
    raise _failure(f"PCAM-CJ1 forbids floating-point literal: {raw}")


def _reject_json_constant(raw: str) -> None:
    raise _failure(f"PCAM-CJ1 forbids non-JSON numeric constant: {raw}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized_keys: set[str] = set()
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        if normalized in normalized_keys:
            raise _failure("object keys collide after Unicode NFC normalization")
        normalized_keys.add(normalized)
        result[key] = value
    return result
