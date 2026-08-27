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
    RetainedRollbackHistory,
    RuntimeProfile,
    TickExecutor,
    canonical_hash,
    load_document,
    validate_document,
)
from pcam_runtime.schema import repository_root

VECTOR_HASH = "0" * 64
COUNTER_VECTOR_HASH = "e0342685389e4f101c0b24300ee918077b675ed53c71c406542aaa88b969ec7f"
COUNTER_SOURCE_HASH = "99c887cedffd0575b1994942752843c5cb2ffacfecf08873aec684288395535f"
COUNTER_SOURCE = repository_root() / "reference/extensions/tick-counter-v1.json"


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
        "determinism_vectors": list(item.determinism_vectors),
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


def test_verified_tick_counter_executes_snapshots_and_rolls_back_end_to_end():
    source = COUNTER_SOURCE.read_bytes()
    item = ExtensionRegistration(
        namespace="tech.greyforge.pcam.tick-counter",
        implementation_id="greyforge.extension.tick_counter.v1",
        implementation_hash=COUNTER_SOURCE_HASH,
        authoritative=True,
        schema_id="https://schemas.greyforge.tech/pcam/extensions/tick-counter-v1.json",
        payload_schema={
            "type": "object",
            "required": ["increment"],
            "properties": {"increment": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        },
        runtime_semantics_id="pcam.runtime.tick-start-counter.v1",
        ordering_id="pcam.order.tick-start-counter.v1",
        determinism_vectors=(COUNTER_VECTOR_HASH,),
        runtime_hook="TICK_START_COUNTER",
        implementation_source=source,
    )
    vector = load_document(repository_root() / "tests/vectors/extension-tick-counter.json")
    assert canonical_hash(vector) == COUNTER_VECTOR_HASH
    extension = declaration(item)
    extension["payload"] = vector["payload"]
    profile = RuntimeProfile(extensions={item.namespace: extension})
    executor = TickExecutor((), profile, extension_registry=ExtensionRegistry((item,)))
    history = RetainedRollbackHistory(executor, retained_history_ticks=4)
    state = executor.initial_state()
    counters = []
    for _ in range(vector["ticks"]):
        state, trace, _ = history.advance(state)
        counters.append(state.extension_state[item.namespace]["counter"])
        assert trace["state_changes"]["extension_state"] == state.extension_state
    assert counters == vector["expected_counters"]

    restored = executor.restore(history.frames[1].snapshot)
    restored, _ = executor.tick(restored)
    restored, _ = executor.tick(restored)
    assert restored.extension_state[item.namespace]["counter"] == vector["rollback"][
        "expected_counter_after_two_ticks"
    ]
    correction = history.correct_and_resimulate(1, ())
    assert correction.state.state_hash() == state.state_hash()


def test_executable_extension_source_hash_mismatch_fails_closed():
    with pytest.raises(PCAMError) as raised:
        ExtensionRegistration(
            namespace="tech.greyforge.pcam.tick-counter",
            implementation_id="greyforge.extension.tick_counter.v1",
            implementation_hash=COUNTER_SOURCE_HASH,
            authoritative=True,
            schema_id="https://schemas.greyforge.tech/pcam/extensions/tick-counter-v1.json",
            payload_schema={"type": "object"},
            determinism_vectors=(COUNTER_VECTOR_HASH,),
            runtime_hook="TICK_START_COUNTER",
            implementation_source=b"tampered",
        )
    assert raised.value.fault.value == "INVALID_EXTENSION"


def test_extension_payload_depth_and_encoded_size_fail_before_execution():
    nested: object = 1
    for _ in range(70):
        nested = {"next": nested}
    hostile = {
        "tech.greyforge.pcam.hostile": {
            "requirement": "OPTIONAL",
            "authoritative": False,
            "omission_preserves_authority": True,
            "payload": nested,
        }
    }
    with pytest.raises(PCAMError) as depth_error:
        ExtensionRegistry().validate(hostile, 1_048_576)
    assert depth_error.value.fault.value == "EXTENSION_LIMIT_EXCEEDED"

    oversized = copy.deepcopy(hostile)
    oversized["tech.greyforge.pcam.hostile"]["payload"] = "x" * 128
    with pytest.raises(PCAMError) as size_error:
        ExtensionRegistry().validate(oversized, 64)
    assert size_error.value.fault.value == "EXTENSION_LIMIT_EXCEEDED"
