use chrono::{DateTime, NaiveDate, Utc};
use codexbar_core::{activity, charts, domain, formatting, history, pace, providers};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyDict, PyFloat, PyInt};
use serde_json::Value;
use std::collections::HashMap;
use std::path::PathBuf;

type HistorySample = (f64, String, String, f64);
type PaceTuple = (
    String,
    Option<f64>,
    Option<f64>,
    bool,
    Option<f64>,
    Option<f64>,
    Option<String>,
);
type RateWindowTuple = (
    String,
    String,
    f64,
    Option<String>,
    Option<String>,
    Option<i64>,
    Option<f64>,
    bool,
    Option<f64>,
    Option<String>,
    bool,
);

#[pyclass(name = "HistoryStore")]
struct RustHistoryStore {
    inner: history::HistoryStore,
}

#[pymethods]
impl RustHistoryStore {
    #[new]
    fn new(path: PathBuf, retention_days: i64) -> Self {
        Self {
            inner: history::HistoryStore::new(path, retention_days),
        }
    }

    fn append(&self, samples: Vec<HistorySample>) {
        let samples: Vec<_> = samples
            .into_iter()
            .map(
                |(timestamp, provider, window, used_percent)| history::Sample {
                    timestamp,
                    provider,
                    window,
                    used_percent,
                },
            )
            .collect();
        self.inner.append(&samples);
    }

    fn read_all(&self) -> Vec<HistorySample> {
        self.inner
            .read_all()
            .into_iter()
            .map(|sample| {
                (
                    sample.timestamp,
                    sample.provider,
                    sample.window,
                    sample.used_percent,
                )
            })
            .collect()
    }

    fn prune(&self, now: f64) {
        self.inner.prune_at(now);
    }

    fn series(&self, provider: &str, window: &str, hours: f64, now: f64) -> Vec<(f64, f64)> {
        self.inner.series_at(provider, window, hours, now)
    }
}

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
fn pace_from_json(payload: &str) -> Option<PaceTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let pace = domain::pace_from_value(&payload)?;
    Some((
        pace.stage,
        pace.delta_percent,
        pace.expected_used_percent,
        pace.will_last_to_reset,
        pace.eta_seconds,
        pace.run_out_probability,
        pace.summary,
    ))
}

#[pyfunction]
fn rate_window_from_json(payload: &str, key: &str, title: Option<&str>) -> Option<RateWindowTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let window = domain::rate_window_from_value(&payload, key, title)?;
    Some((
        window.key,
        window.title,
        window.used_percent,
        window
            .resets_at
            .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
        window.reset_description,
        window.window_minutes,
        window.next_regen_percent,
        window.is_placeholder,
        window.quota_limit,
        window.quota_unit,
        window.usage_known,
    ))
}

#[pyfunction]
fn parse_timestamp(value: Option<&str>) -> Option<String> {
    domain::parse_timestamp(value)
        .map(|timestamp| timestamp.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true))
}

fn python_number_as_json(value: &Bound<'_, PyAny>) -> Option<Value> {
    if value.is_instance_of::<PyBool>()
        || !(value.is_instance_of::<PyInt>() || value.is_instance_of::<PyFloat>())
    {
        return None;
    }
    let number = value.extract::<f64>().ok()?;
    serde_json::Number::from_f64(number).map(Value::Number)
}

#[pyfunction]
fn optional_float(value: &Bound<'_, PyAny>) -> Option<f64> {
    domain::optional_float(python_number_as_json(value).as_ref())
}

#[pyfunction]
fn optional_int(value: &Bound<'_, PyAny>) -> Option<i64> {
    domain::optional_i64(python_number_as_json(value).as_ref())
}

#[pyfunction]
fn provider_usage_has_error(error: Option<&str>) -> bool {
    domain::ProviderUsage::error_is_present(error)
}

#[pyfunction]
fn provider_usage_max_used_percent(values: Vec<f64>) -> f64 {
    domain::ProviderUsage::max_used_from(values)
}

