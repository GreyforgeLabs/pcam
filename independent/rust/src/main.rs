use pcam_independent::simulation::SimulationRuntime;
use pcam_independent::{canonical_hash_json, canonicalize_json};
use serde_json::json;
use std::env;
use std::fs;
use std::process::ExitCode;

fn main() -> ExitCode {
    match run() {
        Ok(payload) => {
            println!(
                "{}",
                serde_json::to_string(&payload).expect("result serialization")
            );
            ExitCode::SUCCESS
        }
        Err(message) => {
            println!("{}", json!({"code": "INVALID_INPUT", "message": message}));
            ExitCode::from(2)
        }
    }
}

fn run() -> Result<serde_json::Value, String> {
    let arguments: Vec<String> = env::args().collect();
    if arguments.len() != 3 {
        return Err(
            "usage: pcam-independent <canonicalize|hash|simulation-manifest> <file>".to_owned(),
        );
    }
    let source = fs::read(&arguments[2]).map_err(|error| error.to_string())?;
    match arguments[1].as_str() {
        "canonicalize" => Ok(json!({
            "canonical": String::from_utf8(canonicalize_json(&source).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?,
            "code": "OK"
        })),
        "hash" => Ok(json!({
            "code": "OK",
            "sha256": canonical_hash_json(&source).map_err(|error| error.to_string())?
        })),
        "simulation-manifest" => simulation_manifest(&source),
        _ => Err("unknown command".to_owned()),
    }
}

fn simulation_manifest(source: &[u8]) -> Result<serde_json::Value, String> {
    let vector: serde_json::Value =
        serde_json::from_slice(source).map_err(|error| error.to_string())?;
    let runtime = SimulationRuntime::from_vector(&vector).map_err(|error| format!("{error:?}"))?;
    let mut state = runtime
        .initial_state(&vector)
        .map_err(|error| format!("{error:?}"))?;
    let definition_set_hash = state.definition_set_hash.clone();
    let mut tick_state_digests = Vec::new();
    for tick in vector["ticks"]
        .as_array()
        .ok_or_else(|| "runtime vector requires ticks".to_owned())?
    {
        let (next, trace) = runtime
            .tick(&state, tick)
            .map_err(|error| format!("{error:?}"))?;
        tick_state_digests.push(trace.state_digest);
        state = next;
    }
    Ok(json!({
        "code": "OK",
        "definition_set_hash": definition_set_hash,
        "final_state_digest": state.digest().map_err(|error| format!("{error:?}"))?,
        "tick_state_digests": tick_state_digests,
    }))
}
