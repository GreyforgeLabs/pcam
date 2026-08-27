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
        return Err("usage: pcam-independent <canonicalize|hash> <file>".to_owned());
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
        _ => Err("unknown command".to_owned()),
    }
}
