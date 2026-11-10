//! Monthly allowance helpers ported from `codexbar_gtk/pace.py`.
//!
//! Currency exchange is injected so the core calculations remain pure and can
//! be validated before the currency service itself is migrated.

use chrono::{DateTime, Local, NaiveTime, Utc};

pub const MONTHLY_DAYS: [i64; 4] = [28, 29, 30, 31];

#[derive(Debug, Clone, PartialEq)]
pub struct AllowanceWindow {
    pub is_placeholder: bool,
    pub usage_known: bool,
    pub window_minutes: Option<i64>,
    pub used_percent: f64,
    pub quota_limit: Option<f64>,
    pub quota_unit: Option<String>,
    pub resets_at: Option<DateTime<Utc>>,
}

impl AllowanceWindow {
    fn remaining_percent(&self) -> f64 {
        (100.0 - self.used_percent).max(0.0)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MonthlyCost {
    pub used: f64,
    pub limit: f64,
    pub currency: String,
    pub period: Option<String>,
    pub resets_at: Option<DateTime<Utc>>,
}

/// Whether a quota window is a 28–31 day monthly allowance.
pub fn is_monthly_window(window_minutes: Option<i64>) -> bool {
    let Some(minutes) = window_minutes.filter(|minutes| *minutes > 0) else {
        return false;
    };
    let rounded_days = (minutes as f64 / 1_440.0 + 0.5).floor() as i64;
    MONTHLY_DAYS.contains(&rounded_days)
}

/// Divide a finite remaining allowance among the local calendar days until reset.
pub fn daily_target(
    remaining: Option<f64>,
    resets_at: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
) -> Option<f64> {
    let remaining = remaining.filter(|value| value.is_finite() && *value >= 0.0)?;
    let resets_at = resets_at?;
    let local_now = now.with_timezone(&Local);
    let local_reset = resets_at.with_timezone(&Local);
    if local_reset <= local_now {
        return None;
    }

    let days_to_reset = (local_reset.date_naive() - local_now.date_naive()).num_days();
    let reset_day_is_included = local_reset.time() > NaiveTime::MIN;
    let day_count = (days_to_reset + i64::from(reset_day_is_included)).max(1);
    Some(remaining / day_count as f64)
}

/// Daily target for a monthly quota window, in the window's own unit.
pub fn window_daily_target(window: &AllowanceWindow, now: DateTime<Utc>) -> Option<f64> {
    if window.is_placeholder || !window.usage_known || !is_monthly_window(window.window_minutes) {
        return None;
    }
    if !window.used_percent.is_finite() || window.used_percent < 0.0 {
        return None;
    }
    let limit = match window.quota_limit {
        Some(limit) if limit != 0.0 && limit > 0.0 => limit,
        _ => 100.0,
    };
    let remaining = limit * window.remaining_percent() / 100.0;
    daily_target(Some(remaining), window.resets_at, now)
}

/// Format a monthly quota window's daily target.
pub fn format_window_target<F>(
    window: &AllowanceWindow,
    preferred_currency: &str,
    now: DateTime<Utc>,
    convert: &F,
) -> Option<String>
where
    F: Fn(f64, &str, &str) -> Option<f64>,
{
    if window.quota_limit.is_some() && window.quota_unit.as_deref() == Some("") {
        return None;
    }
    let unit = if window.quota_limit.is_none() {
        "%"
    } else {
        window.quota_unit.as_deref().unwrap_or("")
    };
    format_daily_target(
        window_daily_target(window, now),
        Some(unit),
        preferred_currency,
        convert,
    )
}

/// Calculate a provider's monthly spending cap as a daily target.
pub fn monthly_cost_daily_target(cost: Option<&MonthlyCost>, now: DateTime<Utc>) -> Option<f64> {
    let cost = cost?;
    let period = cost
        .period
        .as_deref()
        .unwrap_or_default()
        .trim()
        .to_lowercase();
    if !matches!(
        period.as_str(),
        "monthly" | "month" | "this month" | "monthly cap" | "monthly credit limit"
    ) {
        return None;
    }
    if !cost.used.is_finite() || cost.used < 0.0 || !cost.limit.is_finite() || cost.limit <= 0.0 {
        return None;
    }
    let remaining = (cost.limit - cost.used).max(0.0);
    daily_target(Some(remaining), cost.resets_at, now)
}

/// Format a provider's monthly spending cap as a daily target.
pub fn format_monthly_cost_target<F>(
    cost: Option<&MonthlyCost>,
    preferred_currency: &str,
    now: DateTime<Utc>,
    convert: &F,
) -> Option<String>
where
    F: Fn(f64, &str, &str) -> Option<f64>,
{
    let cost = cost?;
    format_daily_target(
        monthly_cost_daily_target(Some(cost), now),
        Some(&cost.currency),
        preferred_currency,
        convert,
    )
}

/// Format a daily target. Conversion is attempted only when requested and only
/// replaces the source amount if the converter returns a result.
pub fn format_daily_target<F>(
    target: Option<f64>,
    unit: Option<&str>,
    preferred_currency: &str,
    convert: &F,
) -> Option<String>
where
    F: Fn(f64, &str, &str) -> Option<f64>,
{
    let target = target.filter(|value| value.is_finite())?;
    let normalized = unit.unwrap_or("%").trim();
    let lowered = normalized.to_lowercase();
    let amount = if lowered == "%" || lowered == "percent" {
        format!("{}%", format_number(target))
    } else if lowered == "credits" {
        format!("{} credits", format_number(target))
    } else if lowered == "requests" {
        format!("{} requests", format_number(target))
    } else {
        let source = normalized.to_uppercase();
        if !crate::currency::CURRENCIES
            .iter()
            .any(|(code, _, _)| *code == source)
        {
            return None;
        }
        let preferred = if preferred_currency.is_empty() {
            "AUTO".to_owned()
        } else {
            preferred_currency.to_uppercase()
        };
        let (value, output_currency) = if preferred != "AUTO" && preferred != source {
            match convert(target, &source, &preferred) {
                Some(value) => (value, preferred.as_str()),
                None => (target, source.as_str()),
            }
        } else {
            (target, source.as_str())
        };
        crate::formatting::format_currency(Some(value), output_currency, false)
    };
    Some(format!("≈ {amount} / day to last until reset"))
}

/// Up to two decimals without trailing zeros, using comma-separated thousands.
fn format_number(value: f64) -> String {
    let raw = format!("{value:.2}");
    let (sign, unsigned) = raw
        .strip_prefix('-')
        .map(|value| ("-", value))
        .unwrap_or(("", raw.as_str()));
    let (integer, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    let fraction = fraction.trim_end_matches('0');
    let mut output = String::with_capacity(raw.len() + integer.len() / 3);
    output.push_str(sign);
    for (index, digit) in integer.chars().enumerate() {
        if index > 0 && (integer.len() - index) % 3 == 0 {
            output.push(',');
        }
        output.push(digit);
    }
    if !fraction.is_empty() {
        output.push('.');
        output.push_str(fraction);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Duration, TimeZone};

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 7, 1, 12, 0, 0).unwrap()
    }

    fn reset(day: u32, hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 7, day, hour, 0, 0).unwrap()
    }

