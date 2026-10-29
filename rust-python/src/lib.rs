use chrono::NaiveDate;
use codexbar_core::{activity, providers};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use serde_json::Value;
use std::collections::HashMap;

#[pyfunction]
fn canonical_id(provider_id: &str) -> String {
    providers::canonical_id(provider_id).to_owned()
}

#[pyfunction]
fn display_name(provider_id: &str) -> String {
    providers::display_name(provider_id)
}

#[pyfunction]
fn short_name(provider_id: &str) -> String {
    providers::short_name(provider_id)
}

#[pyfunction]
fn accent_color(provider_id: &str) -> String {
    providers::accent_color(provider_id).to_owned()
}

#[pyfunction]
fn all_provider_ids() -> Vec<String> {
    providers::all_provider_ids()
        .into_iter()
        .map(str::to_owned)
        .collect()
}

#[pyfunction]
fn backend_name() -> &'static str {
    "rust"
}

#[pyfunction]
fn activity_levels(values: Vec<i64>) -> Vec<i64> {
    activity::activity_levels(&values)
        .into_iter()
        .map(i64::from)
        .collect()
}

#[pyfunction]
fn weekly_totals(start: &str, values: Vec<(String, i64)>, today: &str) -> PyResult<Vec<i64>> {
    let start = parse_date(start)?;
    let today = parse_date(today)?;
    let mut by_date = HashMap::with_capacity(values.len());
    for (date, value) in values {
        by_date.insert(parse_date(&date)?, value);
    }
    Ok(activity::weekly_totals(start, &by_date, today))
}

#[pyfunction]
fn cumulative_totals(values: Vec<i64>) -> Vec<i64> {
    activity::cumulative_totals(&values)
}

#[pyfunction]
fn daily_series(
    entries_json: &str,
    days: Option<i64>,
    history_coverage_established: bool,
) -> PyResult<Vec<(String, Option<f64>)>> {
    let raw_entries: Vec<Value> = serde_json::from_str(entries_json)
        .map_err(|error| PyValueError::new_err(format!("invalid activity entries: {error}")))?;
    let entries: Vec<activity::DailyCostEntry> = raw_entries
        .into_iter()
        .filter_map(|raw| {
            let Value::Object(object) = raw else {
                return None;
            };
            Some(activity::DailyCostEntry {
                date: python_string(object.get("date")),
                total_cost: python_float(object.get("totalCost")),
            })
        })
        .collect();
    Ok(
        activity::daily_series(&entries, days, history_coverage_established)
            .into_iter()
            .map(|point| (point.date.to_string(), point.cost))
            .collect(),
    )
}

#[pyfunction]
fn align_start(today: &str) -> PyResult<String> {
    Ok(activity::align_start(parse_date(today)?).to_string())
}

fn parse_date(value: &str) -> PyResult<NaiveDate> {
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .map_err(|error| PyValueError::new_err(format!("invalid date {value:?}: {error}")))
}

fn python_string(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(value)) => value.clone(),
        Some(Value::Bool(value)) => if *value { "True" } else { "False" }.to_owned(),
        Some(Value::Number(value)) => value.to_string(),
        Some(Value::Array(_)) | Some(Value::Object(_)) => value.unwrap().to_string(),
    }
}

fn python_float(value: Option<&Value>) -> Option<f64> {
    match value? {
        Value::Null => None,
        Value::Number(value) => value.as_f64(),
        Value::String(value) => value.trim().parse().ok(),
        Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
        Value::Array(_) | Value::Object(_) => None,
    }
}

#[pymodule]
fn _rust_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(canonical_id, module)?)?;
    module.add_function(wrap_pyfunction!(display_name, module)?)?;
    module.add_function(wrap_pyfunction!(short_name, module)?)?;
    module.add_function(wrap_pyfunction!(accent_color, module)?)?;
    module.add_function(wrap_pyfunction!(all_provider_ids, module)?)?;
    module.add_function(wrap_pyfunction!(backend_name, module)?)?;
    module.add_function(wrap_pyfunction!(activity_levels, module)?)?;
    module.add_function(wrap_pyfunction!(weekly_totals, module)?)?;
    module.add_function(wrap_pyfunction!(cumulative_totals, module)?)?;
    module.add_function(wrap_pyfunction!(daily_series, module)?)?;
    module.add_function(wrap_pyfunction!(align_start, module)?)?;
    Ok(())
}
