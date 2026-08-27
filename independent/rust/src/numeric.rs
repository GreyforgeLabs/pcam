#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverflowPolicy {
    Fault,
    Saturate,
    Wrap,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NumericError {
    IntegerOverflow,
    DivisionByZero,
    InvalidDivisor,
}

pub fn apply_i64(value: i128, policy: OverflowPolicy) -> Result<i64, NumericError> {
    if (i64::MIN as i128..=i64::MAX as i128).contains(&value) {
        return Ok(value as i64);
    }
    match policy {
        OverflowPolicy::Fault => Err(NumericError::IntegerOverflow),
        OverflowPolicy::Saturate => Ok(value.clamp(i64::MIN as i128, i64::MAX as i128) as i64),
        OverflowPolicy::Wrap => {
            let modulus = 1_i128 << 64;
            Ok(value.rem_euclid(modulus) as u64 as i64)
        }
    }
}

pub fn apply_u64(value: i128, policy: OverflowPolicy) -> Result<u64, NumericError> {
    if (0..=u64::MAX as i128).contains(&value) {
        return Ok(value as u64);
    }
    match policy {
        OverflowPolicy::Fault => Err(NumericError::IntegerOverflow),
        OverflowPolicy::Saturate => Ok(value.clamp(0, u64::MAX as i128) as u64),
        OverflowPolicy::Wrap => Ok(value.rem_euclid(1_i128 << 64) as u64),
    }
}

pub fn euclidean_divmod(dividend: i64, divisor: i64) -> Result<(i64, i64), NumericError> {
    if divisor == 0 {
        return Err(NumericError::DivisionByZero);
    }
    if divisor < 0 {
        return Err(NumericError::InvalidDivisor);
    }
    Ok((dividend.div_euclid(divisor), dividend.rem_euclid(divisor)))
}

pub fn scale_ratio(value: i64, numerator: i64, denominator: u64) -> Result<i64, NumericError> {
    if denominator == 0 {
        return Err(NumericError::DivisionByZero);
    }
    let product = apply_i64(value as i128 * numerator as i128, OverflowPolicy::Fault)?;
    apply_i64(
        (product as i128).div_euclid(denominator as i128),
        OverflowPolicy::Fault,
    )
}
