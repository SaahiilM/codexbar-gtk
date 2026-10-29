//! Shared domain primitives and strict payload-number helpers.
//!
//! The Python reference currently accepts `datetime.fromisoformat` inputs and
//! normalizes naive timestamps as UTC. Rust's accepted timestamp grammar is
//! intentionally explicit here; transitional callers retain a Python fallback
//! for valid ISO forms not accepted by this parser.

use std::collections::HashMap;

use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use serde_json::Value;

fn python_max(values: impl IntoIterator<Item = f64>, default: f64) -> f64 {
    let mut values = values.into_iter();
    let Some(first) = values.next() else {
        return default;
    };
    values.fold(
        first,
        |largest, value| if value > largest { value } else { largest },
    )
}

/// Parse an ISO timestamp into UTC.
///
/// Supports RFC 3339 offsets, `Z`, naive date/time forms (interpreted as UTC),
/// fractional seconds, and date-only values. Whitespace surrounding the value
/// is ignored. Invalid input returns `None` rather than a fabricated epoch.
pub fn parse_timestamp(value: Option<&str>) -> Option<DateTime<Utc>> {
    let text = value?.trim();
    if text.is_empty() {
        return None;
    }

    let normalized = text.strip_suffix('Z').map(|s| format!("{s}+00:00"));
    let input = normalized.as_deref().unwrap_or(text);

    if let Ok(timestamp) = DateTime::parse_from_rfc3339(input) {
        return Some(timestamp.with_timezone(&Utc));
    }

    // Python datetime.fromisoformat accepts both T and a space as separators.
    for pattern in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(datetime) = NaiveDateTime::parse_from_str(input, pattern) {
            return Some(datetime.and_utc());
        }
    }

    NaiveDate::parse_from_str(input, "%Y-%m-%d")
        .ok()
        .and_then(|date| date.and_hms_opt(0, 0, 0))
        .map(|datetime| datetime.and_utc())
}

/// Return a finite JSON number, rejecting booleans and strings.
pub fn optional_float(value: Option<&Value>) -> Option<f64> {
    let value = value?;
    let number = value.as_number()?.as_f64()?;
    number.is_finite().then_some(number)
}

/// Return an integral JSON number that fits in `i64`.
///
/// Python's integer type is unbounded; Rust domain durations use `i64`. Values
/// outside that range remain available to the Python compatibility fallback.
pub fn optional_i64(value: Option<&Value>) -> Option<i64> {
    let number = optional_float(value)?;
    if !number.fract().eq(&0.0) || number < i64::MIN as f64 || number >= -(i64::MIN as f64) {
        return None;
    }
    Some(number as i64)
}

/// Pace forecast for a quota window.
#[derive(Clone, Debug, PartialEq)]
pub struct Pace {
    pub stage: String,
    pub delta_percent: Option<f64>,
    pub expected_used_percent: Option<f64>,
    pub will_last_to_reset: bool,
    pub eta_seconds: Option<f64>,
    pub run_out_probability: Option<f64>,
    pub summary: Option<String>,
}

impl Pace {
    pub fn in_deficit(&self) -> bool {
        Self::stage_is_deficit(&self.stage)
    }

    pub fn stage_is_deficit(stage: &str) -> bool {
        matches!(stage, "slightlyAhead" | "ahead" | "farAhead")
    }

    pub fn in_reserve(&self) -> bool {
        Self::stage_is_reserve(&self.stage)
    }

    pub fn stage_is_reserve(stage: &str) -> bool {
        matches!(stage, "slightlyBehind" | "behind" | "farBehind")
    }

    pub fn stage_label(&self) -> &str {
        Self::label_for_stage(&self.stage)
    }

    pub fn label_for_stage(stage: &str) -> &str {
        match stage {
            "onTrack" => "On pace",
            "slightlyAhead" | "ahead" => "In deficit",
            "farAhead" => "Well in deficit",
            "slightlyBehind" | "behind" => "In reserve",
            "farBehind" => "Well in reserve",
            other => other,
        }
    }
}

/// Normalize a provider pace object when its dynamic fields match the typed
/// Rust contract. Unsupported field shapes are left for the Python fallback.
pub fn pace_from_value(value: &Value) -> Option<Pace> {
    let object = value.as_object()?;
    let stage = object.get("stage")?.as_str()?.to_owned();
    if stage.is_empty() {
        return None;
    }
    for key in [
        "deltaPercent",
        "expectedUsedPercent",
        "etaSeconds",
        "runOutProbability",
    ] {
        if let Some(raw) = object.get(key) {
            if !raw.is_null() && optional_float(Some(raw)).is_none() {
                return None;
            }
        }
    }
    let summary = match object.get("summary") {
        Some(Value::String(summary)) => Some(summary.clone()),
        None | Some(Value::Null) => None,
        _ => return None,
    };
    Some(Pace {
        stage,
        delta_percent: optional_float(object.get("deltaPercent")),
        expected_used_percent: optional_float(object.get("expectedUsedPercent")),
        will_last_to_reset: object
            .get("willLastToReset")
            .map(json_truthy)
            .unwrap_or(true),
        eta_seconds: optional_float(object.get("etaSeconds")),
        run_out_probability: optional_float(object.get("runOutProbability")),
        summary,
    })
}

