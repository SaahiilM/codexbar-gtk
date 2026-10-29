//! Shared domain primitives and strict payload-number helpers.
//!
//! The Python reference currently accepts `datetime.fromisoformat` inputs and
//! normalizes naive timestamps as UTC. Rust's accepted timestamp grammar is
//! intentionally explicit here; transitional callers retain a Python fallback
//! for valid ISO forms not accepted by this parser.

use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use serde_json::Value;

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
