import json
from copy import deepcopy
from pathlib import Path

import pytest

from pcam_runtime import action_from_document, canonical_hash, validate_document

ROOT = Path(__file__).resolve().parents[3]


def _vector():
    return json.loads(
        (ROOT / "tests/vectors/full-definition-hashes.json").read_text(encoding="utf-8")
    )


def _set_path(document, path, value):
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = deepcopy(value)


def test_python_full_definition_base_is_schema_complete_and_hash_pinned():
    vector = _vector()
    document = vector["base_document"]
    schema = json.loads((ROOT / "schemas/action.schema.json").read_text(encoding="utf-8"))

    assert set(document) == set(schema["properties"])
    assert set(document) == {case["path"][0] for case in vector["mutations"]}
    assert validate_document(document) == []
    assert canonical_hash(document) == vector["expected"]["base_sha256"]


def test_python_every_action_document_field_changes_the_shared_hash():
    vector = _vector()
    base = vector["base_document"]
    base_hash = canonical_hash(base)
    mutation_hashes = []
    for case in vector["mutations"]:
        document = deepcopy(base)
        _set_path(document, case["path"], case["value"])
        diagnostics = validate_document(document)
        assert (diagnostics == []) is case["valid"], case["id"]
        digest = canonical_hash(document)
        assert digest != base_hash, case["id"]
        mutation_hashes.append({"id": case["id"], "sha256": digest})

    assert canonical_hash(mutation_hashes) == vector["expected"][
        "mutation_hashes_sha256"
    ]


def test_schema_adapter_deep_captures_and_rejects_direct_definition_mutation():
    vector = _vector()
    source = deepcopy(vector["base_document"])
    definition = action_from_document(source)
    before_canonical = definition.to_canonical()
    before_hash = definition.definition_hash

    for case in vector["mutations"]:
        _set_path(source, case["path"], case["value"])
    assert definition.to_canonical() == before_canonical
    assert definition.definition_hash == before_hash

    wait = next(node for node in definition.nodes if node.id == "wait")
    attempts = (
        lambda: definition.metadata.__setitem__("changed", True),
        lambda: definition.extensions["tech.greyforge.binding"]["payload"].__setitem__(
            "label", "changed"
        ),
        lambda: definition.parameter_declarations["power"].__setitem__("default", 9),
        lambda: wait.entry_effects[0].payload.__setitem__("clip", "changed"),
        lambda: definition.predicates[0].expression.__setitem__("literal", False),
        lambda: definition.semantic_facts[0].fact.attributes.__setitem__("rank", 9),
        lambda: definition.transitions[0].metadata.__setitem__("changed", True),
    )
    for attempt in attempts:
        with pytest.raises(TypeError, match="hash-bound definition data is immutable"):
            attempt()
    assert definition.definition_hash == before_hash
