import copy
import json
from pathlib import Path

import pytest

from pcam_runtime import (
    LockstepCoordinator,
    RetainedRollbackHistory,
    ServerAuthoritativeCorrectionPlanner,
    run_vector,
)

ROOT = Path(__file__).resolve().parents[3]


def _documents():
    network = json.loads((ROOT / "tests/vectors/network-services.json").read_text())
    runtime = json.loads((ROOT / network["runtime_vector"]).read_text())
    return network, runtime


def _coordinator(network, profile_name="wait_profile"):
    profile = network["lockstep"][profile_name]
    return LockstepCoordinator(
        tuple(network["lockstep"]["required_peers"]),
        network["expected"]["definition_set_hash"],
        profile["input_availability_policy"],
        profile["digest_interval_ticks"],
        profile["desynchronization_policy"],
        profile.get("predictor_id"),
    )


def test_lockstep_waits_merges_canonically_and_exchanges_matching_digests():
    network, runtime = _documents()
    coordinator = _coordinator(network)
    tick = runtime["ticks"][0]
    definition_hash = network["expected"]["definition_set_hash"]
    coordinator.submit("peer.a", 0, definition_hash, tuple(tick["inputs"]), tuple(tick["contacts"]))

    waiting = coordinator.advance()
    assert waiting.status == "WAITING"
    assert waiting.missing_peers == ("peer.b",)
    assert coordinator.next_tick == 0
    with pytest.raises(ValueError, match="definition-set hash mismatch"):
        coordinator.submit(
            "peer.b",
            0,
            network["lockstep"]["bad_definition_set_hash"],
            contacts=tuple(tick["contacts"]),
        )

    coordinator.submit("peer.b", 0, definition_hash, contacts=tuple(tick["contacts"]))
    ready = coordinator.advance()
    assert ready.status == "READY"
    assert ready.tick_document == tick
    assert ready.predicted_peers == ()
    assert ready.digest_due is True

    coordinated = copy.deepcopy(runtime)
    coordinated["ticks"][0] = ready.tick_document
    run = run_vector(coordinated)
    digest = run.traces[0]["state_digest"]
    assert digest == network["expected"]["tick_state_digests"][0]
    assert coordinator.submit_digest("peer.a", 0, digest, digest).status == "WAITING"
    assert coordinator.submit_digest("peer.b", 0, digest, digest).status == "MATCH"


def test_lockstep_prediction_host_mismatch_and_desync_policies_fail_closed():
    network, runtime = _documents()
    definition_hash = network["expected"]["definition_set_hash"]
    predicted = _coordinator(network, "predict_profile")
    predicted.submit("peer.a", 0, definition_hash)
    result = predicted.advance()
    assert result.status == "READY"
    assert result.predicted_peers == ("peer.b",)
    assert result.tick_document == {"inputs": [], "contacts": []}
    assert result.digest_due is False

    mismatch = _coordinator(network)
    mismatch.submit("peer.a", 0, definition_hash, contacts=tuple(runtime["ticks"][0]["contacts"]))
    mismatch.submit("peer.b", 0, definition_hash)
    with pytest.raises(ValueError, match="host snapshot mismatch"):
        mismatch.advance()
    assert mismatch.next_tick == 0

    aborted = _coordinator(network)
    contacts = tuple(runtime["ticks"][0]["contacts"])
    aborted.submit("peer.a", 0, definition_hash, tuple(runtime["ticks"][0]["inputs"]), contacts)
    aborted.submit("peer.b", 0, definition_hash, contacts=contacts)
    ready = aborted.advance()
    digest = network["expected"]["tick_state_digests"][0]
    assert aborted.submit_digest("peer.a", 0, digest, digest).status == "WAITING"
    resolution = aborted.submit_digest(
        "peer.b", 0, network["lockstep"]["bad_state_digest"], digest
    )
    assert resolution.status == "ABORTED"
    assert resolution.mismatched_peers == ("peer.b",)
    assert ready.digest_due is True
    with pytest.raises(ValueError, match="session is aborted"):
        aborted.advance()


def test_server_authoritative_resimulation_and_replace_discard_match_server_state():
    network, runtime = _documents()
    direct = run_vector(runtime)
    initial = direct.executor.restore(direct.initial_snapshot)
    manager = RetainedRollbackHistory(direct.executor, retained_history_ticks=8)
    state = initial
    for tick in range(3):
        inputs = () if tick == 0 else direct.input_history[tick]
        state, _, _ = manager.advance(state, inputs, direct.host_history[tick])
    assert state.state_hash() != direct.final_state.state_hash()

    resimulate = network["server_authoritative"]["resimulate"]
    planner = ServerAuthoritativeCorrectionPlanner(
        resimulate["correction_policy"], resimulate["max_latency_compensation_ticks"]
    )
    plan = planner.plan(state.tick, resimulate["authoritative_tick"], False)
    assert plan.operation == "RESTORE_AND_RESIMULATE"
    correction = manager.correct_and_resimulate(0, direct.input_history[0])
    assert correction.state.state_hash() == network["expected"]["final_state_digest"]
    assert correction.state.to_snapshot() == direct.final_state.to_snapshot()

    authoritative_tick_one, _ = direct.executor.tick(
        initial, direct.input_history[0], direct.host_history[0]
    )
    replace = network["server_authoritative"]["replace_discard"]
    replace_planner = ServerAuthoritativeCorrectionPlanner(
        replace["correction_policy"], replace["max_latency_compensation_ticks"]
    )
    replace_plan = replace_planner.plan(state.tick, replace["authoritative_tick"], True)
    assert replace_plan.operation == "REPLACE_AND_DISCARD"
    assert replace_plan.discard_prediction_ticks == 2
    replaced = direct.executor.restore(direct.executor.save(authoritative_tick_one))
    for tick in (1, 2):
        replaced, _ = direct.executor.tick(
            replaced, direct.input_history[tick], direct.host_history[tick]
        )
    assert replaced.to_snapshot() == direct.final_state.to_snapshot()

    with pytest.raises(ValueError, match="requires complete authoritative state"):
        replace_planner.plan(state.tick, 1, False)
    with pytest.raises(ValueError, match="correction tick is invalid"):
        replace_planner.plan(state.tick, state.tick + 1, True)
    bounded = ServerAuthoritativeCorrectionPlanner(replace["correction_policy"], 1)
    with pytest.raises(ValueError, match="exceeds compensation limit"):
        bounded.plan(state.tick, 1, True)
