import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_master_specification_has_complete_unique_top_level_sections():
    specification = (ROOT / "spec/PCAM-v3.md").read_text(encoding="utf-8")
    sections = [int(value) for value in re.findall(r"^# ([1-9][0-9]*)\.", specification, re.MULTILINE)]
    assert sections == list(range(1, 48))
    assert "release gates in §45" in specification


def test_resolved_normative_contracts_remain_in_master_text():
    specification = (ROOT / "spec/PCAM-v3.md").read_text(encoding="utf-8")
    required_contracts = (
        "deferred_quanta",
        "atomic_group_id` is an optional opaque correlation identifier",
        "`FREEZE_ALL_ACTION_LOGIC` expands exactly to",
        "The stack-group identity key is `(target_id, stack_group)`",
        "defense_fact_id, optional",
        "More than one eligible defense fact is ambiguous",
        "`MATERIALIZE` converts the currently selected active templates",
        "the event is not visible or expired",
        "max_expression_depth",
        "max_expression_nodes",
        "Canonical machine documents MUST encode an absent `input_match` or `event_match` as `null`",
        "Phase is an optional projection, never the whole state",
    )
    assert all(contract in specification for contract in required_contracts)


def test_ordering_fault_and_bound_contracts_are_explicit():
    specification = (ROOT / "spec/PCAM-v3.md").read_text(encoding="utf-8")
    for heading in (
        "## 13.2 Canonical Input Order",
        "## 15.3 Canonical Intent Order",
        "## 20.5 Canonical Candidate Order",
        "## 23.5 Canonical Effect Order",
        "# 30. Fault Model",
        "# 31. Required Limits",
        "# 44. Security and Robustness",
    ):
        assert specification.count(heading) == 1


def test_normative_issue_ledger_and_specification_gate_are_closed_without_stability_claim():
    ledger = (ROOT / "spec/open-issues.md").read_text(encoding="utf-8")
    gate = (ROOT / "release/specification-gate.md").read_text(encoding="utf-8")
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert "Status: CLOSED" in ledger
    assert "State: CLOSED" in gate
    assert "Specification | closed" in status
    assert "Stability: not Stable, Normative" in status
