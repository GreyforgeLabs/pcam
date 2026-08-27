import pytest

from pcam_runtime import (
    EffectTemplate,
    InteractionCandidate,
    InteractionRule,
    RuleOperation,
    SemanticFact,
    canonical_candidates,
    resolve_candidate,
)
from pcam_runtime.errors import PCAMError


def _candidate(candidate_id: str, source: int, target: int, instance: int) -> InteractionCandidate:
    return InteractionCandidate(4, candidate_id, source, target, instance, "strike", candidate_id)


def _offense() -> SemanticFact:
    return SemanticFact(
        "strike",
        "OFFENSE",
        channels=("STRIKE",),
        effect_templates=(
            EffectTemplate("combat.damage", "DAMAGE", 30, "SUM"),
            EffectTemplate("combat.stagger", "STAGGER", 25, "SUM"),
        ),
    )


def _materialize_rule() -> InteractionRule:
    return InteractionRule(
        "materialize",
        "MATERIALIZATION",
        1000,
        {"literal": True},
        (RuleOperation("MATERIALIZE"),),
    )


def test_parry_rejects_incoming_candidate_without_erasing_outgoing_candidate():
    parry = InteractionRule(
        "parry",
        "ROUTING",
        100,
        {
            "op": "and",
            "args": [
                {"op": "contains", "args": [{"ref": "offense.channels"}, {"literal": "STRIKE"}]},
                {"op": "contains", "args": [{"ref": "defense.tags"}, {"literal": "PARRY"}]},
            ],
        },
        (RuleOperation("REJECT", {"reason": "PARRIED"}),),
        stop_pipeline=True,
    )
    facts = {1: None, 2: SemanticFact("parry", "DEFENSE", tags=("PARRY",))}
    incoming = resolve_candidate(_candidate("a-to-b", 1, 2, 10), _offense(), facts, (parry, _materialize_rule()))
    outgoing = resolve_candidate(_candidate("b-to-a", 2, 1, 20), _offense(), facts, (parry, _materialize_rule()))
    assert incoming.status == "REJECTED"
    assert incoming.generated_effects == ()
    assert outgoing.status == "ACCEPTED"
    assert len(outgoing.generated_effects) == 2


def test_armor_modifies_stagger_but_preserves_damage():
    armor = InteractionRule(
        "armor",
        "MODIFICATION",
        200,
        {"op": "contains", "args": [{"ref": "defense.tags"}, {"literal": "ARMOR"}]},
        (RuleOperation("SCALE_EFFECT_CLASS", {"effect_class": "STAGGER", "numerator": 0, "denominator": 1}),),
    )
    decision = resolve_candidate(
        _candidate("armor-hit", 1, 2, 10),
        _offense(),
        {2: SemanticFact("armor", "DEFENSE", tags=("ARMOR",))},
        (armor, _materialize_rule()),
    )
    payloads = {item.effect_class: item.payload for item in decision.active_effect_templates}
    assert payloads == {"DAMAGE": 30, "STAGGER": 0}
    assert len(decision.generated_effects) == 2


def test_candidate_order_ignores_host_enumeration_and_supports_trade():
    first = _candidate("z", 2, 1, 20)
    second = _candidate("a", 1, 2, 10)
    assert canonical_candidates((first, second)) == (second, first)
    decisions = [
        resolve_candidate(item, _offense(), {}, (_materialize_rule(),))
        for item in canonical_candidates((first, second))
    ]
    assert all(item.status == "ACCEPTED" and item.generated_effects for item in decisions)


def test_redirect_loop_faults_or_rejects_deterministically():
    redirect = InteractionRule(
        "reflect",
        "ROUTING",
        1,
        {"literal": True},
        (RuleOperation("REDIRECT", {"target_entity_id": 1}),),
    )
    candidate = _candidate("loop", 1, 2, 10)
    with pytest.raises(PCAMError) as raised:
        resolve_candidate(candidate, _offense(), {}, (redirect,))
    assert raised.value.fault.value == "REDIRECT_LIMIT_EXCEEDED"

    decision = resolve_candidate(candidate, _offense(), {}, (redirect,), redirect_limit_policy="REJECT")
    assert decision.status == "REJECTED"
    assert "REDIRECT_LIMIT_EXCEEDED" in decision.decision_tags
