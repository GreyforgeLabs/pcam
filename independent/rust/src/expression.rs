use crate::numeric::{NumericError, OverflowPolicy, apply_i64, euclidean_divmod};
use serde_json::{Map, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvalError {
    DivisionByZero,
    IntegerOverflow,
    StateInvariant,
}

pub fn evaluate(
    expression: &Value,
    context: &BTreeMap<String, Value>,
    max_depth: usize,
    max_nodes: usize,
) -> Result<Value, EvalError> {
    let mut budget = max_nodes;
    evaluate_inner(expression, context, 0, max_depth, &mut budget)
}

fn evaluate_inner(
    expression: &Value,
    context: &BTreeMap<String, Value>,
    depth: usize,
    max_depth: usize,
    budget: &mut usize,
) -> Result<Value, EvalError> {
    if depth > max_depth || *budget == 0 {
        return Err(EvalError::StateInvariant);
    }
    *budget -= 1;
    let object = expression.as_object().ok_or(EvalError::StateInvariant)?;
    if exact_keys(object, &["literal"]) {
        let literal = &object["literal"];
        validate_literal(literal)?;
        return Ok(literal.clone());
    }
    if exact_keys(object, &["ref"]) {
        let reference = object["ref"].as_str().ok_or(EvalError::StateInvariant)?;
        return context
            .get(reference)
            .cloned()
            .ok_or(EvalError::StateInvariant);
    }
    if !exact_keys(object, &["args", "op"]) {
        return Err(EvalError::StateInvariant);
    }
    let operator = object["op"].as_str().ok_or(EvalError::StateInvariant)?;
    let raw_args = object["args"].as_array().ok_or(EvalError::StateInvariant)?;
    let args = raw_args
        .iter()
        .map(|item| evaluate_inner(item, context, depth + 1, max_depth, budget))
        .collect::<Result<Vec<_>, _>>()?;
    apply(operator, &args)
}

fn apply(operator: &str, args: &[Value]) -> Result<Value, EvalError> {
    match operator {
        "and" => Ok(Value::Bool(
            args.iter()
                .map(boolean)
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .all(|item| item),
        )),
        "or" => Ok(Value::Bool(
            args.iter()
                .map(boolean)
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .any(|item| item),
        )),
        "not" => {
            arity(args, 1)?;
            Ok(Value::Bool(!boolean(&args[0])?))
        }
        "xor" => {
            arity(args, 2)?;
            Ok(Value::Bool(boolean(&args[0])? != boolean(&args[1])?))
        }
        "eq" | "ne" => {
            arity(args, 2)?;
            Ok(Value::Bool(if operator == "eq" {
                args[0] == args[1]
            } else {
                args[0] != args[1]
            }))
        }
        "lt" | "lte" | "gt" | "gte" => {
            arity(args, 2)?;
            let ordering = compare(&args[0], &args[1])?;
            let result = match operator {
                "lt" => ordering == Ordering::Less,
                "lte" => ordering != Ordering::Greater,
                "gt" => ordering == Ordering::Greater,
                _ => ordering != Ordering::Less,
            };
            Ok(Value::Bool(result))
        }
        "add" | "sub" | "mul" => {
            arity(args, 2)?;
            let left = integer(&args[0])? as i128;
            let right = integer(&args[1])? as i128;
            let value = match operator {
                "add" => left + right,
                "sub" => left - right,
                _ => left * right,
            };
            Ok(Value::from(
                apply_i64(value, OverflowPolicy::Fault).map_err(map_numeric)?,
            ))
        }
        "div" | "mod" => {
            arity(args, 2)?;
            let (quotient, remainder) =
                euclidean_divmod(integer(&args[0])?, integer(&args[1])?).map_err(map_numeric)?;
            Ok(Value::from(if operator == "div" {
                quotient
            } else {
                remainder
            }))
        }
        "min" | "max" => {
            if args.is_empty() {
                return Err(EvalError::StateInvariant);
            }
            let values = args.iter().map(integer).collect::<Result<Vec<_>, _>>()?;
            let value = if operator == "min" {
                values.into_iter().min()
            } else {
                values.into_iter().max()
            };
            Ok(Value::from(value.ok_or(EvalError::StateInvariant)?))
        }
        "clamp" => {
            arity(args, 3)?;
            let value = integer(&args[0])?;
            let lower = integer(&args[1])?;
            let upper = integer(&args[2])?;
            if lower > upper {
                return Err(EvalError::StateInvariant);
            }
            Ok(Value::from(value.clamp(lower, upper)))
        }
        "abs" => {
            arity(args, 1)?;
            let value = integer(&args[0])?;
            Ok(Value::from(
                apply_i64((value as i128).abs(), OverflowPolicy::Fault).map_err(map_numeric)?,
            ))
        }
        "contains" => {
            arity(args, 2)?;
            let values = args[0].as_array().ok_or(EvalError::StateInvariant)?;
            Ok(Value::Bool(values.contains(&args[1])))
        }
        "intersects" | "subset" | "union" | "difference" => {
            arity(args, 2)?;
            let left = symbol_set(&args[0])?;
            let right = symbol_set(&args[1])?;
            match operator {
                "intersects" => Ok(Value::Bool(!left.is_disjoint(&right))),
                "subset" => Ok(Value::Bool(left.is_subset(&right))),
                "union" => Ok(symbols(left.union(&right).cloned().collect())),
                _ => Ok(symbols(left.difference(&right).cloned().collect())),
            }
        }
        "if" => {
            arity(args, 3)?;
            Ok(if boolean(&args[0])? {
                args[1].clone()
            } else {
                args[2].clone()
            })
        }
        "coalesce" => {
            if args.is_empty() {
                return Err(EvalError::StateInvariant);
            }
            Ok(args
                .iter()
                .find(|item| !item.is_null())
                .cloned()
                .unwrap_or(Value::Null))
        }
        _ => Err(EvalError::StateInvariant),
    }
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> bool {
    object.len() == expected.len() && expected.iter().all(|key| object.contains_key(*key))
}

fn validate_literal(value: &Value) -> Result<(), EvalError> {
    match value {
        Value::Number(number) if !number.is_i64() && !number.is_u64() => {
            Err(EvalError::StateInvariant)
        }
        Value::Array(items) => items.iter().try_for_each(validate_literal),
        Value::Object(items) => items.values().try_for_each(validate_literal),
        _ => Ok(()),
    }
}

fn arity(args: &[Value], expected: usize) -> Result<(), EvalError> {
    if args.len() == expected {
        Ok(())
    } else {
        Err(EvalError::StateInvariant)
    }
}

fn boolean(value: &Value) -> Result<bool, EvalError> {
    value.as_bool().ok_or(EvalError::StateInvariant)
}

fn integer(value: &Value) -> Result<i64, EvalError> {
    value.as_i64().ok_or(EvalError::StateInvariant)
}

fn compare(left: &Value, right: &Value) -> Result<Ordering, EvalError> {
    if let (Some(left), Some(right)) = (left.as_i64(), right.as_i64()) {
        return Ok(left.cmp(&right));
    }
    if let (Some(left), Some(right)) = (left.as_str(), right.as_str()) {
        return Ok(left.cmp(right));
    }
    Err(EvalError::StateInvariant)
}

fn symbol_set(value: &Value) -> Result<BTreeSet<String>, EvalError> {
    value
        .as_array()
        .ok_or(EvalError::StateInvariant)?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_owned)
                .ok_or(EvalError::StateInvariant)
        })
        .collect()
}

fn symbols(values: BTreeSet<String>) -> Value {
    Value::Array(values.into_iter().map(Value::String).collect())
}

fn map_numeric(error: NumericError) -> EvalError {
    match error {
        NumericError::DivisionByZero => EvalError::DivisionByZero,
        NumericError::IntegerOverflow => EvalError::IntegerOverflow,
        NumericError::InvalidDivisor => EvalError::StateInvariant,
    }
}