/// Provider cost/limit data. A zero or negative limit is not a usable cap.
#[derive(Clone, Debug, PartialEq)]
pub struct CostInfo {
    pub used: f64,
    pub limit: f64,
    pub currency: String,
    pub period: Option<String>,
    pub balance: Option<f64>,
    pub personal_used: Option<f64>,
    pub resets_at: Option<DateTime<Utc>>,
}

impl CostInfo {
    pub fn has_limit(&self) -> bool {
        Self::limit_is_usable(self.limit)
    }

    pub fn limit_is_usable(limit: f64) -> bool {
        limit > 0.0
    }

    pub fn used_percent(&self) -> f64 {
        Self::percent_used(self.used, self.limit)
    }

    pub fn percent_used(used: f64, limit: f64) -> f64 {
        if !Self::limit_is_usable(limit) {
            return 0.0;
        }
        let percent = used / limit * 100.0;
        if percent.is_nan() || percent > 100.0 {
            100.0
        } else if percent < 0.0 {
            0.0
        } else {
            percent
        }
    }
}

/// Normalize one CLI ``providerCost`` envelope into a typed cost snapshot.
///
/// Python's float conversion tolerates non-numeric values by falling back to
/// 0.0; Rust's optional_float rejects them, so callers should use the Python
/// fallback when this returns None.
pub fn cost_from_value(value: &Value) -> Option<CostInfo> {
    let object = value.as_object()?;
    let used = optional_float(object.get("used")).unwrap_or(0.0);
    let limit = optional_float(object.get("limit")).unwrap_or(0.0);
    let currency = object
        .get("currencyCode")
        .or_else(|| object.get("currency"))
        .and_then(Value::as_str)
        .unwrap_or("USD")
        .to_owned();
    let period = object
        .get("period")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let balance = optional_float(object.get("balance"));
    let personal_used = optional_float(object.get("personalUsed"));
    let resets_at = object
        .get("resetsAt")
        .and_then(Value::as_str)
        .and_then(|value| parse_timestamp(Some(value)));

    Some(CostInfo {
        used,
        limit,
        currency,
        period,
        balance,
        personal_used,
        resets_at,
    })
}

/// Normalize one detail row from a CLI ``providerCost`` details section.
///
/// Matches Python's ``DetailRow`` construction: label/value are coerced to
/// strings, used_percent comes from ``progress.usedPercent`` (rejected when
/// non-numeric), and severity defaults to ``"normal"``.
pub fn detail_row_from_value(value: &Value) -> Option<DetailRow> {
    let object = value.as_object()?;
    let label = object
        .get("label")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let value_str = object
        .get("value")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let secondary_value = object
        .get("secondaryValue")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let progress = object.get("progress").and_then(Value::as_object);
    let used_percent = progress
        .and_then(|p| p.get("usedPercent"))
        .and_then(|v| optional_float(Some(v)));
    let severity = object
        .get("severity")
        .and_then(Value::as_str)
        .unwrap_or("normal")
        .to_owned();

    Some(DetailRow {
        label,
        value: value_str,
        secondary_value,
        used_percent,
        severity,
    })
}

/// Normalize one detail section (rows + optional chart) from CLI payload.
///
/// Matches Python's section construction: up to 24 rows per section, chart
/// points truncated to 120.
pub fn detail_section_from_value(value: &Value) -> Option<DetailSection> {
    let object = value.as_object()?;
    let title = object
        .get("title")
        .and_then(Value::as_str)
        .map(str::to_owned);

    let mut rows: Vec<DetailRow> = Vec::new();
    if let Some(raw_rows) = object.get("rows").and_then(Value::as_array) {
        for raw_row in raw_rows.iter().take(24) {
            if let Some(row) = detail_row_from_value(raw_row) {
                rows.push(row);
            }
        }
    }

    let chart = object.get("chart").and_then(detail_chart_from_value);

    Some(DetailSection { title, rows, chart })
}

/// Normalize a detail chart from CLI payload.
///
/// Chart points are truncated to 120 entries; non-numeric point values fall
/// back to 0.0 (matching Python's ``float(value)`` coercion).
pub fn detail_chart_from_value(value: &Value) -> Option<DetailChart> {
    let object = value.as_object()?;
    let kind = object
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("bars")
        .to_owned();
    let title = object
        .get("title")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let unit = object
        .get("unit")
        .and_then(Value::as_str)
        .map(str::to_owned);

    let mut points: Vec<(String, f64)> = Vec::new();
    if let Some(raw_points) = object.get("points").and_then(Value::as_array) {
        for raw_point in raw_points.iter().take(120) {
            let point_obj = raw_point.as_object()?;
            let label = point_obj
                .get("label")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            let point_value = point_obj
                .get("value")
                .and_then(|v| optional_float(Some(v)))
                .unwrap_or(0.0);
            points.push((label, point_value));
        }
    }

    Some(DetailChart {
        kind,
        title,
        unit,
        points,
    })
}

