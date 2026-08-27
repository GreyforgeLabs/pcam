import copy

import pytest

from pcam_runtime import (
    ActionDefinition,
    NetworkProfile,
    NodeDefinition,
    PCAMError,
    RuntimeProfile,
    TickExecutor,
    load_document,
    validate_document,
)
from pcam_runtime.schema import repository_root


def test_default_runtime_declares_local_deterministic_profile():
    profile = RuntimeProfile()
    assert profile.network_profiles == (NetworkProfile(),)


def test_networked_profiles_require_mechanism_and_limits():
    with pytest.raises(PCAMError):
        NetworkProfile(id="pcam.rollback.incomplete", topology="ROLLBACK")

    rollback = NetworkProfile(
        id="pcam.rollback.v1",
        topology="ROLLBACK",
        predictor_id="pcam.predict.hold-last",
        snapshot_interval_ticks=2,
        retained_history_ticks=120,
        effect_reconciliation_policy="pcam.effects.stable-id",
        latency_mechanism="pcam.latency.rollback",
        max_latency_compensation_ticks=12,
    )
    assert rollback.retained_history_ticks == 120


def test_runtime_profile_hash_binds_limits_and_network_declarations():
    base = RuntimeProfile()
    changed_limit = RuntimeProfile(max_effects_per_tick=base.max_effects_per_tick + 1)
    changed_expression_limit = RuntimeProfile(max_expression_nodes=base.max_expression_nodes + 1)
    changed_network = RuntimeProfile(
        network_profiles=(
            NetworkProfile(
                id="pcam.lockstep.v1",
                topology="LOCKSTEP",
                input_availability_policy="WAIT",
                digest_interval_ticks=30,
                desynchronization_policy="pcam.desync.abort",
                latency_mechanism="pcam.latency.input-delay",
                max_latency_compensation_ticks=3,
            ),
        )
    )
    assert len(
        {
            base.profile_hash,
            changed_limit.profile_hash,
            changed_expression_limit.profile_hash,
            changed_network.profile_hash,
        }
    ) == 4

    definition = ActionDefinition("PROFILE", 1, 0, (NodeDefinition("RUN"),))
    assert TickExecutor((definition,), base).definition_set_hash != TickExecutor(
        (definition,), changed_network
    ).definition_set_hash


def test_network_profile_hash_uses_canonical_identifier_order():
    local = NetworkProfile()
    lockstep = NetworkProfile(
        id="pcam.lockstep.v1",
        topology="LOCKSTEP",
        input_availability_policy="WAIT",
        digest_interval_ticks=30,
        desynchronization_policy="pcam.desync.abort",
        latency_mechanism="pcam.latency.input-delay",
        max_latency_compensation_ticks=3,
    )
    assert RuntimeProfile(network_profiles=(local, lockstep)).profile_hash == RuntimeProfile(
        network_profiles=(lockstep, local)
    ).profile_hash


def test_runtime_profile_rejects_duplicate_network_identifiers():
    document = load_document(repository_root() / "tests/valid/minimal-runtime-profile.json")
    duplicate = copy.deepcopy(document["network_profiles"][0])
    document["network_profiles"].append(duplicate)
    diagnostics = validate_document(document)
    assert diagnostics[0].fault == "DUPLICATE_IDENTIFIER"
