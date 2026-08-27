"""Bounded lockstep coordination and server-authoritative correction planning."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import canonical_dumps, canonical_hash
from .immutable import freeze_value


@dataclass(frozen=True)
class LockstepTick:
    status: str
    tick: int
    tick_document: dict[str, object] | None = None
    missing_peers: tuple[str, ...] = ()
    predicted_peers: tuple[str, ...] = ()
    digest_due: bool = False


@dataclass(frozen=True)
class DigestResolution:
    status: str
    tick: int
    mismatched_peers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServerCorrectionPlan:
    operation: str
    authoritative_tick: int
    discard_prediction_ticks: int


@dataclass(frozen=True)
class _PeerPacket:
    definition_set_hash: str
    inputs: tuple[dict[str, object], ...]
    contacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", freeze_value(self.inputs))
        object.__setattr__(self, "contacts", freeze_value(self.contacts))


class LockstepCoordinator:
    def __init__(
        self,
        required_peers: tuple[str, ...],
        definition_set_hash: str,
        input_availability_policy: str,
        digest_interval_ticks: int,
        desynchronization_policy: str,
        predictor_id: str | None = None,
    ):
        canonical_peers = tuple(sorted(required_peers, key=lambda item: item.encode("utf-8")))
        if not canonical_peers or len(canonical_peers) != len(set(canonical_peers)):
            raise ValueError("lockstep peers must be nonempty and unique")
        if input_availability_policy not in {"WAIT", "PREDICT"}:
            raise ValueError("unsupported lockstep input availability policy")
        if input_availability_policy == "PREDICT" and predictor_id != "pcam.predict.no-input.v1":
            raise ValueError("bounded lockstep prediction requires pcam.predict.no-input.v1")
        if digest_interval_ticks <= 0:
            raise ValueError("digest interval must be positive")
        if desynchronization_policy not in {"pcam.desync.abort", "pcam.desync.report"}:
            raise ValueError("unsupported desynchronization policy")
        self.required_peers = canonical_peers
        self.definition_set_hash = definition_set_hash
        self.input_availability_policy = input_availability_policy
        self.digest_interval_ticks = digest_interval_ticks
        self.desynchronization_policy = desynchronization_policy
        self.predictor_id = predictor_id
        self.next_tick = 0
        self.aborted = False
        self._packets: dict[str, _PeerPacket] = {}
        self._digest_ticks: set[int] = set()
        self._digest_reports: dict[int, dict[str, str]] = {}
        self._local_digests: dict[int, str] = {}

    def submit(
        self,
        peer_id: str,
        tick: int,
        definition_set_hash: str,
        inputs: tuple[dict[str, object], ...] = (),
        contacts: tuple[dict[str, object], ...] = (),
    ) -> None:
        self._require_active()
        if peer_id not in self.required_peers:
            raise ValueError("unknown lockstep peer")
        if tick != self.next_tick:
            raise ValueError("lockstep packet tick does not match next tick")
        if definition_set_hash != self.definition_set_hash:
            raise ValueError("lockstep definition-set hash mismatch")
        if peer_id in self._packets:
            raise ValueError("duplicate lockstep peer packet")
        if any(int(item.get("assigned_tick", -1)) != tick for item in inputs):
            raise ValueError("lockstep input assigned_tick mismatch")
        self._packets[peer_id] = _PeerPacket(definition_set_hash, inputs, contacts)

    def advance(self) -> LockstepTick:
        self._require_active()
        missing = tuple(peer for peer in self.required_peers if peer not in self._packets)
        if missing and self.input_availability_policy == "WAIT":
            return LockstepTick("WAITING", self.next_tick, missing_peers=missing)
        packets = tuple(self._packets[peer] for peer in self.required_peers if peer in self._packets)
        host_hashes = {canonical_hash(packet.contacts) for packet in packets}
        if len(host_hashes) > 1:
            raise ValueError("lockstep deterministic host snapshot mismatch")
        contacts = packets[0].contacts if packets else ()
        inputs = tuple(item for packet in packets for item in packet.inputs)
        identifiers = [str(item.get("input_id")) for item in inputs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("lockstep input_id collision")
        inputs = tuple(sorted(inputs, key=_input_key))
        tick = self.next_tick
        due = (tick + 1) % self.digest_interval_ticks == 0
        document = {"inputs": list(inputs), "contacts": list(contacts)}
        self._packets.clear()
        self.next_tick += 1
        if due:
            self._digest_ticks.add(tick)
        return LockstepTick(
            "READY",
            tick,
            freeze_value(document),
            predicted_peers=missing,
            digest_due=due,
        )

    def submit_digest(
        self,
        peer_id: str,
        tick: int,
        reported_digest: str,
        local_digest: str,
    ) -> DigestResolution:
        self._require_active()
        if peer_id not in self.required_peers:
            raise ValueError("unknown lockstep peer")
        if tick not in self._digest_ticks:
            raise ValueError("state digest is not due for tick")
        known_local = self._local_digests.setdefault(tick, local_digest)
        if known_local != local_digest:
            raise ValueError("local digest changed during exchange")
        reports = self._digest_reports.setdefault(tick, {})
        if peer_id in reports:
            raise ValueError("duplicate peer digest")
        reports[peer_id] = reported_digest
        missing = set(self.required_peers) - set(reports)
        if missing:
            return DigestResolution("WAITING", tick)
        mismatched = tuple(peer for peer in self.required_peers if reports[peer] != local_digest)
        if mismatched and self.desynchronization_policy == "pcam.desync.abort":
            self.aborted = True
            return DigestResolution("ABORTED", tick, mismatched)
        return DigestResolution("REPORTED" if mismatched else "MATCH", tick, mismatched)

    def _require_active(self) -> None:
        if self.aborted:
            raise ValueError("lockstep session is aborted")


class ServerAuthoritativeCorrectionPlanner:
    def __init__(self, correction_policy: str, max_latency_compensation_ticks: int):
        if correction_policy not in {
            "pcam.correction.resimulate.v1",
            "pcam.correction.replace-discard.v1",
        }:
            raise ValueError("unsupported server correction policy")
        if max_latency_compensation_ticks < 0:
            raise ValueError("correction limit must be nonnegative")
        self.correction_policy = correction_policy
        self.max_latency_compensation_ticks = max_latency_compensation_ticks

    def plan(
        self,
        current_tick: int,
        authoritative_tick: int,
        complete_state_supplied: bool,
    ) -> ServerCorrectionPlan:
        if authoritative_tick < 0 or authoritative_tick > current_tick:
            raise ValueError("authoritative correction tick is invalid")
        discard = current_tick - authoritative_tick
        if discard > self.max_latency_compensation_ticks:
            raise ValueError("authoritative correction exceeds compensation limit")
        if self.correction_policy == "pcam.correction.replace-discard.v1":
            if not complete_state_supplied:
                raise ValueError("replace-discard correction requires complete authoritative state")
            operation = "REPLACE_AND_DISCARD"
        else:
            operation = "RESTORE_AND_RESIMULATE"
        return ServerCorrectionPlan(operation, authoritative_tick, discard)


def _input_key(value: dict[str, object]) -> tuple[object, ...]:
    return (
        int(value.get("source_entity_id", 0)),
        int(value.get("sequence", 0)),
        str(value.get("command_id", "")).encode("utf-8"),
        str(value.get("input_id", "")).encode("utf-8"),
        canonical_dumps(value),
    )
