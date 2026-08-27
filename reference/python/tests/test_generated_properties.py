import random
from itertools import permutations

from pcam_runtime import (
    ActionDefinition,
    EffectEnvelope,
    EffectTemplate,
    FreezeToken,
    HostSnapshot,
    InteractionCandidate,
    InteractionRule,
    NodeDefinition,
    PredicateDefinition,
    RollbackManager,
    RuleOperation,
    RuntimeProfile,
    SemanticFact,
    TickExecutor,
    TickInput,
    TransitionDefinition,
    is_frozen,
    reduce_effects,
    resolve_candidate,
)


def test_generated_rates_and_restore_points_preserve_continuation():
    generator = random.Random(0x5043414D)
    for case in range(64):
        scale = generator.randint(1, 32)
        units = generator.randint(0, 64)
        definition = ActionDefinition(
            id=f"RATE_{case}",
            rate_scale=scale,
            units_per_tick=units,
            nodes=(NodeDefinition(id="RUN"),),
        )
        executor = TickExecutor((definition,), RuntimeProfile(max_quanta_per_action_per_tick=128))
        state = executor.initial_state()
        start = TickInput(f"start-{case}", 1, 0, "START", 0, action_definition_id=definition.id)
        state, _ = executor.tick(state, (start,))
        for _ in range(generator.randint(1, 8)):
            state, _ = executor.tick(state)
        restored = executor.restore(executor.save(state))
        for _ in range(8):
            state, left = executor.tick(state)
            restored, right = executor.tick(restored)
            assert left["state_digest"] == right["state_digest"]
        assert state.to_snapshot() == restored.to_snapshot()


def test_generated_action_graphs_and_input_permutations_are_deterministic():
    generator = random.Random(0xA6710)
    for case in range(24):
        node_count = generator.randint(2, 8)
        nodes = tuple(NodeDefinition(id=f"N{index}") for index in range(node_count))
        transitions = tuple(
            TransitionDefinition(
                id=f"T{index}",
                source_node=f"N{index}",
                evaluation_point="AFTER_QUANTUM",
                priority=10,
                target_node=f"N{index + 1}",
            )
            for index in range(node_count - 1)
        )
        definition = ActionDefinition(f"GRAPH_{case}", 1, 1, nodes, transitions=transitions)
        executor = TickExecutor((definition,))
        inputs = (
            TickInput("b", 2, 0, "START", 0, action_definition_id=definition.id),
            TickInput("a", 1, 0, "START", 0, action_definition_id=definition.id),
        )
        results = []
        for order in permutations(inputs):
            state, _ = executor.tick(executor.initial_state(), order)
            for _ in range(node_count):
                state, _ = executor.tick(state)
            results.append(state.to_snapshot())
        assert results[0] == results[1]


def test_generated_predicate_guards_produce_repeatable_transitions():
    generator = random.Random(0x6A4D)
    for threshold in (generator.randint(0, 20) for _ in range(32)):
        predicate = PredicateDefinition("READY", ("RUN",), min_node_step=threshold)
        definition = ActionDefinition(
            id=f"GUARD_{threshold}_{generator.randrange(1 << 30)}",
            rate_scale=1,
            units_per_tick=1,
            nodes=(NodeDefinition("RUN"), NodeDefinition("DONE")),
            predicates=(predicate,),
            transitions=(
                TransitionDefinition(
                    "guarded",
                    "RUN",
                    "POST_ADVANCE",
                    10,
                    target_node="DONE",
                    guard_predicate="READY",
                ),
            ),
        )
        executor = TickExecutor((definition,))
        states = []
        for _ in range(2):
            state = executor.initial_state()
            state, _ = executor.tick(
                state,
                (TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id),),
            )
            for _ in range(24):
                state, _ = executor.tick(state)
            states.append(state.to_snapshot())
        assert states[0] == states[1]


def test_generated_freeze_combinations_are_order_independent():
    generator = random.Random(0xF2EE2E)
    for case in range(64):
        tokens = tuple(
            FreezeToken.created(
                token_id=index + 1,
                source_id=index,
                target_id=9,
                creation_tick=generator.randint(0, 4),
                duration=generator.randint(1, 8),
                domains=(generator.choice(("PROGRESSION", "BUFFER_EXPIRY", "INPUT_CAPTURE")),),
                stack_group=f"g-{index}",
            )
            for index in range(generator.randint(1, 8))
        )
        shuffled = list(tokens)
        generator.shuffle(shuffled)
        for tick in range(12):
            for domain in ("PROGRESSION", "BUFFER_EXPIRY", "INPUT_CAPTURE"):
                assert is_frozen(tokens, tick, 9, domain) == is_frozen(tuple(shuffled), tick, 9, domain)


