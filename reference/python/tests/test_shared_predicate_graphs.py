import json
from pathlib import Path

import pytest

from pcam_runtime import (
    ActionDefinition,
    NodeDefinition,
    PCAMError,
    PredicateDefinition,
    RuntimeProfile,
    TickExecutor,
    TickInput,
    TransitionDefinition,
)

ROOT = Path(__file__).resolve().parents[3]
VECTOR = json.loads((ROOT / "tests/vectors/predicate-graphs.json").read_text())


def _profile():
    limits = VECTOR["limits"]
    return RuntimeProfile(
        max_expression_depth=limits["max_expression_depth"],
        max_expression_nodes=limits["max_expression_nodes"],
    )


def _definition(predicates, *, identifier="PREDICATES", loop=False):
    transitions = ()
    nodes = (NodeDefinition("A"),)
    units = 0
    if loop:
        nodes = (NodeDefinition("A", "TIMED", 2, True),)
        units = 1
        transitions = (
            TransitionDefinition(
                "LOOP",
                "A",
                "AFTER_QUANTUM",
                1,
                target_node="A",
                target_step=0,
                guard_expression={
                    "op": "gte",
                    "args": [{"ref": "action.node_step"}, {"literal": 2}],
                },
                consume_policy="NEVER",
                cycle_delta=1,
            ),
        )
    return ActionDefinition(identifier, 1, units, nodes, tuple(predicates), transitions=transitions)


def _chain(length):
    predicates = [PredicateDefinition(f"P{length - 1:03}", expression={"literal": True})]
    for index in reversed(range(length - 1)):
        predicates.append(
            PredicateDefinition(
                f"P{index:03}",
                expression={"ref": f"action.predicate.P{index + 1:03}"},
            )
        )
    return predicates


def _start(definition_id):
    return TickInput("start", 1, 0, "START", 0, action_definition_id=definition_id)


def test_python_predicate_graph_depth_and_node_budgets_are_profile_bound():
    for length in VECTOR["accepted_chain_lengths"]:
        definition = _definition(_chain(length), identifier=f"CHAIN_OK_{length}")
        executor = TickExecutor((definition,), _profile())
        state, _ = executor.tick(executor.initial_state(), (_start(definition.id),))
        assert all(state.action_instances["1"].predicate_truth_state.values())

    for length in VECTOR["rejected_chain_lengths"]:
        with pytest.raises(PCAMError) as captured:
            TickExecutor((_definition(_chain(length), identifier=f"CHAIN_BAD_{length}"),), _profile())
        assert captured.value.fault.value == VECTOR["limit_fault"]

    for count in VECTOR["accepted_predicate_counts"]:
        predicates = [PredicateDefinition(f"P{index:03}", expression={"literal": True}) for index in range(count)]
        TickExecutor((_definition(predicates, identifier=f"COUNT_OK_{count}"),), _profile())
    for count in VECTOR["rejected_predicate_counts"]:
        predicates = [PredicateDefinition(f"P{index:03}", expression={"literal": True}) for index in range(count)]
        with pytest.raises(PCAMError) as captured:
            TickExecutor((_definition(predicates, identifier=f"COUNT_BAD_{count}"),), _profile())
        assert captured.value.fault.value == VECTOR["limit_fault"]


def _diamond(order):
    values = {
        "BASE": PredicateDefinition(
            "BASE",
            expression={"op": "gte", "args": [{"ref": "action.node_step"}, {"literal": 1}]},
        ),
        "LEFT": PredicateDefinition("LEFT", expression={"ref": "action.predicate.BASE"}),
        "RIGHT": PredicateDefinition("RIGHT", expression={"ref": "action.predicate.BASE"}),
        "TOP": PredicateDefinition(
            "TOP",
            expression={
                "op": "and",
                "args": [
                    {"ref": "action.predicate.LEFT"},
                    {"ref": "action.predicate.RIGHT"},
                ],
            },
        ),
    }
    return [values[identifier] for identifier in order]


def _projection(action):
    return {
        "node_step": action.node_step,
        "cycle": action.cycle,
        "truth": action.predicate_truth_state,
        "entries": action.predicate_entry_serials,
        "exits": action.predicate_exit_serials,
    }


def test_python_diamond_graph_order_edges_and_restore_match_shared_vector():
    outcomes = []
    for order_index, order in enumerate(VECTOR["diamond_orders"]):
        definition = _definition(_diamond(order), identifier=f"DIAMOND_{order_index}", loop=True)
        executor = TickExecutor((definition,), _profile())
        state = executor.initial_state()
        projections = []
        for tick in range(3):
            inputs = (_start(definition.id),) if tick == 0 else ()
            state, _ = executor.tick(state, inputs)
            projections.append(_projection(state.action_instances["1"]))
            state = executor.restore(executor.save(state))
        assert projections == VECTOR["diamond_expected"]
        outcomes.append(projections)
    assert outcomes[0] == outcomes[1]


def test_python_hostile_predicate_cycles_and_missing_dependencies_fail_closed():
    for case in VECTOR["definition_faults"]:
        if case["kind"] == "SELF_CYCLE":
            predicates = [PredicateDefinition("A", expression={"ref": "action.predicate.A"})]
        elif case["kind"] == "THREE_CYCLE":
            predicates = [
                PredicateDefinition("A", expression={"ref": "action.predicate.B"}),
                PredicateDefinition("B", expression={"ref": "action.predicate.C"}),
                PredicateDefinition("C", expression={"ref": "action.predicate.A"}),
            ]
        else:
            predicates = [PredicateDefinition("A", expression={"ref": "action.predicate.MISSING"})]
        with pytest.raises(PCAMError) as captured:
            TickExecutor((_definition(predicates, identifier=case["id"]),), _profile())
        assert captured.value.fault.value == case["fault"]