/// Chart attached to a provider detail section.
#[derive(Clone, Debug, PartialEq)]
pub struct DetailChart {
    pub kind: String,
    pub title: Option<String>,
    pub unit: Option<String>,
    pub points: Vec<(String, f64)>,
}

impl DetailChart {
    pub fn peak(&self) -> f64 {
        Self::peak_for(&self.points)
    }

    pub fn peak_for(points: &[(String, f64)]) -> f64 {
        python_max(points.iter().map(|(_, value)| *value), 0.0)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct CreditEvent {
    pub id: String,
    pub date: String,
    pub service: String,
    pub used: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DetailRow {
    pub label: String,
    pub value: String,
    pub secondary_value: Option<String>,
    pub used_percent: Option<f64>,
    pub severity: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DetailSection {
    pub title: Option<String>,
    pub rows: Vec<DetailRow>,
    pub chart: Option<DetailChart>,
}

/// Aggregate context fields from a provider payload: credits, status, errors,
/// plan, and reset credits.
#[derive(Clone, Debug, PartialEq)]
pub struct ProviderContext {
    pub credits_remaining: Option<f64>,
    pub credits_available: bool,
    pub credit_events: Vec<CreditEvent>,
    pub reset_credits_available: i64,
    pub status_level: Option<String>,
    pub status_description: Option<String>,
    pub error: Option<String>,
    pub plan: Option<String>,
}

/// Normalize provider context fields (credits, status, error, plan) from a CLI
/// payload.
///
/// Matches Python's ``provider_usage_from_payload`` context assembly: credits
/// remaining/available/events from ``credits``, reset credits available from
/// ``codexResetCredits``, status indicator/description from ``status``, error
/// message from ``error``, and plan from payload/identity/login method.
pub fn provider_context_from_value(payload: &Value) -> Option<ProviderContext> {
    let object = payload.as_object()?;

    let credits = object
        .get("credits")
        .or_else(|| {
            object
                .get("usage")
                .and_then(Value::as_object)
                .and_then(|u| u.get("credits"))
        })
        .and_then(Value::as_object);
    let credits_remaining = credits
        .and_then(|c| c.get("remaining"))
        .and_then(|v| optional_float(Some(v)));
    let credits_available = credits
        .and_then(|c| c.get("creditsAvailable"))
        .and_then(Value::as_bool)
        .unwrap_or(false);

    let mut credit_events: Vec<CreditEvent> = Vec::new();
    if let Some(raw_events) = credits
        .and_then(|c| c.get("events"))
        .and_then(Value::as_array)
    {
        for raw_event in raw_events.iter() {
            let event_obj = raw_event.as_object()?;
            let used = event_obj
                .get("creditsUsed")
                .and_then(|v| optional_float(Some(v)))
                .unwrap_or(0.0);
            credit_events.push(CreditEvent {
                id: event_obj
                    .get("id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
                date: event_obj
                    .get("date")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
                service: event_obj
                    .get("service")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_owned(),
                used,
            });
        }
    }

    let reset_credits = object
        .get("usage")
        .and_then(Value::as_object)
        .and_then(|u| u.get("codexResetCredits").and_then(Value::as_object));
    let reset_credits_available = reset_credits
        .and_then(|c| c.get("availableCount"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    let status = object
        .get("status")
        .or_else(|| {
            object
                .get("usage")
                .and_then(Value::as_object)
                .and_then(|u| u.get("status"))
        })
        .and_then(Value::as_object);
    let status_level = status.and_then(|s| {
        s.get("indicator")
            .and_then(Value::as_str)
            .map(str::to_owned)
    });
    let status_description = status.and_then(|s| {
        s.get("description")
            .and_then(Value::as_str)
            .map(str::to_owned)
    });

    let error = object
        .get("error")
        .or_else(|| {
            object
                .get("usage")
                .and_then(Value::as_object)
                .and_then(|u| u.get("error"))
        })
        .and_then(Value::as_object)
        .and_then(|e| e.get("message").and_then(Value::as_str).map(str::to_owned));

    let plan = provider_plan_from_value(object);

    Some(ProviderContext {
        credits_remaining,
        credits_available,
        credit_events,
        reset_credits_available,
        status_level,
        status_description,
        error,
        plan,
    })
}

/// Extract the plan from a provider payload, matching Python's ``_plan_from``:
/// checks ``plan``/``subscriptionPlan`` at top level, then ``identity.plan``,
/// then derives from ``loginMethod``.
pub fn provider_plan_from_value(object: &serde_json::Map<String, Value>) -> Option<String> {
    for key in ["plan", "subscriptionPlan"] {
        if let Some(Value::String(value)) = object.get(key) {
            if !value.is_empty() {
                return Some(value.clone());
            }
        }
    }
    if let Some(identity) = object
        .get("usage")
        .and_then(Value::as_object)
        .and_then(|u| u.get("identity").and_then(Value::as_object))
    {
        if let Some(Value::String(value)) = identity.get("plan") {
            if !value.is_empty() {
                return Some(value.clone());
            }
        }
        if let Some(Value::String(login)) = identity.get("loginMethod") {
            if !login.is_empty() && login != "oauth" && login != "apiKey" && login != "cookie" {
                return Some(
                    login
                        .chars()
                        .next()
                        .map(|c| c.to_uppercase().collect::<String>() + &login[1..])
                        .unwrap_or_default(),
                );
            }
        }
    }
    None
}

/// A running or recent coding-agent session.
#[derive(Clone, Debug, PartialEq)]
pub struct AgentSession {
    pub id: String,
    pub provider: String,
    pub state: String,
    pub project_name: String,
    pub cwd: String,
    pub pid: i64,
    pub started_at: Option<DateTime<Utc>>,
    pub last_activity_at: Option<DateTime<Utc>>,
    pub host: String,
}

impl AgentSession {
    pub fn is_running(&self) -> bool {
        Self::state_is_running(&self.state)
    }

    pub fn state_is_running(state: &str) -> bool {
        matches!(state.to_lowercase().as_str(), "running" | "active" | "live")
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SpendProvider {
    pub provider: String,
    pub cost: f64,
    pub tokens: i64,
    pub session_tokens: i64,
    pub daily: Vec<Value>,
    pub projects: Vec<Value>,
    pub priced: bool,
    pub provenance: String,
    pub cost_known: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SpendSummary {
    pub total_cost: f64,
    pub cost_known: bool,
    pub cost_partial: bool,
    pub currency: String,
    pub total_tokens: i64,
    pub coverage: HashMap<String, i64>,
    pub provenance: String,
    pub reporting_period: Option<String>,
    pub history_label: Option<String>,
    pub history_coverage_established: bool,
    pub daily: Vec<Value>,
    pub projects: Vec<Value>,
    pub models: Vec<Value>,
    pub session_cost: f64,
    pub session_cost_known: bool,
    pub session_tokens: i64,
    pub last30_cost: f64,
    pub last30_cost_known: bool,
    pub last30_cost_partial: bool,
    pub last30_tokens: i64,
    pub incomplete_requests: i64,
    pub error: Option<String>,
    pub providers: Vec<SpendProvider>,
}

/// Aggregate provider data consumed by dashboard and tray presentation.
#[derive(Clone, Debug, PartialEq)]
pub struct ProviderUsage {
    pub provider_id: String,
    pub display_name: String,
    pub source: Option<String>,
    pub version: Option<String>,
    pub updated_at: Option<DateTime<Utc>>,
    pub account_email: Option<String>,
    pub plan: Option<String>,
    pub login_method: Option<String>,
    pub windows: Vec<RateWindow>,
    pub pace: HashMap<String, Pace>,
    pub credits_remaining: Option<f64>,
    pub credits_unit: String,
    pub credits_available: bool,
    pub cost: Option<CostInfo>,
    pub status_level: Option<String>,
    pub status_description: Option<String>,
    pub error: Option<String>,
    pub details: Vec<DetailSection>,
    pub reset_credits_available: i64,
    pub reset_credits: Vec<Value>,
    pub credit_events: Vec<CreditEvent>,
    pub accounts: Vec<String>,
    pub selected_account: Option<String>,
    pub accent_color: String,
    pub raw: Value,
}

impl ProviderUsage {
    pub fn has_error(&self) -> bool {
        Self::error_is_present(self.error.as_deref())
    }

    pub fn error_is_present(error: Option<&str>) -> bool {
        error.is_some_and(|error| !error.is_empty())
    }

    pub fn primary_window(&self) -> Option<&RateWindow> {
        self.windows.first()
    }

    pub fn max_used_percent(&self) -> f64 {
        Self::max_used_from(self.windows.iter().map(|window| window.used_percent))
    }

    pub fn max_used_from(values: impl IntoIterator<Item = f64>) -> f64 {
        python_max(values, 0.0)
    }

    pub fn window(&self, key: &str) -> Option<&RateWindow> {
        self.windows.iter().find(|window| window.key == key)
    }

    pub fn pace_for(&self, window: &RateWindow) -> Option<&Pace> {
        self.pace.get(&window.key)
    }

    pub fn subtitle(&self) -> String {
        Self::subtitle_for(self.plan.as_deref(), self.account_email.as_deref())
    }

    pub fn subtitle_for(plan: Option<&str>, account_email: Option<&str>) -> String {
        [plan, account_email]
            .into_iter()
            .flatten()
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join(" · ")
    }
}

/// Normalize one standard CLI window envelope into a typed quota window.
/// Additional-window semantics are handled by the provider normalizer.
pub fn rate_window_from_value(
    payload: &Value,
    key: &str,
    title: Option<&str>,
) -> Option<RateWindow> {
    let object = payload.as_object()?;
    let used_percent = optional_float(object.get("usedPercent"));
    let raw_title = title.filter(|value| !value.is_empty());
    let normalized_title = raw_title.map(str::to_owned).unwrap_or_else(|| {
        let lower = key.to_lowercase();
        let mut chars = lower.chars();
        chars
            .next()
            .map(|first| first.to_uppercase().chain(chars).collect())
            .unwrap_or_default()
    });
    Some(RateWindow {
        key: key.to_owned(),
        title: normalized_title,
        used_percent: used_percent.unwrap_or(0.0),
        resets_at: object
            .get("resetsAt")
            .and_then(Value::as_str)
            .and_then(|value| parse_timestamp(Some(value))),
        reset_description: object
            .get("resetDescription")
            .and_then(Value::as_str)
            .map(str::to_owned),
        window_minutes: optional_i64(object.get("windowMinutes")),
        next_regen_percent: optional_float(object.get("nextRegenPercent")),
        is_placeholder: object
            .get("isSyntheticPlaceholder")
            .is_some_and(json_truthy),
        quota_limit: optional_float(object.get("quotaLimit")),
        quota_unit: object
            .get("quotaUnit")
            .and_then(Value::as_str)
            .map(str::to_owned),
        usage_known: used_percent.is_some(),
    })
}

/// Normalize one entry from the CLI's ``extraRateWindows`` array.
///
/// The outer object carries ``id``/``title``/``usageKnown``/``isSyntheticPlaceholder``
/// while the nested ``window`` object carries the rate-window fields.
pub fn extra_rate_window_from_value(item: &Value) -> Option<RateWindow> {
    let object = item.as_object()?;
    let inner = object.get("window")?.as_object()?;
    let key = object
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("extra")
        .to_owned();
    let title = object
        .get("title")
        .and_then(Value::as_str)
        .or_else(|| object.get("id").and_then(Value::as_str))
        .unwrap_or("Extra")
        .to_owned();
    let mut rate_window =
        rate_window_from_value(&Value::Object(inner.clone()), &key, Some(&title))?;
    let usage_known_inner = rate_window.usage_known;
    rate_window.usage_known = match object.get("usageKnown") {
        Some(Value::Bool(false)) => false,
        _ => usage_known_inner,
    };
    Some(rate_window)
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

/// Typed quota window. Missing usage is represented by `usage_known = false`
/// rather than conflated with a known zero.
#[derive(Clone, Debug, PartialEq)]
pub struct RateWindow {
    pub key: String,
    pub title: String,
    pub used_percent: f64,
    pub resets_at: Option<DateTime<Utc>>,
    pub reset_description: Option<String>,
    pub window_minutes: Option<i64>,
    pub next_regen_percent: Option<f64>,
    pub is_placeholder: bool,
    pub quota_limit: Option<f64>,
    pub quota_unit: Option<String>,
    pub usage_known: bool,
}

impl RateWindow {
    pub fn remaining_percent(&self) -> f64 {
        (100.0 - self.used_percent).max(0.0)
    }

    pub fn duration_label(&self) -> Option<String> {
        let minutes = self.window_minutes?;
        if minutes == 0 {
            return None;
        }
        if minutes % 1_440 == 0 {
            let days = minutes / 1_440;
            return Some(if days > 1 {
                format!("{days}d window")
            } else {
                "24h window".to_owned()
            });
        }
        if minutes % 60 == 0 {
            return Some(format!("{}h window", minutes / 60));
        }
        Some(format!("{minutes}m window"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::json;

    #[test]
    fn timestamps_normalize_offsets_naive_values_and_dates_to_utc() {
        assert_eq!(
            parse_timestamp(Some("2026-10-21T14:56:53Z")),
            Utc.with_ymd_and_hms(2026, 10, 21, 14, 56, 53).single()
        );
        assert_eq!(
            parse_timestamp(Some(" 2026-10-21T16:56:53+02:00 ")),
            Utc.with_ymd_and_hms(2026, 10, 21, 14, 56, 53).single()
        );
        assert_eq!(
            parse_timestamp(Some("2026-10-21 14:56:53.125")),
            Utc.with_ymd_and_hms(2026, 10, 21, 14, 56, 53)
                .single()
                .map(|time| time + chrono::Duration::milliseconds(125))
        );
        assert_eq!(
            parse_timestamp(Some("2026-10-21")),
            Utc.with_ymd_and_hms(2026, 10, 21, 0, 0, 0).single()
        );
        assert_eq!(parse_timestamp(None), None);
        assert_eq!(parse_timestamp(Some("  ")), None);
        assert_eq!(parse_timestamp(Some("yesterday")), None);
    }

    #[test]
    fn optional_numbers_reject_booleans_strings_and_non_finite_values() {
        assert_eq!(optional_float(Some(&json!(12))), Some(12.0));
        assert_eq!(optional_float(Some(&json!(12.5))), Some(12.5));
        assert_eq!(optional_float(Some(&json!(true))), None);
        assert_eq!(optional_float(Some(&json!("12.5"))), None);
        assert_eq!(optional_i64(Some(&json!(12.0))), Some(12));
        assert_eq!(optional_i64(Some(&json!(12.5))), None);
        assert_eq!(optional_i64(Some(&json!(true))), None);
        assert_eq!(optional_i64(Some(&json!(u64::MAX))), None);
    }

    fn window(minutes: Option<i64>, used: f64) -> RateWindow {
        RateWindow {
            key: "primary".to_owned(),
            title: "Session".to_owned(),
            used_percent: used,
            resets_at: None,
            reset_description: None,
            window_minutes: minutes,
            next_regen_percent: None,
            is_placeholder: false,
            quota_limit: None,
            quota_unit: None,
            usage_known: true,
        }
    }

    #[test]
    fn pace_properties_and_labels_match_python_contract() {
        let cases = [
            ("onTrack", false, false, "On pace"),
            ("slightlyAhead", true, false, "In deficit"),
            ("ahead", true, false, "In deficit"),
            ("farAhead", true, false, "Well in deficit"),
            ("slightlyBehind", false, true, "In reserve"),
            ("behind", false, true, "In reserve"),
            ("farBehind", false, true, "Well in reserve"),
            ("futureStage", false, false, "futureStage"),
        ];
        for (stage, deficit, reserve, label) in cases {
            let pace = Pace {
                stage: stage.to_owned(),
                delta_percent: None,
                expected_used_percent: None,
                will_last_to_reset: true,
                eta_seconds: None,
                run_out_probability: None,
                summary: None,
            };
            assert_eq!(pace.in_deficit(), deficit);
            assert_eq!(pace.in_reserve(), reserve);
            assert_eq!(pace.stage_label(), label);
        }
    }

    #[test]
    fn pace_payload_normalization_preserves_typed_fields_and_fallback_shapes() {
        let pace = pace_from_value(&json!({
            "stage": "behind",
            "deltaPercent": -12.5,
            "expectedUsedPercent": 45,
            "willLastToReset": 1,
            "etaSeconds": 600,
            "runOutProbability": 0.2,
            "summary": "in reserve"
        }))
        .unwrap();
        assert_eq!(pace.stage, "behind");
        assert_eq!(pace.delta_percent, Some(-12.5));
        assert_eq!(pace.expected_used_percent, Some(45.0));
        assert!(pace.will_last_to_reset);
        assert_eq!(pace.eta_seconds, Some(600.0));
        assert_eq!(pace.run_out_probability, Some(0.2));
        assert_eq!(pace.summary.as_deref(), Some("in reserve"));
        assert!(pace_from_value(&json!({"stage": ""})).is_none());
        assert!(pace_from_value(&json!({"stage": "ahead", "etaSeconds": "unknown"})).is_none());
        assert!(pace_from_value(&json!({"stage": 1})).is_none());
    }

    #[test]
    fn cost_info_limit_and_percent_match_python_contract() {
        let cost = |used, limit| CostInfo {
            used,
            limit,
            currency: "USD".to_owned(),
            period: None,
            balance: None,
            personal_used: None,
            resets_at: None,
        };
        assert!(!cost(10.0, 0.0).has_limit());
        assert!(!cost(10.0, -1.0).has_limit());
        assert!(cost(10.0, f64::INFINITY).has_limit());
        assert_eq!(cost(50.0, 100.0).used_percent(), 50.0);
        assert_eq!(cost(150.0, 100.0).used_percent(), 100.0);
        assert_eq!(cost(-5.0, 100.0).used_percent(), 0.0);
        assert_eq!(cost(f64::NAN, 100.0).used_percent(), 100.0);
        assert_eq!(cost(10.0, f64::NAN).used_percent(), 0.0);
    }

    #[test]
    fn cost_payload_normalization_preserves_fields_and_fallbacks() {
        let cost = cost_from_value(&json!({
            "used": 12.5,
            "limit": 100.0,
            "currencyCode": "USD",
            "period": "Extra usage",
            "balance": 87.5,
            "personalUsed": 2.0,
            "resetsAt": "2026-10-30T20:00:00Z"
        }))
        .unwrap();
        assert_eq!(cost.used, 12.5);
        assert_eq!(cost.limit, 100.0);
        assert_eq!(cost.currency, "USD");
        assert_eq!(cost.period.as_deref(), Some("Extra usage"));
        assert_eq!(cost.balance, Some(87.5));
        assert_eq!(cost.personal_used, Some(2.0));
        assert_eq!(
            cost.resets_at,
            Utc.with_ymd_and_hms(2026, 10, 30, 20, 0, 0).single()
        );

        let missing_fields = cost_from_value(&json!({})).unwrap();
        assert_eq!(missing_fields.used, 0.0);
        assert_eq!(missing_fields.limit, 0.0);
        assert_eq!(missing_fields.currency, "USD");
        assert!(!missing_fields.has_limit());
        assert_eq!(missing_fields.balance, None);

        let non_numeric_used = cost_from_value(&json!({"used": "not a number"}));
        assert_eq!(non_numeric_used.unwrap().used, 0.0);

        let missing_used = cost_from_value(&json!({"totalCost": 42}));
        // totalCost is not a recognized key; Python only reads "used"
        assert_eq!(missing_used.unwrap().used, 0.0);
    }

    #[test]
    fn detail_section_normalization_preserves_rows_and_chart() {
        let section = detail_section_from_value(&json!({
            "title": "Usage breakdown",
            "rows": [
                {
                    "label": "Code",
                    "value": "3 requests",
                    "secondaryValue": "Python",
                    "progress": {"usedPercent": 45},
                    "severity": "normal",
                },
                {
                    "label": "Tests",
                    "value": "12 passed",
                    "progress": {},
                    "severity": "warning",
                },
            ],
            "chart": {
                "kind": "bars",
                "title": "Daily",
                "unit": "requests",
                "points": [
                    {"label": "10-20", "value": 3},
                    {"label": "10-21", "value": 8},
                    {"label": "bad", "value": "not a number"},
                ],
            },
        }))
        .unwrap();
        assert_eq!(section.title.as_deref(), Some("Usage breakdown"));
        assert_eq!(section.rows.len(), 2);
        assert_eq!(section.rows[0].label, "Code");
        assert_eq!(section.rows[0].value, "3 requests");
        assert_eq!(section.rows[0].secondary_value.as_deref(), Some("Python"));
        assert_eq!(section.rows[0].used_percent, Some(45.0));
        assert_eq!(section.rows[0].severity, "normal");
        assert_eq!(section.rows[1].label, "Tests");
        assert_eq!(section.rows[1].used_percent, None);
        assert_eq!(section.rows[1].severity, "warning");
        let chart = section.chart.unwrap();
        assert_eq!(chart.kind, "bars");
        assert_eq!(chart.title.as_deref(), Some("Daily"));
        assert_eq!(chart.unit.as_deref(), Some("requests"));
        assert_eq!(chart.points.len(), 3);
        assert_eq!(chart.points[0], ("10-20".to_owned(), 3.0));
        assert_eq!(chart.points[1], ("10-21".to_owned(), 8.0));
        assert_eq!(chart.points[2], ("bad".to_owned(), 0.0));
        assert_eq!(chart.peak(), 8.0);

        let empty = detail_section_from_value(&json!({})).unwrap();
        assert_eq!(empty.title, None);
        assert_eq!(empty.rows.len(), 0);
        assert_eq!(empty.chart, None);
    }

    #[test]
    fn detail_section_row_limit_is_respected() {
        let rows: Vec<Value> = (0..30)
            .map(|i| json!({"label": format!("row {}", i), "value": format!("val {}", i)}))
            .collect();
        let section = detail_section_from_value(&json!({"rows": rows})).unwrap();
        assert_eq!(section.rows.len(), 24);
        assert_eq!(section.rows[0].label, "row 0");
        assert_eq!(section.rows[23].label, "row 23");
    }

    #[test]
    fn provider_context_normalization_preserves_credits_status_error_plan() {
        let context = provider_context_from_value(&json!({
            "usage": {
                "credits": {
                    "remaining": 437.55,
                    "creditsAvailable": true,
                    "events": [
                        {"id": "e1", "date": "2026-10-20", "service": "codex", "creditsUsed": 12.5},
                        {"id": "e2", "date": "2026-10-21", "service": "codex", "creditsUsed": 5.0},
                    ],
                },
                "codexResetCredits": {
                    "availableCount": 3,
                },
                "status": {
                    "indicator": "warning",
                    "description": "Degraded performance",
                },
                "error": {
                    "message": "API rate limit exceeded",
                },
            },
            "plan": "Pro Plus",
        }))
        .unwrap();
        assert_eq!(context.credits_remaining, Some(437.55));
        assert!(context.credits_available);
        assert_eq!(context.credit_events.len(), 2);
        assert_eq!(context.credit_events[0].id, "e1");
        assert_eq!(context.credit_events[0].date, "2026-10-20");
        assert_eq!(context.credit_events[0].service, "codex");
        assert_eq!(context.credit_events[0].used, 12.5);
        assert_eq!(context.credit_events[1].used, 5.0);
        assert_eq!(context.reset_credits_available, 3);
        assert_eq!(context.status_level.as_deref(), Some("warning"));
        assert_eq!(
            context.status_description.as_deref(),
            Some("Degraded performance")
        );
        assert_eq!(context.error.as_deref(), Some("API rate limit exceeded"));
        assert_eq!(context.plan.as_deref(), Some("Pro Plus"));

        // Missing fields fall back to defaults
        let empty = provider_context_from_value(&json!({
            "usage": {}
        }))
        .unwrap();
        assert_eq!(empty.credits_remaining, None);
        assert!(!empty.credits_available);
        assert_eq!(empty.credit_events.len(), 0);
        assert_eq!(empty.reset_credits_available, 0);
        assert_eq!(empty.status_level, None);
        assert_eq!(empty.status_description, None);
        assert_eq!(empty.error, None);
        assert_eq!(empty.plan, None);

        // Plan from identity when inside usage
        let context = provider_context_from_value(&json!({
            "usage": {
                "identity": {
                    "plan": "Team Plan",
                    "loginMethod": "apiKey",
                }
            }
        }))
        .unwrap();
        assert_eq!(context.plan.as_deref(), Some("Team Plan"));

        // Plan derived from loginMethod when not oauth/apiKey/cookie
        let context = provider_context_from_value(&json!({
            "usage": {
                "identity": {
                    "loginMethod": "sso",
                }
            }
        }))
        .unwrap();
        assert_eq!(context.plan.as_deref(), Some("Sso"));

        // No plan from oauth/login methods
        let context = provider_context_from_value(&json!({
            "usage": {
                "identity": {
                    "loginMethod": "oauth",
                }
            }
        }))
        .unwrap();
        assert_eq!(context.plan, None);

        let context = provider_context_from_value(&json!({
            "usage": {
                "identity": {
                    "loginMethod": "cookie",
                }
            }
        }))
        .unwrap();
        assert_eq!(context.plan, None);
    }

    #[test]
    fn data_model_derived_helpers_match_python_contract() {
        let chart = DetailChart {
            kind: "bars".to_owned(),
            title: None,
            unit: None,
            points: vec![("a".to_owned(), -2.0), ("b".to_owned(), 8.0)],
        };
        assert_eq!(chart.peak(), 8.0);
        assert_eq!(DetailChart::peak_for(&[]), 0.0);
        assert_eq!(
            DetailChart::peak_for(&[("negative".to_owned(), -2.0)]),
            -2.0
        );
        assert!(DetailChart::peak_for(&[("nan".to_owned(), f64::NAN)]).is_nan());

        for (state, running) in [
            ("running", true),
            ("ACTIVE", true),
            ("Live", true),
            ("stopped", false),
            ("", false),
        ] {
            assert_eq!(AgentSession::state_is_running(state), running);
        }
        assert!(ProviderUsage::error_is_present(Some("error")));
        assert!(!ProviderUsage::error_is_present(Some("")));
        assert!(!ProviderUsage::error_is_present(None));
        assert_eq!(ProviderUsage::max_used_from([12.0, 80.0, 35.0]), 80.0);
        assert_eq!(ProviderUsage::max_used_from([-2.0]), -2.0);
        assert!(ProviderUsage::max_used_from([f64::NAN, 8.0]).is_nan());
        assert_eq!(ProviderUsage::max_used_from([]), 0.0);
        assert_eq!(
            ProviderUsage::subtitle_for(Some("Plus"), Some("fixture@example.invalid")),
            "Plus · fixture@example.invalid"
        );
        assert_eq!(ProviderUsage::subtitle_for(Some(""), None), "");
    }

    #[test]
    fn standard_window_payload_normalization_preserves_unknown_and_zero() {
        let known_zero = rate_window_from_value(
            &json!({
                "usedPercent": 0,
                "resetsAt": "2026-10-21T14:56:53Z",
                "windowMinutes": 300,
                "isSyntheticPlaceholder": false,
                "quotaLimit": 120,
                "quotaUnit": "requests"
            }),
            "primary",
            Some("Session"),
        )
        .unwrap();
        assert_eq!(known_zero.title, "Session");
        assert_eq!(known_zero.used_percent, 0.0);
        assert!(known_zero.usage_known);
        assert_eq!(known_zero.window_minutes, Some(300));
        assert_eq!(known_zero.quota_limit, Some(120.0));
        assert_eq!(known_zero.quota_unit.as_deref(), Some("requests"));
        assert!(!known_zero.is_placeholder);

        let unknown = rate_window_from_value(&json!({}), "secondary", None).unwrap();
        assert_eq!(unknown.title, "Secondary");
        assert_eq!(unknown.used_percent, 0.0);
        assert!(!unknown.usage_known);
        assert_eq!(unknown.resets_at, None);

        for truthy in [
            json!(true),
            json!(1),
            json!("yes"),
            json!([1]),
            json!({"x": 1}),
        ] {
            assert!(rate_window_from_value(
                &json!({"isSyntheticPlaceholder": truthy}),
                "primary",
                None,
            )
            .unwrap()
            .is_placeholder);
        }
    }

    #[test]
    fn rate_window_derived_values_match_python_contract() {
        assert_eq!(window(Some(300), 48.0).remaining_percent(), 52.0);
        assert_eq!(window(Some(300), 101.0).remaining_percent(), 0.0);
        assert_eq!(window(Some(300), f64::NAN).remaining_percent(), 0.0);
        assert_eq!(
            window(Some(300), 0.0).duration_label().as_deref(),
            Some("5h window")
        );
        assert_eq!(
            window(Some(1_440), 0.0).duration_label().as_deref(),
            Some("24h window")
        );
        assert_eq!(
            window(Some(2_880), 0.0).duration_label().as_deref(),
            Some("2d window")
        );
        assert_eq!(
            window(Some(90), 0.0).duration_label().as_deref(),
            Some("90m window")
        );
        assert_eq!(window(Some(0), 0.0).duration_label(), None);
        assert_eq!(window(None, 0.0).duration_label(), None);
    }
}
