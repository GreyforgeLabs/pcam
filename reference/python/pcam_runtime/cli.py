"""PCAM v3 command-line facade with stable JSON result envelopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .canonical import canonical_dumps, canonical_hash
from .errors import PCAMError, ResultCode
from .migration import migrate_legacy
from .pcam24 import compile_pcam24
from .schema import load_document, validate_document
from .state import SimulationState
from .vectors import rollback_vector, run_vector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcam")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "canonicalize", "definition-hash", "compile", "state-hash", "migrate-v2"):
        command = sub.add_parser(name)
        command.add_argument("file", type=Path)
    for name in ("run", "trace", "snapshot", "restore", "rollback-test"):
        command = sub.add_parser(name)
        command.add_argument("file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = load_document(args.file)
        handler = {
            "validate": _validate,
            "canonicalize": _canonicalize,
            "definition-hash": _definition_hash,
            "compile": _compile,
            "state-hash": _state_hash,
            "migrate-v2": _migrate_v2,
            "run": _run,
            "trace": _trace,
            "snapshot": _snapshot,
            "restore": _restore,
            "rollback-test": _rollback_test,
        }.get(args.command)
        assert handler is not None
        return handler(document)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": str(exc)}, exit_code=2)
    except PCAMError as exc:
        return _emit(
            {"code": exc.code.value, "fault": exc.fault.value, "message": exc.message},
            exit_code=2,
        )


def _validate(document: Any) -> int:
    diagnostics = validate_document(document)
    if diagnostics:
        return _emit(
            {
                "code": ResultCode.DEFINITION_REJECTED.value,
                "diagnostics": [item.to_dict() for item in diagnostics],
            },
            exit_code=2,
        )
    return _emit({"code": ResultCode.OK.value, "diagnostics": []})


def _canonicalize(document: Any) -> int:
    canonical = canonical_dumps(document).decode("utf-8")
    return _emit({"canonical": canonical, "code": ResultCode.OK.value})


def _definition_hash(document: Any) -> int:
    diagnostics = validate_document(document)
    if diagnostics:
        return _emit(
            {"code": ResultCode.DEFINITION_REJECTED.value, "diagnostics": [item.to_dict() for item in diagnostics]},
            exit_code=2,
        )
    return _emit({"code": ResultCode.OK.value, "definition_hash": canonical_hash(document)})


def _compile(document: Any) -> int:
    if not isinstance(document, dict) or document.get("kind") != "pcam24":
        return _emit(
            {"code": ResultCode.INVALID_INPUT.value, "message": "compile currently requires a PCAM-24 source"},
            exit_code=2,
        )
    compiled = compile_pcam24(document)
    diagnostics = validate_document(compiled)
    if diagnostics:
        return _emit(
            {"code": ResultCode.DEFINITION_REJECTED.value, "diagnostics": [item.to_dict() for item in diagnostics]},
            exit_code=2,
        )
    return _emit({"code": ResultCode.OK.value, "definition": compiled})


def _state_hash(document: Any) -> int:
    if not isinstance(document, dict) or "definition_set_hash" not in document:
        return _emit(
            {"code": ResultCode.INVALID_INPUT.value, "message": "state-hash requires a snapshot"},
            exit_code=2,
        )
    diagnostics = validate_document(document)
    if diagnostics:
        return _emit(
            {"code": ResultCode.DEFINITION_REJECTED.value, "diagnostics": [item.to_dict() for item in diagnostics]},
            exit_code=2,
        )
    return _emit({"code": ResultCode.OK.value, "state_hash": canonical_hash(document)})


def _migrate_v2(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "legacy definition must be an object"}, exit_code=2)
    result = migrate_legacy(document)
    return _emit(
        {
            "code": ResultCode.OK.value,
            "definition": result.definition,
            "source_evidence_hash": result.source_evidence_hash,
            "source_version": result.source_version,
            "warnings": [warning.to_dict() for warning in result.warnings],
        }
    )


def _run(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "runtime vector must be an object"}, 2)
    result = run_vector(document)
    mismatch = _expected_digest_mismatch(document, result.final_state.state_hash())
    if mismatch:
        return _emit(mismatch, 2)
    return _emit(
        {
            "code": ResultCode.OK.value,
            "final_state_digest": result.final_state.state_hash(),
            "final_tick": result.final_state.tick,
        }
    )


def _trace(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "runtime vector must be an object"}, 2)
    result = run_vector(document)
    mismatch = _expected_digest_mismatch(document, result.final_state.state_hash())
    if mismatch:
        return _emit(mismatch, 2)
    return _emit(
        {
            "code": ResultCode.OK.value,
            "final_state_digest": result.final_state.state_hash(),
            "traces": list(result.traces),
        }
    )


def _snapshot(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "runtime vector must be an object"}, 2)
    result = run_vector(document)
    return _emit(
        {
            "code": ResultCode.OK.value,
            "snapshot": result.final_state.to_snapshot(),
            "state_hash": result.final_state.state_hash(),
        }
    )


def _restore(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "snapshot must be an object"}, 2)
    state = SimulationState.from_snapshot(document)
    snapshot = state.to_snapshot()
    return _emit({"code": ResultCode.OK.value, "snapshot": snapshot, "state_hash": state.state_hash()})


def _rollback_test(document: Any) -> int:
    if not isinstance(document, dict):
        return _emit({"code": ResultCode.INVALID_INPUT.value, "message": "runtime vector must be an object"}, 2)
    direct, corrected, traces = rollback_vector(document)
    equivalent = direct.to_snapshot() == corrected.to_snapshot()
    return _emit(
        {
            "code": ResultCode.OK.value if equivalent else ResultCode.RUNTIME_FAULT.value,
            "corrected_digest": corrected.state_hash(),
            "direct_digest": direct.state_hash(),
            "equivalent": equivalent,
            "resimulated_ticks": len(traces),
        },
        0 if equivalent else 2,
    )


def _expected_digest_mismatch(document: dict[str, Any], actual: str) -> dict[str, Any] | None:
    expected = document.get("expected", {}).get("final_state_digest")
    if expected is not None and expected != actual:
        return {
            "actual": actual,
            "code": ResultCode.RUNTIME_FAULT.value,
            "expected": expected,
            "message": "runtime vector final digest mismatch",
        }
    return None


def _emit(payload: dict[str, Any], exit_code: int = 0) -> int:
    sys.stdout.buffer.write(canonical_dumps(payload) + b"\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
