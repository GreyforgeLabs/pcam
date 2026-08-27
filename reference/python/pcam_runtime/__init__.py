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
from .numeric import OverflowPolicy, apply_i64, apply_u64, euclidean_divmod, scale_ratio
from .rng import PCG32Stream
from .schema import Diagnostic, load_document, validate_document
from .state import ActionInstance, SimulationState

__all__ = [
    "ActionDefinition",
    "ActionInstance",
    "Contact",
    "Diagnostic",
    "Effect",
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
    "euclidean_divmod",
    "load_document",
    "validate_document",
    "scale_ratio",
]
