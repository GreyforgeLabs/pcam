import json
from pathlib import Path

import pytest

from pcam_runtime import PCAMError
from pcam_runtime.ledgers import (
    HitPolicy,
    LedgerContext,
    is_eligible,
    ledger_key,
    receipt_required,
    write_receipt,
)

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads((ROOT / "tests/vectors/ledgers.json").read_text(encoding="utf-8"))


def test_python_ledger_policies_match_shared_sequential_vectors():
    vector = _vector()
    for case in vector["cases"]:
        policy = HitPolicy(**case["policy"])
        ledger = {}
        for index, step in enumerate(case["steps"]):
            context = LedgerContext(**(vector["base_context"] | step["context"]))
            assert ledger_key(policy, context) == step["key"], (case["id"], index)
            eligible = is_eligible(ledger, policy, context)
            assert eligible is step["eligible"], (case["id"], index)
            written = False
            if step["write"] and eligible:
                ledger, receipt = write_receipt(
                    ledger,
                    policy,
                    context,
                    f"{case['id']}-{index}",
                )
                written = receipt is not None
            assert written is step["receipt_written"], (case["id"], index)
            assert len(ledger) == step["ledger_count"], (case["id"], index)


def test_python_receipt_conditions_match_shared_truth_table():
    for case in _vector()["receipt_conditions"]:
        assert receipt_required(case["condition"], case["accepted"], case["impact"]) is case[
            "required"
        ]


def test_python_rejects_shared_invalid_ledger_policies():
    for policy in _vector()["invalid_policies"]:
        with pytest.raises(PCAMError):
            HitPolicy(**policy)
