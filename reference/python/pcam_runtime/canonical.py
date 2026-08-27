"""PCAM-CJ1 canonical JSON and SHA-256 helpers."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .errors import PCAMError, PCAMFault, ResultCode


def canonical_dumps(value: Any) -> bytes:
    """Encode a value with the PCAM-CJ1 JSON profile.

    Supported values are dataclasses, mappings with string keys, sequences,
    strings, integers, booleans, and null. Floats and non-string mapping keys
    are rejected in this slice.
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
            return sorted(pairs, key=lambda pair: canonical_dumps(pair[0]))
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
        return sorted(normalized, key=canonical_dumps)
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
