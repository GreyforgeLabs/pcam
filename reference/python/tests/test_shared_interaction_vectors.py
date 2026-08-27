import json
from pathlib import Path

import pytest

from pcam_runtime import (
    EffectTemplate,
    InteractionCandidate,
    InteractionRule,
    RuleOperation,
    SemanticFact,
    canonical_candidates,
    canonical_hash,
    resolve_candidate,
)
from pcam_runtime.errors import PCAMError

ROOT = Path(__file__).resolve().parents[3]


def _vectors():
    return json.loads((ROOT / "tests/vectors/interactions.json").read_text(encoding="utf-8"))


def _template(value):
    return EffectTemplate(**value)


def _fact(value):
    value = dict(value)
    value["channels"] = tuple(value.get("channels", ()))
    value["tags"] = tuple(value.get("tags", ()))
    value["effect_templates"] = tuple(
        _template(template) for template in value.get("effect_templates", ())
    )
    return SemanticFact(**value)


def _operation(value):
    data = dict(value.get("data", {}))
    for key in ("template", "replacement"):
        if key in data:
            data[key] = _template(data[key])
    return RuleOperation(value["op"], data or None)


def _rule(value):
    value = dict(value)
    value["operations"] = tuple(_operation(operation) for operation in value["operations"])
    return InteractionRule(**value)


def _decision_record(value):
    return {
        "candidate_id": value.candidate_id,
        "status": value.status,
        "current_target": value.current_target,
        "active_effect_templates": [template.__dict__ for template in value.active_effect_templates],
        "decision_tags": list(value.decision_tags),
        "generated_effects": [effect.__dict__ for effect in value.generated_effects],
        "receipt_requests": list(value.receipt_requests),
        "redirect_count": value.redirect_count,
        "visited_targets": list(value.visited_targets),
        "trace": list(value.trace),
    }


def _summary(value):
    return {
        "status": value.status,
        "current_target": value.current_target,
        "effect_classes": [item.effect_class for item in value.active_effect_templates],
        "generated_effect_ids": [item.effect_id for item in value.generated_effects],
        "decision_tags": list(value.decision_tags),
        "receipt_requests": list(value.receipt_requests),
        "redirect_count": value.redirect_count,
        "visited_targets": list(value.visited_targets),
        "trace_rule_ids": [item["rule_id"] for item in value.trace],
    }


def _resolve(case):
    options = case.get("options", {})
    return resolve_candidate(
        InteractionCandidate(**case["candidate"]),
        _fact(case["offense"]),
        {
            int(target): _fact(fact) if fact is not None else None
            for target, fact in case["defense_by_target"].items()
        },
        tuple(_rule(rule) for rule in case["rules"]),
        max_redirects=options.get("max_redirects", 8),
        redirect_limit_policy=options.get("redirect_limit_policy", "FAULT"),
    )


def test_python_interaction_resolver_matches_shared_decision_records():
    for case in _vectors()["cases"]:
        decision = _resolve(case)
        assert _summary(decision) == case["expected"], case["id"]
        assert canonical_hash(_decision_record(decision)) == case["decision_sha256"], case["id"]


def test_python_interaction_resolver_matches_shared_faults():
    for case in _vectors()["fault_cases"]:
        with pytest.raises(PCAMError) as raised:
            _resolve(case)
        code = (
            raised.value.code.value
            if case["fault"] == "DEFINITION_REJECTED"
            else raised.value.fault.value
        )
        assert code == case["fault"], case["id"]


def test_python_candidate_order_matches_shared_vector():
    order = _vectors()["canonical_candidate_order"]
    candidates = tuple(InteractionCandidate(**item) for item in order["candidates"])
    assert [item.candidate_id for item in canonical_candidates(candidates)] == order["candidate_ids"]