    fn no_conversion(_: f64, _: &str, _: &str) -> Option<f64> {
        None
    }

    #[test]
    fn recognizes_only_month_long_windows() {
        assert!(is_monthly_window(Some(28 * 1_440)));
        assert!(is_monthly_window(Some(31 * 1_440)));
        assert!(!is_monthly_window(Some(7 * 1_440)));
        assert!(!is_monthly_window(Some(5 * 60)));
        assert!(!is_monthly_window(None));
        assert!(!is_monthly_window(Some(0)));
        assert!(!is_monthly_window(Some(-1)));
    }

    #[test]
    fn daily_targets_count_today_and_skip_midnight_reset_day() {
        assert_eq!(
            daily_target(Some(300.0), Some(reset(11, 12)), now()),
            Some(300.0 / 11.0)
        );
        assert_eq!(
            daily_target(Some(300.0), Some(reset(11, 0)), now()),
            Some(30.0)
        );
        assert_eq!(daily_target(None, Some(reset(11, 12)), now()), None);
        assert_eq!(
            daily_target(Some(f64::NAN), Some(reset(11, 12)), now()),
            None
        );
        assert_eq!(daily_target(Some(-1.0), Some(reset(11, 12)), now()), None);
        assert_eq!(daily_target(Some(300.0), None, now()), None);
        assert_eq!(daily_target(Some(300.0), Some(reset(1, 11)), now()), None);
    }

