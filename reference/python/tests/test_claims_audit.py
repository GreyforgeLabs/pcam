import json
import re
from pathlib import Path

from pcam_runtime import validate_document

ROOT = Path(__file__).resolve().parents[3]


def _allowed(path, line, rules):
    relative = path.relative_to(ROOT).as_posix()
    return any(
        relative == rule["path"] and re.search(rule["context_regex"], line, re.IGNORECASE)
        for rule in rules
    )


def _markdown_lines():
    for path in sorted(ROOT.glob("**/*.md")):
        if ".git" in path.parts or "target" in path.parts:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            yield path, number, line


def test_prohibited_claim_vocabulary_occurs_only_in_audited_nonclaim_contexts():
    audit = json.loads((ROOT / "release/claims-audit.json").read_text())
    failures = []
    for path, number, line in _markdown_lines():
        for pattern in audit["prohibited_claim_patterns"]:
            if re.search(pattern["regex"], line, re.IGNORECASE) and not _allowed(
                path,
                line,
                audit["allowed_prohibition_contexts"],
            ):
                failures.append(f"{path.relative_to(ROOT)}:{number}:{pattern['id']}")
    assert failures == []


def test_class_and_stability_labels_occur_only_in_normative_or_nonclaim_contexts():
    audit = json.loads((ROOT / "release/claims-audit.json").read_text())
    failures = []
    for path, number, line in _markdown_lines():
        if re.search(audit["conformance_class_regex"], line) and not _allowed(
            path,
            line,
            audit["allowed_conformance_contexts"],
        ):
            failures.append(f"{path.relative_to(ROOT)}:{number}:conformance-class")
        if re.search(audit["stable_label_regex"], line, re.IGNORECASE) and not _allowed(
            path,
            line,
            audit["allowed_stability_contexts"],
        ):
            failures.append(f"{path.relative_to(ROOT)}:{number}:stable-label")
    assert failures == []


def test_machine_conformance_manifest_remains_valid_and_unclaimed():
    manifest = json.loads((ROOT / "release/conformance-claims.json").read_text())
    assert validate_document(manifest) == []
    assert all(claim["claimed"] is False for claim in manifest["claims"].values())
