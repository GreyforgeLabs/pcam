import copy
from dataclasses import replace

import pytest

from pcam_runtime import (
    ActionDefinition,
    ExtensionRegistration,
    ExtensionRegistry,
    NetworkProfile,
    NodeDefinition,
    PCAMError,
    RuntimeProfile,
    TickExecutor,
    load_document,
    validate_document,
)
from pcam_runtime.schema import repository_root

VECTOR_HASH = "0" * 64


def registration(implementation_hash: str = "1" * 64) -> ExtensionRegistration:
    return ExtensionRegistration(
        namespace="tech.greyforge.pcam.test",
        implementation_id="greyforge.extension.test.v1",
        implementation_hash=implementation_hash,
        authoritative=True,
        schema_id="https://schemas.greyforge.tech/pcam/extensions/test-v1.json",
        payload_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        },
        determinism_vectors=(VECTOR_HASH,),
    )


def declaration(item: ExtensionRegistration) -> dict[str, object]:
    return {
        "requirement": "REQUIRED",
        "authoritative": True,
        "schema_id": item.schema_id,
        "canonical_encoding": item.canonical_encoding,
        "validation_id": item.validation_id,
        "runtime_semantics_id": item.runtime_semantics_id,
        "ordering_id": item.ordering_id,
        "fault_behavior_id": item.fault_behavior_id,
        "snapshot_schema_id": item.snapshot_schema_id,
        "rollback_behavior_id": item.rollback_behavior_id,
        "determinism_vectors": [VECTOR_HASH],
        "payload": {"value": 7},
    }


def test_unknown_required_extension_is_rejected_and_safe_optional_is_ignored():
    registry = ExtensionRegistry()
    with pytest.raises(PCAMError) as raised:
        registry.validate(
            {
                "tech.greyforge.pcam.missing": {
                    "requirement": "REQUIRED",
                    "authoritative": False,
                    "payload": {},
                }
            },
            4096,
        )
    assert raised.value.fault.value == "UNKNOWN_REQUIRED_EXTENSION"

    result = registry.validate(
        {
            "tech.greyforge.pcam.visual": {
                "requirement": "OPTIONAL",
                "authoritative": False,
                "omission_preserves_authority": True,
                "payload": {"color": "blue"},
            }
        },
        4096,
    )
    assert result.ignored == ("tech.greyforge.pcam.visual",)


def test_authoritative_extension_contract_and_payload_are_validated():
    item = registration()
    registry = ExtensionRegistry((item,))
    accepted = registry.validate({item.namespace: declaration(item)}, 4096)
    assert accepted.accepted == (item.namespace,)

    invalid = declaration(item)
    invalid["payload"] = {"value": -1}
    with pytest.raises(PCAMError) as raised:
        registry.validate({item.namespace: invalid}, 4096)
    assert raised.value.fault.value == "INVALID_EXTENSION"


def test_extension_registry_identity_is_order_invariant_and_binds_runtime_hash():
    first = registration("1" * 64)
    second = ExtensionRegistration(
        namespace="org.example.pcam.cosmetic",
        implementation_id="example.extension.cosmetic.v1",
        implementation_hash="2" * 64,
        authoritative=False,
        schema_id="https://example.org/pcam/cosmetic-v1.json",
        payload_schema={"type": "object"},
    )
    forward = ExtensionRegistry((first, second))
    reverse = ExtensionRegistry((second, first))
    assert forward.identity_hash == reverse.identity_hash

    definition = ActionDefinition("EXTENSION_HASH", 1, 0, (NodeDefinition("RUN"),))
    base_hash = TickExecutor((definition,)).definition_set_hash
    registered_hash = TickExecutor((definition,), extension_registry=forward).definition_set_hash
    assert base_hash != registered_hash


def test_extension_snapshot_state_is_bounded_on_restore():
    profile = RuntimeProfile(
        max_extension_state_bytes=64,
        network_profiles=(NetworkProfile(),),
    )
    executor = TickExecutor((ActionDefinition("EXTENSION_STATE", 1, 0, (NodeDefinition("RUN"),)),), profile)
    state = replace(executor.initial_state(), extension_state={"tech.greyforge.pcam.test": "x" * 128})
    with pytest.raises(PCAMError) as raised:
        executor.restore(state.to_snapshot())
    assert raised.value.fault.value == "EXTENSION_LIMIT_EXCEEDED"


def test_extension_schema_enforces_optional_omission_and_authoritative_contract():
    path = repository_root() / "tests/valid/minimal-action.json"
    document = load_document(path)
    optional = copy.deepcopy(document)
    optional["extensions"] = {
        "tech.greyforge.pcam.visual": {
            "requirement": "OPTIONAL",
            "authoritative": False,
            "omission_preserves_authority": True,
            "payload": {},
        }
    }
    assert validate_document(optional) == []

    unsafe = copy.deepcopy(optional)
    unsafe["extensions"]["tech.greyforge.pcam.visual"]["omission_preserves_authority"] = False
    assert validate_document(unsafe)[0].code == "SCHEMA_VALIDATION_FAILED"

    item = registration()
    authoritative = copy.deepcopy(document)
    authoritative["extensions"] = {item.namespace: declaration(item)}
    assert validate_document(authoritative) == []
