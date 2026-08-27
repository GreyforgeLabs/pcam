from pathlib import Path

from pcam_runtime import compile_pcam24, load_document, validate_document

ROOT = Path(__file__).resolve().parents[3]


def test_pcam24_compiles_to_valid_core_action_with_explicit_lifecycle():
    source = load_document(ROOT / "tests" / "valid" / "minimal-pcam24.json")
    compiled = compile_pcam24(source)
    assert compiled["kind"] == "action"
    assert compiled["nodes"]["timeline"]["duration_quanta"] == 24
    assert compiled["transitions"][0]["target"] == {"kind": "TERMINATE"}
    assert validate_document(compiled) == []


def test_pcam24_loop_compiles_explicit_cycle_boundary():
    source = load_document(ROOT / "tests" / "valid" / "minimal-pcam24.json")
    source["lifecycle"] = "LOOP"
    compiled = compile_pcam24(source)
    transition = compiled["transitions"][0]
    assert transition["cycle_delta"] == 1
    assert transition["target"] == {"kind": "NODE", "node": "timeline", "target_step": 0}
