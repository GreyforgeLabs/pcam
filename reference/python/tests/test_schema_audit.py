from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from pcam_runtime import load_document, validate_document

ROOT = Path(__file__).resolve().parents[3]


def _resolve(document, pointer):
    value = document
    for raw in pointer.strip("/").split("/") if pointer != "/" else ():
        key = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _parent(document, pointer):
    parts = pointer.strip("/").split("/")
    parent = document
    for raw in parts[:-1]:
        key = raw.replace("~1", "/").replace("~0", "~")
        parent = parent[int(key)] if isinstance(parent, list) else parent[key]
    tail = parts[-1].replace("~1", "/").replace("~0", "~")
    return parent, int(tail) if isinstance(parent, list) else tail


def _mutate(document, operation):
    if operation["op"] == "append_copy":
        target = _resolve(document, operation["path"])
        target.append(deepcopy(_resolve(document, operation["source"])))
        return
    parent, key = _parent(document, operation["path"])
    if operation["op"] == "remove":
        del parent[key]
    elif operation["op"] == "add" and isinstance(parent, list):
        parent.insert(key, deepcopy(operation["value"]))
    elif operation["op"] in {"add", "replace"}:
        parent[key] = deepcopy(operation["value"])
    else:
        raise AssertionError(operation["op"])


def test_every_declared_schema_is_valid_draft_2020_12_and_every_evidence_path_exists():
    audit = json.loads((ROOT / "release/schema-audit.json").read_text())
    schemas = {
        item["schema"] for item in audit["normative_definition_types"].values()
    }.union(audit["additional_machine_documents"].values())
    for relative in schemas:
        path = ROOT / relative
        Draft202012Validator.check_schema(json.loads(path.read_text()))
    for entry in audit["normative_definition_types"].values():
        assert all((ROOT / relative).is_file() for relative in entry["positive"])
    for key in ("negative_corpus",):
        assert (ROOT / audit[key]).is_file()
    for key in ("canonical_hash_corpus", "version_vectors", "extension_evidence"):
        assert all((ROOT / relative).is_file() for relative in audit[key])


def test_all_normative_positive_documents_validate():
    audit = json.loads((ROOT / "release/schema-audit.json").read_text())
    paths = {
        relative
        for entry in audit["normative_definition_types"].values()
        for relative in entry["positive"]
    }
    for relative in sorted(paths):
        document = load_document(ROOT / relative)
        if document.get("kind") in {"action", "interaction_profile", "runtime_profile", "pcam24"}:
            assert validate_document(document) == [], relative


def test_machine_negative_mutation_corpus_fails_with_stable_codes():
    corpus = json.loads((ROOT / "tests/invalid/schema-mutations.json").read_text())
    for case in corpus["cases"]:
        document = load_document(ROOT / case["base"])
        for operation in case["operations"]:
            _mutate(document, operation)
        diagnostics = validate_document(document)
        assert diagnostics, case["id"]
        if "expected_code" in case:
            assert any(item.code == case["expected_code"] for item in diagnostics), case["id"]
        if "expected_fault" in case:
            assert any(item.fault == case["expected_fault"] for item in diagnostics), case["id"]
