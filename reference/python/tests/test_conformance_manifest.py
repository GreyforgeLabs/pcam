from copy import deepcopy

from pcam_runtime import load_document, validate_document


def _manifest():
    return load_document("release/conformance-claims.json")


def test_repository_conformance_manifest_is_valid_and_claims_nothing_early():
    manifest = _manifest()
    assert validate_document(manifest) == []
    assert all(not claim["claimed"] for claim in manifest["claims"].values())


def test_claim_with_open_requirement_is_rejected():
    manifest = deepcopy(_manifest())
    manifest["claims"]["PCAM-RUN-3"]["claimed"] = True
    diagnostics = validate_document(manifest)
    assert any("cannot contain OPEN" in item.message for item in diagnostics)


def test_manifest_requires_exact_requirement_sets_and_safe_existing_evidence():
    missing = deepcopy(_manifest())
    del missing["claims"]["PCAM-DEF-3"]["requirements"]["schema_validation"]
    assert any("requirement set mismatch" in item.message for item in validate_document(missing))

    unsafe = deepcopy(_manifest())
    requirement = unsafe["claims"]["PCAM-DEF-3"]["requirements"]["schema_validation"]
    requirement["evidence"] = ["../outside"]
    assert any("repository-relative" in item.message for item in validate_document(unsafe))


def test_dependent_claim_requires_parent_class_claim():
    manifest = deepcopy(_manifest())
    det = manifest["claims"]["PCAM-DET-3"]
    det["claimed"] = True
    for requirement in det["requirements"].values():
        requirement["status"] = "PASS"
        requirement["evidence"] = ["release/conformance-claims.json"]
    diagnostics = validate_document(manifest)
    assert any("requires claimed PCAM-RUN-3" in item.message for item in diagnostics)
