"""PCAM v3 Python reference-runtime vertical slice.

This package is intentionally narrow. It exercises the first conformance-
preserving slice without claiming full PCAM-RUN-3 or rollback conformance.
"""

from .canonical import canonical_dumps, canonical_hash
from .errors import PCAMError, PCAMFault, ResultCode
from .model import (
    ActionDefinition,
    Contact,
    Effect,
    HostSnapshot,
    NodeDefinition,
    PredicateDefinition,
    RuntimeProfile,
    TickInput,
    TransitionDefinition,
)
from .rollback import RollbackManager
from .runtime import TickExecutor
from .pcam24 import compile_pcam24
from .expressions import evaluate
from .buffers import BufferEntry, apply_consumption, capture_entry, end_tick as expire_buffer_entries, select_entry
from .freezes import FreezeToken, add_token, end_tick as expire_freeze_tokens, is_frozen, progression_accrual
from .numeric import OverflowPolicy, apply_i64, apply_u64, euclidean_divmod, scale_ratio
from .rng import PCG32Stream
from .schema import Diagnostic, load_document, validate_document
from .state import ActionInstance, SimulationState

__all__ = [
    "ActionDefinition",
    "ActionInstance",
    "BufferEntry",
    "Contact",
    "Diagnostic",
    "Effect",
    "FreezeToken",
    "HostSnapshot",
    "NodeDefinition",
    "OverflowPolicy",
    "PCAMError",
    "PCAMFault",
    "PCG32Stream",
    "PredicateDefinition",
    "ResultCode",
    "RollbackManager",
    "RuntimeProfile",
    "SimulationState",
    "TickExecutor",
    "TickInput",
    "TransitionDefinition",
    "canonical_dumps",
    "canonical_hash",
    "compile_pcam24",
    "evaluate",
    "apply_i64",
    "apply_u64",
    "apply_consumption",
    "capture_entry",
    "euclidean_divmod",
    "expire_buffer_entries",
    "expire_freeze_tokens",
    "load_document",
    "is_frozen",
    "progression_accrual",
    "select_entry",
    "add_token",
    "validate_document",
    "scale_ratio",
]
