import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_BOUNDS = {
    "collection_lengths",
    "recursion_depth",
    "definition_size",
    "snapshot_size",
    "integer_bounds",
    "identifier_syntax",
    "extension_declarations",
    "event_counts",
    "candidate_counts",
    "effect_counts",
    "redirect_counts",
    "buffer_counts",
    "child_counts",
}


def test_security_manifest_maps_every_normative_bound_to_existing_evidence():
    manifest = json.loads((ROOT / "release/security-robustness.json").read_text(encoding="utf-8"))
    assert set(manifest["bounds"]) == EXPECTED_BOUNDS
    assert set(manifest["untrusted_inputs"]) == {"definitions", "snapshots", "replays", "network_inputs"}
    for evidence in manifest["bounds"].values():
        assert evidence
        assert all((ROOT / path).is_file() for path in evidence)
    assert not any(manifest["non_claims"].values())