def test_generated_effect_aggregation_is_permutation_invariant():
    generator = random.Random(0xEFFECC7)
    for case in range(48):
        effects = tuple(
            EffectEnvelope(
                effect_id=f"e-{case}-{index}",
                effect_type="resource.delta",
                effect_class="RESOURCE",
                source_entity_id=generator.randint(1, 4),
                target_entity_id=1,
                source_action_instance_id=index,
                origin_tick=0,
                priority=generator.randint(0, 10),
                payload=generator.randint(-100, 100),
                reducer="SUM",
            )
            for index in range(generator.randint(1, 12))
        )
        expected = reduce_effects(effects)
        shuffled = list(effects)
        generator.shuffle(shuffled)
        assert reduce_effects(tuple(shuffled)) == expected


def test_generated_interaction_rule_order_is_definition_order_independent():
    generator = random.Random(0x1A7E2AC7)
    offense = SemanticFact(
        "strike",
        "OFFENSE",
        effect_templates=(EffectTemplate("combat.damage", "DAMAGE", 10, "SUM"),),
    )
    candidate = InteractionCandidate(0, "candidate", 1, 2, 3, "strike", "contact")
    for case in range(32):
        orders = generator.sample(range(1, 1000), generator.randint(1, 8))
        rules = tuple(
            InteractionRule(
                f"tag-{order}",
                "MODIFICATION",
                order,
                {"literal": True},
                (RuleOperation("ADD_DECISION_TAG", {"tag": f"T{order}"}),),
            )
            for order in orders
        ) + (
            InteractionRule("materialize", "MATERIALIZATION", 1000, {"literal": True}, (RuleOperation("MATERIALIZE"),)),
        )
        expected = resolve_candidate(candidate, offense, {}, rules)
        shuffled = list(rules)
        generator.shuffle(shuffled)
        assert resolve_candidate(candidate, offense, {}, tuple(shuffled)) == expected


def test_generated_rollback_corrections_match_direct_execution():
    generator = random.Random(0x2011BAC)
    for case in range(24):
        definition = ActionDefinition(
            id=f"ROLLBACK_{case}",
            rate_scale=generator.randint(1, 8),
            units_per_tick=generator.randint(0, 8),
            nodes=(NodeDefinition("RUN"),),
        )
        executor = TickExecutor((definition,))
        initial = executor.initial_state()
        start = TickInput("start", 1, 0, "START", 0, action_definition_id=definition.id)
        direct = initial
        direct, _ = executor.tick(direct, (start,))
        for _ in range(5):
            direct, _ = executor.tick(direct)
        corrected, _ = RollbackManager(executor).correct_and_resimulate(
            executor.save(initial),
            {},
            {tick: HostSnapshot() for tick in range(6)},
            0,
            (start,),
            6,
        )
        assert corrected.to_snapshot() == direct.to_snapshot()


def test_generated_parent_child_structures_respect_declared_limits():
    generator = random.Random(0xC411D)
    for case in range(16):
        capacity = generator.randint(1, 4)
        child = ActionDefinition(
            id=f"CHILD_{case}",
            rate_scale=1,
            units_per_tick=0,
            nodes=(NodeDefinition("RUN"),),
        )
        parent = ActionDefinition(
            id=f"PARENT_{case}",
            rate_scale=1,
            units_per_tick=0,
            nodes=(NodeDefinition("RUN"),),
            child_slot_capacities={"SUB": capacity},
            child_termination_policies={"SUB": "TERMINATE_CHILD"},
            transitions=(
                TransitionDefinition(
                    "launch",
                    "RUN",
                    "PRE_ADVANCE",
                    10,
                    target_kind="CHILD_ACTION",
                    target_action=child.id,
                    child_slot_id="SUB",
                    parent_policy="CONTINUE",
                    input_command="LAUNCH",
                ),
            ),
        )
        executor = TickExecutor((parent, child), RuntimeProfile(max_children_per_action=capacity))
        state = executor.initial_state()
        state, _ = executor.tick(
            state,
            (TickInput("start", 1, 0, "START", 0, action_definition_id=parent.id),),
        )
        for tick in range(1, capacity + 2):
            state, _ = executor.tick(state, (TickInput(f"launch-{tick}", 1, tick, "LAUNCH", tick),))
        assert len(state.action_instances["1"].child_instance_ids) == capacity
