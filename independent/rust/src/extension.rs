use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExtensionError {
    ImplementationHashMismatch,
    IntegerOverflow,
}

pub fn verify_implementation(source: &[u8], expected_sha256: &str) -> Result<(), ExtensionError> {
    let actual: String = Sha256::digest(source)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    if actual == expected_sha256 {
        Ok(())
    } else {
        Err(ExtensionError::ImplementationHashMismatch)
    }
}

pub fn run_tick_counter(
    initial: u64,
    increment: u64,
    ticks: usize,
) -> Result<Vec<u64>, ExtensionError> {
    let mut counter = initial;
    let mut values = Vec::with_capacity(ticks);
    for _ in 0..ticks {
        counter = counter
            .checked_add(increment)
            .ok_or(ExtensionError::IntegerOverflow)?;
        values.push(counter);
    }
    Ok(values)
}
