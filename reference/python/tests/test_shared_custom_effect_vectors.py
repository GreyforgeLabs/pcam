import json
from pathlib import Path

import pytest

from pcam_runtime import (
    CustomEffectRegistration,
    CustomEffectRegistry,
    EffectEnvelope,
    PCAMError,
    canonical_hash,
    reduce_effects,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR_HASH = "cd14a75292221115aa6b05fe3a5331d9cb81a79f42a845e9365edbff6da9332d"


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/custom-effect-ordered-fold.json").read_text(
            encoding="utf-8"
        )
    )


def _registration(vector):
    source = (ROOT / vector["implementation_path"]).read_bytes()
    return CustomEffectRegistration(
        effect_type=vector["effect_type"],
        implementation_id="greyforge.effect.ordered-i64-fold.v1",
        implementation_hash=vector["implementation_sha256"],
        payload_schema=vector["payload_schema"],
        determinism_vectors=(VECTOR_HASH,),
        implementation_source=source,
    )


def _effects(values):
    return tuple(EffectEnvelope(**value) for value in values)


def test_python_custom_effect_is_hash_bound_ordered_and_permutation_invariant():
    vector = _vector()
    assert canonical_hash(vector) == VECTOR_HASH
    registry = CustomEffectRegistry((_registration(vector),))
    expected = vector["expected"]
    for permutation in vector["permutations"]:
        reduced, rejected = reduce_effects(_effects(permutation), registry)
        assert rejected == ()
        assert reduced[0].__dict__ == {
            **expected,
            "source_effect_ids": tuple(expected["source_effect_ids"]),
        }


def test_python_custom_effect_payload_overflow_and_registration_fail_closed():
    vector = _vector()
    registry = CustomEffectRegistry((_registration(vector),))
    for case in vector["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            reduce_effects(_effects(case["effects"]), registry)
        assert raised.value.fault.value == case["fault"], case["id"]

    with pytest.raises(PCAMError):
        CustomEffectRegistration(
            effect_type=vector["effect_type"],
            implementation_id="greyforge.effect.ordered-i64-fold.v1",
            implementation_hash="0" * 64,
            payload_schema=vector["payload_schema"],
            determinism_vectors=(VECTOR_HASH,),
        )

    with pytest.raises(PCAMError):
        CustomEffectRegistration(
            effect_type=vector["effect_type"],
            implementation_id="greyforge.effect.ordered-i64-fold.v1",
            implementation_hash=vector["implementation_sha256"],
            payload_schema=vector["payload_schema"],
            determinism_vectors=(VECTOR_HASH,),
            implementation_source=b"tampered",
        )

    with pytest.raises(PCAMError):
        CustomEffectRegistration(
            effect_type=vector["effect_type"],
            implementation_id="greyforge.effect.ordered-i64-fold.v1",
            implementation_hash=vector["implementation_sha256"],
            payload_schema=vector["payload_schema"],
            determinism_vectors=(VECTOR_HASH,),
        )