    #[test]
    fn formats_percent_credit_request_and_currency_units() {
        assert_eq!(
            format_daily_target(Some(42.0), None, "auto", &no_conversion).as_deref(),
            Some("≈ 42% / day to last until reset")
        );
        assert_eq!(
            format_daily_target(Some(12.5), Some(" Credits "), "auto", &no_conversion).as_deref(),
            Some("≈ 12.5 credits / day to last until reset")
        );
        assert_eq!(
            format_daily_target(Some(9.0), Some("requests"), "auto", &no_conversion).as_deref(),
            Some("≈ 9 requests / day to last until reset")
        );
        assert_eq!(
            format_daily_target(Some(1_234.5), Some("USD"), "auto", &no_conversion).as_deref(),
            Some("≈ $1,234 / day to last until reset")
        );
        assert_eq!(
            format_daily_target(Some(10.0), Some("widgets"), "auto", &no_conversion),
            None
        );
        assert_eq!(
            format_daily_target(None, Some("%"), "auto", &no_conversion),
            None
        );
        assert_eq!(
            format_daily_target(Some(f64::INFINITY), Some("%"), "auto", &no_conversion),
            None
        );
    }

    #[test]
    fn currency_conversion_uses_the_converted_amount_when_available() {
        let convert = |amount: f64, source: &str, target: &str| {
            assert_eq!((amount, source, target), (10.0, "USD", "EUR"));
            Some(9.2)
        };
        assert_eq!(
            format_daily_target(Some(10.0), Some("USD"), "EUR", &convert).as_deref(),
            Some("≈ €9.20 / day to last until reset")
        );
        assert_eq!(
            format_daily_target(Some(10.0), Some("USD"), "EUR", &no_conversion).as_deref(),
            Some("≈ $10 / day to last until reset")
        );
    }

    #[test]
    fn monthly_window_targets_respect_quota_metadata_and_validity() {
        let window = AllowanceWindow {
            is_placeholder: false,
            usage_known: true,
            window_minutes: Some(30 * 1_440),
            used_percent: 25.0,
            quota_limit: Some(200.0),
            quota_unit: Some("credits".into()),
            resets_at: Some(reset(11, 12)),
        };
        assert_eq!(window_daily_target(&window, now()), Some(150.0 / 11.0));
        assert_eq!(
            format_window_target(&window, "auto", now(), &no_conversion).as_deref(),
            Some("≈ 13.64 credits / day to last until reset")
        );

        let percent_window = AllowanceWindow {
            quota_limit: None,
            quota_unit: None,
            ..window.clone()
        };
        assert_eq!(
            format_window_target(&percent_window, "auto", now(), &no_conversion).as_deref(),
            Some("≈ 6.82% / day to last until reset")
        );
        let unlabelled = AllowanceWindow {
            quota_unit: Some(String::new()),
            ..window.clone()
        };
        assert_eq!(
            format_window_target(&unlabelled, "auto", now(), &no_conversion),
            None
        );
        let placeholder = AllowanceWindow {
            is_placeholder: true,
            ..window.clone()
        };
        assert_eq!(window_daily_target(&placeholder, now()), None);
        let unknown = AllowanceWindow {
            usage_known: false,
            ..window.clone()
        };
        assert_eq!(window_daily_target(&unknown, now()), None);
        let weekly = AllowanceWindow {
            window_minutes: Some(7 * 1_440),
            ..window
        };
        assert_eq!(window_daily_target(&weekly, now()), None);
    }

    #[test]
    fn monthly_cost_targets_require_a_known_monthly_cap() {
        let cost = MonthlyCost {
            used: 20.0,
            limit: 80.0,
            currency: "USD".into(),
            period: Some(" Monthly ".into()),
            resets_at: Some(reset(11, 12)),
        };
        let convert = |amount: f64, source: &str, target: &str| {
            assert_eq!((source, target), ("USD", "EUR"));
            assert!((amount - 60.0 / 11.0).abs() < 1e-10);
            Some(5.02)
        };
        assert_eq!(
            format_monthly_cost_target(Some(&cost), "EUR", now(), &convert).as_deref(),
            Some("≈ €5.02 / day to last until reset")
        );
        assert_eq!(
            format_monthly_cost_target(None, "auto", now(), &no_conversion),
            None
        );
        let extra = MonthlyCost {
            period: Some("Extra usage".into()),
            ..cost.clone()
        };
        assert_eq!(
            format_monthly_cost_target(Some(&extra), "auto", now(), &no_conversion),
            None
        );
        let invalid = MonthlyCost {
            used: f64::NAN,
            ..cost
        };
        assert_eq!(
            format_monthly_cost_target(Some(&invalid), "auto", now(), &no_conversion),
            None
        );
    }

    #[test]
    fn daily_target_handles_far_future_dates() {
        let later = reset(1, 12) + Duration::days(31);
        assert!(daily_target(Some(31.0), Some(later), now()).is_some());
    }
}
