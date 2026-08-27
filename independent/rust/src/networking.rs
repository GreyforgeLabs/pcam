use crate::{CanonicalError, canonical_hash, canonicalize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NetworkError {
    InvalidProfile,
    Aborted,
    UnknownPeer,
    TickMismatch,
    DefinitionMismatch,
    DuplicatePacket,
    InputTickMismatch,
    HostMismatch,
    DuplicateInput,
    DigestNotDue,
    DuplicateDigest,
    LocalDigestChanged,
    InvalidCorrection,
    CorrectionWindowExceeded,
    CompleteStateRequired,
    Canonical(CanonicalError),
}

impl From<CanonicalError> for NetworkError {
    fn from(error: CanonicalError) -> Self {
        Self::Canonical(error)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LockstepTick {
    pub status: String,
    pub tick: u64,
    pub tick_document: Option<Value>,
    pub missing_peers: Vec<String>,
    pub predicted_peers: Vec<String>,
    pub digest_due: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DigestResolution {
    pub status: String,
    pub tick: u64,
    pub mismatched_peers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerCorrectionPlan {
    pub operation: String,
    pub authoritative_tick: u64,
    pub discard_prediction_ticks: u64,
}

#[derive(Debug, Clone)]
struct PeerPacket {
    inputs: Vec<Value>,
    contacts: Vec<Value>,
}

#[derive(Debug, Clone)]
pub struct LockstepCoordinator {
    required_peers: Vec<String>,
    definition_set_hash: String,
    input_availability_policy: String,
    digest_interval_ticks: u64,
    desynchronization_policy: String,
    pub next_tick: u64,
    pub aborted: bool,
    packets: BTreeMap<String, PeerPacket>,
    digest_ticks: BTreeSet<u64>,
    digest_reports: BTreeMap<u64, BTreeMap<String, String>>,
    local_digests: BTreeMap<u64, String>,
}

impl LockstepCoordinator {
    pub fn new(
        mut required_peers: Vec<String>,
        definition_set_hash: String,
        input_availability_policy: &str,
        digest_interval_ticks: u64,
        desynchronization_policy: &str,
        predictor_id: Option<&str>,
    ) -> Result<Self, NetworkError> {
        required_peers.sort_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
        if required_peers.is_empty()
            || required_peers.windows(2).any(|pair| pair[0] == pair[1])
            || !matches!(input_availability_policy, "WAIT" | "PREDICT")
            || digest_interval_ticks == 0
            || !matches!(
                desynchronization_policy,
                "pcam.desync.abort" | "pcam.desync.report"
            )
            || (input_availability_policy == "PREDICT"
                && predictor_id != Some("pcam.predict.no-input.v1"))
        {
            return Err(NetworkError::InvalidProfile);
        }
        Ok(Self {
            required_peers,
            definition_set_hash,
            input_availability_policy: input_availability_policy.to_owned(),
            digest_interval_ticks,
            desynchronization_policy: desynchronization_policy.to_owned(),
            next_tick: 0,
            aborted: false,
            packets: BTreeMap::new(),
            digest_ticks: BTreeSet::new(),
            digest_reports: BTreeMap::new(),
            local_digests: BTreeMap::new(),
        })
    }

    pub fn submit(
        &mut self,
        peer_id: &str,
        tick: u64,
        definition_set_hash: &str,
        inputs: &[Value],
        contacts: &[Value],
    ) -> Result<(), NetworkError> {
        self.require_active()?;
        if !self.required_peers.iter().any(|peer| peer == peer_id) {
            return Err(NetworkError::UnknownPeer);
        }
        if tick != self.next_tick {
            return Err(NetworkError::TickMismatch);
        }
        if definition_set_hash != self.definition_set_hash {
            return Err(NetworkError::DefinitionMismatch);
        }
        if self.packets.contains_key(peer_id) {
            return Err(NetworkError::DuplicatePacket);
        }
        if inputs
            .iter()
            .any(|input| input["assigned_tick"].as_u64() != Some(tick))
        {
            return Err(NetworkError::InputTickMismatch);
        }
        for input in inputs {
            canonicalize(input)?;
        }
        self.packets.insert(
            peer_id.to_owned(),
            PeerPacket {
                inputs: inputs.to_vec(),
                contacts: contacts.to_vec(),
            },
        );
        Ok(())
    }

    pub fn advance(&mut self) -> Result<LockstepTick, NetworkError> {
        self.require_active()?;
        let missing = self
            .required_peers
            .iter()
            .filter(|peer| !self.packets.contains_key(*peer))
            .cloned()
            .collect::<Vec<_>>();
        if !missing.is_empty() && self.input_availability_policy == "WAIT" {
            return Ok(LockstepTick {
                status: "WAITING".to_owned(),
                tick: self.next_tick,
                tick_document: None,
                missing_peers: missing,
                predicted_peers: Vec::new(),
                digest_due: false,
            });
        }
        let packets = self
            .required_peers
            .iter()
            .filter_map(|peer| self.packets.get(peer))
            .collect::<Vec<_>>();
        let host_hashes = packets
            .iter()
            .map(|packet| canonical_hash(&Value::Array(packet.contacts.clone())))
            .collect::<Result<BTreeSet<_>, _>>()?;
        if host_hashes.len() > 1 {
            return Err(NetworkError::HostMismatch);
        }
        let contacts = packets
            .first()
            .map(|packet| packet.contacts.clone())
            .unwrap_or_default();
        let mut inputs = packets
            .iter()
            .flat_map(|packet| packet.inputs.iter().cloned())
            .collect::<Vec<_>>();
        let identifiers = inputs
            .iter()
            .map(|input| input["input_id"].as_str().unwrap_or_default())
            .collect::<Vec<_>>();
        if identifiers.len() != identifiers.iter().collect::<BTreeSet<_>>().len() {
            return Err(NetworkError::DuplicateInput);
        }
        inputs.sort_by(|left, right| input_key(left).cmp(&input_key(right)));
        let tick = self.next_tick;
        let digest_due = (tick + 1) % self.digest_interval_ticks == 0;
        self.packets.clear();
        self.next_tick += 1;
        if digest_due {
            self.digest_ticks.insert(tick);
        }
        Ok(LockstepTick {
            status: "READY".to_owned(),
            tick,
            tick_document: Some(json!({"inputs": inputs, "contacts": contacts})),
            missing_peers: Vec::new(),
            predicted_peers: missing,
            digest_due,
        })
    }

    pub fn submit_digest(
        &mut self,
        peer_id: &str,
        tick: u64,
        reported_digest: &str,
        local_digest: &str,
    ) -> Result<DigestResolution, NetworkError> {
        self.require_active()?;
        if !self.required_peers.iter().any(|peer| peer == peer_id) {
            return Err(NetworkError::UnknownPeer);
        }
        if !self.digest_ticks.contains(&tick) {
            return Err(NetworkError::DigestNotDue);
        }
        match self.local_digests.get(&tick) {
            Some(known) if known != local_digest => return Err(NetworkError::LocalDigestChanged),
            None => {
                self.local_digests.insert(tick, local_digest.to_owned());
            }
            _ => {}
        }
        let reports = self.digest_reports.entry(tick).or_default();
        if reports.contains_key(peer_id) {
            return Err(NetworkError::DuplicateDigest);
        }
        reports.insert(peer_id.to_owned(), reported_digest.to_owned());
        if reports.len() < self.required_peers.len() {
            return Ok(DigestResolution {
                status: "WAITING".to_owned(),
                tick,
                mismatched_peers: Vec::new(),
            });
        }
        let mismatched = self
            .required_peers
            .iter()
            .filter(|peer| reports[*peer] != local_digest)
            .cloned()
            .collect::<Vec<_>>();
        let status = if mismatched.is_empty() {
            "MATCH"
        } else if self.desynchronization_policy == "pcam.desync.abort" {
            self.aborted = true;
            "ABORTED"
        } else {
            "REPORTED"
        };
        Ok(DigestResolution {
            status: status.to_owned(),
            tick,
            mismatched_peers: mismatched,
        })
    }

    fn require_active(&self) -> Result<(), NetworkError> {
        if self.aborted {
            Err(NetworkError::Aborted)
        } else {
            Ok(())
        }
    }
}

#[derive(Debug, Clone)]
pub struct ServerAuthoritativeCorrectionPlanner {
    correction_policy: String,
    max_latency_compensation_ticks: u64,
}

impl ServerAuthoritativeCorrectionPlanner {
    pub fn new(
        correction_policy: &str,
        max_latency_compensation_ticks: u64,
    ) -> Result<Self, NetworkError> {
        if !matches!(
            correction_policy,
            "pcam.correction.resimulate.v1" | "pcam.correction.replace-discard.v1"
        ) {
            return Err(NetworkError::InvalidProfile);
        }
        Ok(Self {
            correction_policy: correction_policy.to_owned(),
            max_latency_compensation_ticks,
        })
    }

    pub fn plan(
        &self,
        current_tick: u64,
        authoritative_tick: u64,
        complete_state_supplied: bool,
    ) -> Result<ServerCorrectionPlan, NetworkError> {
        if authoritative_tick > current_tick {
            return Err(NetworkError::InvalidCorrection);
        }
        let discard = current_tick - authoritative_tick;
        if discard > self.max_latency_compensation_ticks {
            return Err(NetworkError::CorrectionWindowExceeded);
        }
        let operation = if self.correction_policy == "pcam.correction.replace-discard.v1" {
            if !complete_state_supplied {
                return Err(NetworkError::CompleteStateRequired);
            }
            "REPLACE_AND_DISCARD"
        } else {
            "RESTORE_AND_RESIMULATE"
        };
        Ok(ServerCorrectionPlan {
            operation: operation.to_owned(),
            authoritative_tick,
            discard_prediction_ticks: discard,
        })
    }
}

fn input_key(value: &Value) -> (u64, u64, Vec<u8>, Vec<u8>, Vec<u8>) {
    (
        value["source_entity_id"].as_u64().unwrap_or_default(),
        value["sequence"].as_u64().unwrap_or_default(),
        value["command_id"]
            .as_str()
            .unwrap_or_default()
            .as_bytes()
            .to_vec(),
        value["input_id"]
            .as_str()
            .unwrap_or_default()
            .as_bytes()
            .to_vec(),
        canonicalize(value).unwrap_or_default(),
    )
}
