import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_normative_repository_layout_manifest_is_complete_and_present():
    manifest = json.loads((ROOT / "release/repository-layout.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "pcam.repository-layout.v1"
    assert len(manifest["required_files"]) == len(set(manifest["required_files"]))
    assert len(manifest["required_directories"]) == len(set(manifest["required_directories"]))
    assert all((ROOT / path).is_file() for path in manifest["required_files"])
    assert all((ROOT / path).is_dir() for path in manifest["required_directories"])
