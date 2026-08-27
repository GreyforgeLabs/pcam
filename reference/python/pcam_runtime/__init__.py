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
from .effects import EffectEnvelope, ReducedEffect, RejectedEffect, canonical_effects, reduce_effects
from .intents import ArbitrationState, Claim, Intent, IntentDecision, allocate_action_instance_ids, arbitrate, canonical_intents
from .interactions import (
    EffectTemplate,
    InteractionCandidate,
    InteractionDecision,
    InteractionRule,
    RuleOperation,
    SemanticFact,
    canonical_candidates,
    resolve_candidate,
    validate_rules,
)
from .ledgers import HitPolicy, LedgerContext, Receipt, is_eligible as ledger_is_eligible, ledger_key, receipt_required, write_receipt
from .numeric import OverflowPolicy, apply_i64, apply_u64, euclidean_divmod, scale_ratio
from .rng import PCG32Stream
from .schema import Diagnostic, load_document, validate_document
from .state import ActionInstance, SimulationState

__all__ = [
    "ActionDefinition",
    "ActionInstance",
    "ArbitrationState",
    "BufferEntry",
    "Claim",
    "Contact",
    "Diagnostic",
    "Effect",
    "EffectEnvelope",
    "EffectTemplate",
    "FreezeToken",
    "HostSnapshot",
    "HitPolicy",
    "Intent",
    "IntentDecision",
    "InteractionCandidate",
    "InteractionDecision",
    "InteractionRule",
    "LedgerContext",
    "NodeDefinition",
    "OverflowPolicy",
    "PCAMError",
    "PCAMFault",
    "PCG32Stream",
    "PredicateDefinition",
    "ReducedEffect",
    "Receipt",
    "RejectedEffect",
    "ResultCode",
    "RollbackManager",
    "RuntimeProfile",
    "RuleOperation",
    "SemanticFact",
    "SimulationState",
    "TickExecutor",
    "TickInput",
    "TransitionDefinition",
    "canonical_dumps",
    "canonical_effects",
    "canonical_candidates",
    "canonical_hash",
    "canonical_intents",
    "compile_pcam24",
    "evaluate",
    "apply_i64",
    "apply_u64",
    "apply_consumption",
    "allocate_action_instance_ids",
    "arbitrate",
    "capture_entry",
    "euclidean_divmod",
    "expire_buffer_entries",
    "expire_freeze_tokens",
    "load_document",
    "is_frozen",
    "ledger_is_eligible",
    "ledger_key",
    "progression_accrual",
    "reduce_effects",
    "receipt_required",
    "resolve_candidate",
    "select_entry",
    "add_token",
    "validate_document",
    "validate_rules",
    "write_receipt",
    "scale_ratio",
]
