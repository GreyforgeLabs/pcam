import hashlib

import pytest

from pcam_runtime import PCAMError, canonical_dumps, canonical_hash


def test_pcam_cj1_sorts_keys_normalizes_strings_and_hashes_bytes():
    decomposed = "e\u0301"
    encoded = canonical_dumps({"z": 1, "a": decomposed, "nested": {"b": True, "a": None}})
    assert encoded == b'{"a":"\xc3\xa9","nested":{"a":null,"b":true},"z":1}'
    assert canonical_hash({"b": 2, "a": 1}) == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()


def test_pcam_cj1_rejects_float_literals():
    with pytest.raises(PCAMError) as raised:
        canonical_dumps({"bad": 1.25})
    assert raised.value.fault.value == "CANONICALIZATION_FAILURE"


def test_pcam_cj1_encodes_non_string_logical_maps_as_sorted_pairs():
    assert canonical_dumps({2: "b", 1: "a"}) == b'[[1,"a"],[2,"b"]]'


def test_pcam_cj1_rejects_object_key_collision_after_nfc():
    with pytest.raises(PCAMError) as raised:
        canonical_dumps({"e\u0301": 1, "\u00e9": 2})
    assert "collide" in raised.value.message