#[pyfunction]
fn provider_usage_subtitle(plan: Option<&str>, account_email: Option<&str>) -> String {
    domain::ProviderUsage::subtitle_for(plan, account_email)
}

#[pyfunction]
fn detail_chart_peak(points: Vec<(String, f64)>) -> f64 {
    domain::DetailChart::peak_for(&points)
}

#[pyfunction]
fn agent_session_is_running(state: &str) -> bool {
    domain::AgentSession::state_is_running(state)
}

#[pyfunction]
fn pace_stage_is_deficit(stage: &str) -> bool {
    domain::Pace::stage_is_deficit(stage)
}

#[pyfunction]
fn pace_stage_is_reserve(stage: &str) -> bool {
    domain::Pace::stage_is_reserve(stage)
}

#[pyfunction]
fn pace_stage_label(stage: &str) -> String {
    domain::Pace::label_for_stage(stage).to_owned()
}

#[pyfunction]
fn cost_info_has_limit(limit: f64) -> bool {
    domain::CostInfo::limit_is_usable(limit)
}

#[pyfunction]
fn cost_info_used_percent(used: f64, limit: f64) -> f64 {
    domain::CostInfo::percent_used(used, limit)
}

#[pyfunction]
fn rate_window_remaining_percent(used_percent: f64) -> f64 {
    (100.0 - used_percent).max(0.0)
}

#[pyfunction]
fn rate_window_duration_label(window_minutes: Option<i64>) -> Option<String> {
    domain::RateWindow {
        key: String::new(),
        title: String::new(),
        used_percent: 0.0,
        resets_at: None,
        reset_description: None,
        window_minutes,
        next_regen_percent: None,
        is_placeholder: false,
        quota_limit: None,
        quota_unit: None,
        usage_known: true,
    }
    .duration_label()
}

#[pyfunction]
fn backend_name() -> &'static str {
    "rust"
}

#[pyfunction]
fn sparkline_coordinates(points: Vec<(f64, f64)>, width: i64, height: i64) -> Vec<(f64, f64)> {
    charts::sparkline_coordinates(&points, width, height)
}

#[pyfunction]
fn compact_window_label(title: Option<String>, window_minutes: Option<i64>) -> Option<String> {
    formatting::compact_window_label(title.as_deref(), window_minutes)
}

#[pyfunction]
fn format_percent(value: Option<f64>, decimals: usize) -> String {
    formatting::format_percent(value, decimals)
}

#[pyfunction]
fn format_remaining(used_percent: Option<f64>, decimals: usize) -> String {
    formatting::format_remaining(used_percent, decimals)
}

#[pyfunction]
fn format_countdown(target: Option<String>, now: &str) -> PyResult<Option<String>> {
    Ok(formatting::format_countdown(
        parse_datetime(target.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn format_absolute(target: Option<String>, now: &str) -> PyResult<Option<String>> {
    Ok(formatting::format_absolute(
        parse_datetime(target.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn format_reset(target: Option<String>, style: &str, now: &str) -> PyResult<Option<String>> {
    Ok(formatting::format_reset(
        parse_datetime(target.as_deref())?,
        style,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn format_currency(value: Option<f64>, currency: &str, compact: bool) -> String {
    formatting::format_currency(value, currency, compact)
}

#[pyfunction]
fn format_credits(value: Option<f64>) -> String {
    formatting::format_credits(value)
}

#[pyfunction]
fn format_tokens(value: Option<u64>) -> String {
    formatting::format_tokens(value)
}

#[pyfunction]
fn format_updated(target: Option<String>, now: &str) -> PyResult<Option<String>> {
    Ok(formatting::format_updated(
        parse_datetime(target.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn format_reset_credits(
    expirations: Vec<Option<String>>,
    style: &str,
    now: &str,
) -> PyResult<Option<(String, String, Vec<String>)>> {
    let expirations = expirations
        .iter()
        .map(|value| parse_datetime(value.as_deref()))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(formatting::format_reset_credits(
        &expirations,
        style,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn format_pace(
    stage: &str,
    delta_percent: Option<f64>,
    in_deficit: bool,
    in_reserve: bool,
    stage_label: &str,
) -> String {
    formatting::format_pace(stage, delta_percent, in_deficit, in_reserve, stage_label)
}

#[pyfunction]
fn format_window_span(minutes: Option<i64>) -> Option<String> {
    formatting::format_window_span(minutes)
}

#[pyfunction]
fn next_refresh_seconds(interval_seconds: i64) -> i64 {
    formatting::next_refresh_seconds(interval_seconds)
}

#[pyfunction]
fn workday_progress_percent(
    resets_at: Option<String>,
    now: &str,
    work_days: u32,
) -> PyResult<Option<f64>> {
    Ok(formatting::workday_progress_percent(
        parse_datetime(resets_at.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
        work_days,
    ))
}

#[pyfunction]
fn project_usage_at_reset(
    used_percent: f64,
    samples: Vec<(f64, f64)>,
    resets_at: Option<String>,
    now: &str,
) -> PyResult<Option<f64>> {
    Ok(formatting::project_usage_at_reset(
        used_percent,
        &samples,
        parse_datetime(resets_at.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn pace_is_monthly_window(window_minutes: Option<i64>) -> bool {
    pace::is_monthly_window(window_minutes)
}

#[pyfunction]
fn pace_daily_target(
    remaining: Option<f64>,
    resets_at: Option<String>,
    now: &str,
) -> PyResult<Option<f64>> {
    Ok(pace::daily_target(
        remaining,
        parse_datetime(resets_at.as_deref())?,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn pace_window_daily_target(data: &Bound<'_, PyDict>, now: &str) -> PyResult<Option<f64>> {
    macro_rules! field {
        ($name:literal) => {
            data.get_item($name)?
                .ok_or_else(|| PyValueError::new_err(concat!("missing window field ", $name)))?
        };
    }
    let is_placeholder = field!("is_placeholder").extract()?;
    let usage_known = field!("usage_known").extract()?;
    let window_minutes = field!("window_minutes").extract()?;
    let used_percent = field!("used_percent").extract()?;
    let quota_limit = field!("quota_limit").extract()?;
    let quota_unit = field!("quota_unit").extract()?;
    let resets_at: Option<String> = field!("resets_at").extract()?;
    let window = pace::AllowanceWindow {
        is_placeholder,
        usage_known,
        window_minutes,
        used_percent,
        quota_limit,
        quota_unit,
        resets_at: parse_datetime(resets_at.as_deref())?,
    };
    Ok(pace::window_daily_target(
        &window,
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn pace_monthly_cost_daily_target(
    used: f64,
    limit: f64,
    currency: String,
    period: Option<String>,
    resets_at: Option<String>,
    now: &str,
) -> PyResult<Option<f64>> {
    let cost = pace::MonthlyCost {
        used,
        limit,
        currency,
        period,
        resets_at: parse_datetime(resets_at.as_deref())?,
    };
    Ok(pace::monthly_cost_daily_target(
        Some(&cost),
        parse_datetime(Some(now))?.expect("now is required"),
    ))
}

#[pyfunction]
fn pace_format_daily_target(
    target: Option<f64>,
    unit: Option<String>,
    preferred_currency: &str,
    converted_value: Option<f64>,
) -> Option<String> {
    let convert = |_: f64, _: &str, _: &str| converted_value;
    pace::format_daily_target(target, unit.as_deref(), preferred_currency, &convert)
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

fn parse_datetime(value: Option<&str>) -> PyResult<Option<DateTime<Utc>>> {
    value
        .map(|value| {
            DateTime::parse_from_rfc3339(value)
                .map(|datetime| datetime.with_timezone(&Utc))
                .map_err(|error| {
                    PyValueError::new_err(format!("invalid datetime {value:?}: {error}"))
                })
        })
        .transpose()
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
    module.add_class::<RustHistoryStore>()?;
    module.add_function(wrap_pyfunction!(sparkline_coordinates, module)?)?;
    module.add_function(wrap_pyfunction!(canonical_id, module)?)?;
    module.add_function(wrap_pyfunction!(display_name, module)?)?;
    module.add_function(wrap_pyfunction!(short_name, module)?)?;
    module.add_function(wrap_pyfunction!(accent_color, module)?)?;
    module.add_function(wrap_pyfunction!(all_provider_ids, module)?)?;
    module.add_function(wrap_pyfunction!(backend_name, module)?)?;
    module.add_function(wrap_pyfunction!(parse_timestamp, module)?)?;
    module.add_function(wrap_pyfunction!(rate_window_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(pace_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(optional_float, module)?)?;
    module.add_function(wrap_pyfunction!(optional_int, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_has_error, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_max_used_percent, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_subtitle, module)?)?;
    module.add_function(wrap_pyfunction!(detail_chart_peak, module)?)?;
    module.add_function(wrap_pyfunction!(agent_session_is_running, module)?)?;
    module.add_function(wrap_pyfunction!(pace_stage_is_deficit, module)?)?;
    module.add_function(wrap_pyfunction!(pace_stage_is_reserve, module)?)?;
    module.add_function(wrap_pyfunction!(pace_stage_label, module)?)?;
    module.add_function(wrap_pyfunction!(cost_info_has_limit, module)?)?;
    module.add_function(wrap_pyfunction!(cost_info_used_percent, module)?)?;
    module.add_function(wrap_pyfunction!(rate_window_remaining_percent, module)?)?;
    module.add_function(wrap_pyfunction!(rate_window_duration_label, module)?)?;
    module.add_function(wrap_pyfunction!(compact_window_label, module)?)?;
    module.add_function(wrap_pyfunction!(format_percent, module)?)?;
    module.add_function(wrap_pyfunction!(format_remaining, module)?)?;
    module.add_function(wrap_pyfunction!(format_countdown, module)?)?;
    module.add_function(wrap_pyfunction!(format_absolute, module)?)?;
    module.add_function(wrap_pyfunction!(format_reset, module)?)?;
    module.add_function(wrap_pyfunction!(format_currency, module)?)?;
    module.add_function(wrap_pyfunction!(format_credits, module)?)?;
    module.add_function(wrap_pyfunction!(format_tokens, module)?)?;
    module.add_function(wrap_pyfunction!(format_updated, module)?)?;
    module.add_function(wrap_pyfunction!(format_reset_credits, module)?)?;
    module.add_function(wrap_pyfunction!(format_pace, module)?)?;
    module.add_function(wrap_pyfunction!(format_window_span, module)?)?;
    module.add_function(wrap_pyfunction!(next_refresh_seconds, module)?)?;
    module.add_function(wrap_pyfunction!(workday_progress_percent, module)?)?;
    module.add_function(wrap_pyfunction!(project_usage_at_reset, module)?)?;
    module.add_function(wrap_pyfunction!(pace_is_monthly_window, module)?)?;
    module.add_function(wrap_pyfunction!(pace_daily_target, module)?)?;
    module.add_function(wrap_pyfunction!(pace_window_daily_target, module)?)?;
    module.add_function(wrap_pyfunction!(pace_monthly_cost_daily_target, module)?)?;
    module.add_function(wrap_pyfunction!(pace_format_daily_target, module)?)?;
    module.add_function(wrap_pyfunction!(activity_levels, module)?)?;
    module.add_function(wrap_pyfunction!(weekly_totals, module)?)?;
    module.add_function(wrap_pyfunction!(cumulative_totals, module)?)?;
    module.add_function(wrap_pyfunction!(daily_series, module)?)?;
    module.add_function(wrap_pyfunction!(align_start, module)?)?;
    Ok(())
}
