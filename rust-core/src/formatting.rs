//! Formatting helpers ported from `codexbar_gtk/format.py`.
//!
//! Keep this module free of UI and provider-service dependencies so its behavior
//! can be tested before the Python callers are migrated.

use chrono::{DateTime, Datelike, Duration, Utc};

pub const RESET_STYLES: [&str; 3] = ["countdown", "absolute", "both"];

pub fn compact_window_label(title: Option<&str>, window_minutes: Option<i64>) -> Option<String> {
    let text = title.unwrap_or_default().trim();
    if text.is_empty() {
        return None;
    }
    if text.to_lowercase().contains("session") {
        return Some(match window_minutes.filter(|m| *m > 0) {
            Some(minutes) if minutes % 60 == 0 => format!("{}h", minutes / 60),
            Some(minutes) => format!("{minutes}m"),
            None => "S".to_owned(),
        });
    }
    text.chars().next().map(|c| c.to_uppercase().collect())
}

pub fn format_percent(value: Option<f64>, decimals: usize) -> String {
    value
        .map(|v| format!("{v:.decimals$}%"))
        .unwrap_or_else(|| "—".into())
}

pub fn format_remaining(used_percent: Option<f64>, decimals: usize) -> String {
    used_percent
        .map(|v| format!("{:.decimals$}%", (100.0 - v).max(0.0)))
        .unwrap_or_else(|| "—".into())
}

pub fn format_countdown(target: Option<DateTime<Utc>>, now: DateTime<Utc>) -> Option<String> {
    let target = target?;
    let seconds = (target - now).num_seconds();
    if seconds <= 0 {
        return Some("now".into());
    }
    let days = seconds / 86_400;
    let hours = (seconds % 86_400) / 3_600;
    let minutes = (seconds % 3_600) / 60;
    let secs = seconds % 60;
    Some(if days >= 1 {
        format!("{days}d {hours}h")
    } else if hours >= 1 {
        format!("{hours}h {minutes}m")
    } else if minutes >= 1 {
        format!("{minutes}m {secs}s")
    } else {
        format!("{secs}s")
    })
}

pub fn format_absolute(target: Option<DateTime<Utc>>, now: DateTime<Utc>) -> Option<String> {
    let target = target?;
    Some(if target.date_naive() == now.date_naive() {
        target.format("%H:%M").to_string()
    } else if (now - target).num_days() <= 7 {
        target.format("%a %H:%M").to_string()
    } else {
        target.format("%b %d %H:%M").to_string()
    })
}

pub fn format_reset(
    target: Option<DateTime<Utc>>,
    style: &str,
    now: DateTime<Utc>,
) -> Option<String> {
    let countdown = format_countdown(target, now);
    let absolute = format_absolute(target, now);
    match style {
        "absolute" => absolute,
        "both" => match (countdown, absolute) {
            (Some(c), Some(a)) => Some(format!("resets in {c} · {a}")),
            (Some(c), None) => Some(c),
            (None, Some(a)) => Some(a),
            _ => None,
        },
        _ => match countdown {
            None => None,
            Some(c) if c == "now" => Some("resetting now".into()),
            Some(c) => Some(format!("resets in {c}")),
        },
    }
}

/// Match Python's comma-grouped numeric formatting for currency and credits.
fn grouped_number(value: f64, decimals: usize) -> String {
    let raw = format!("{value:.decimals$}");
    let (sign, unsigned) = raw
        .strip_prefix('-')
        .map(|s| ("-", s))
        .unwrap_or(("", raw.as_str()));
    let (integer, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    let mut grouped = String::with_capacity(raw.len() + integer.len() / 3);
    for (index, digit) in integer.chars().enumerate() {
        if index > 0 && (integer.len() - index) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(digit);
    }
    if decimals > 0 {
        grouped.push('.');
        grouped.push_str(fraction);
    }
    format!("{sign}{grouped}")
}

fn currency_symbol(currency: &str) -> Option<&'static str> {
    crate::currency::CURRENCIES
        .iter()
        .find_map(|(code, symbol, _)| (*code == currency).then_some(*symbol))
}

pub fn format_currency(value: Option<f64>, currency: &str, compact: bool) -> String {
    let Some(value) = value else {
        return "—".into();
    };
    let code = currency.to_uppercase();
    let symbol = currency_symbol(&code).unwrap_or("");
    let suffix = if symbol.is_empty() {
        format!(" {currency}")
    } else {
        String::new()
    };
    if compact && value.abs() >= 1_000.0 {
        format!(
            "{}{}k{}",
            symbol,
            grouped_number(value / 1_000.0, 1),
            suffix
        )
    } else if value.abs() >= 100.0 || value.fract() == 0.0 {
        format!("{}{}{}", symbol, grouped_number(value, 0), suffix)
    } else {
        format!("{}{}{}", symbol, grouped_number(value, 2), suffix)
    }
}

pub fn format_credits(value: Option<f64>) -> String {
    let Some(value) = value else {
        return "—".into();
    };
    let decimals = if value.abs() >= 100.0 {
        0
    } else if value.abs() >= 10.0 {
        1
    } else {
        2
    };
    grouped_number(value, decimals)
}

pub fn format_tokens(value: Option<i128>) -> String {
    let value = value.unwrap_or(0);
    if value < 0 {
        return value.to_string();
    }
    let value = value as u128;
    if value >= 1_000_000_000 {
        format!("{:.2}B", value as f64 / 1_000_000_000.0)
    } else if value >= 1_000_000 {
        format!("{:.1}M", value as f64 / 1_000_000.0)
    } else if value >= 1_000 {
        format!("{:.1}K", value as f64 / 1_000.0)
    } else {
        value.to_string()
    }
}

pub fn format_updated(target: Option<DateTime<Utc>>, now: DateTime<Utc>) -> Option<String> {
    let seconds = (now - target?).num_seconds();
    Some(if seconds < 60 {
        "just now".into()
    } else if seconds < 3_600 {
        format!("{}m ago", seconds / 60)
    } else if seconds < 86_400 {
        format!("{}h ago", seconds / 3_600)
    } else {
        format!("{}d ago", seconds / 86_400)
    })
}

pub fn format_reset_credits(
    expirations: &[Option<DateTime<Utc>>],
    style: &str,
    now: DateTime<Utc>,
) -> Option<(String, String, Vec<String>)> {
    if expirations.is_empty() {
        return None;
    }
    let count_text = if expirations.len() == 1 {
        "1 available".to_owned()
    } else {
        format!("{} available", expirations.len())
    };
    let items: Vec<(String, String)> = expirations
        .iter()
        .map(|expires_at| match expires_at {
            None => ("No expiry".into(), "No expiry".into()),
            Some(date) => {
                let countdown = format_countdown(Some(*date), now).expect("date provided");
                let compact = if style == "countdown" {
                    countdown
                } else {
                    format_absolute(Some(*date), now).unwrap_or_else(|| "No expiry".into())
                };
                (format!("Expires {compact}"), compact)
            }
        })
        .collect();
    let visible: Vec<&str> = items
        .iter()
        .take(4)
        .map(|(_, compact)| compact.as_str())
        .collect();
    let hidden = items.len().saturating_sub(visible.len());
    let compact_text = if hidden > 0 {
        format!("{} · +{hidden}", visible.join(" · "))
    } else {
        visible.join(" · ")
    };
    Some((
        count_text,
        compact_text,
        items.into_iter().map(|(line, _)| line).collect(),
    ))
}

/// Pace summary values are passed explicitly so this module has no dependency
/// on the Python-domain `Pace` object shape.
pub fn format_pace(
    stage: &str,
    delta_percent: Option<f64>,
    in_deficit: bool,
    in_reserve: bool,
    stage_label: &str,
) -> String {
    let value = delta_percent
        .map(|delta| delta.abs().round_ties_even() as i64)
        .unwrap_or(0);
    if stage == "onTrack" || value == 0 {
        "On pace".into()
    } else if in_deficit {
        format!("{value}% in deficit")
    } else if in_reserve {
        format!("{value}% in reserve")
    } else {
        stage_label.to_owned()
    }
}

pub fn format_window_span(minutes: Option<i64>) -> Option<String> {
    let minutes = minutes.filter(|minutes| *minutes != 0)?;
    Some(if minutes % 1_440 == 0 {
        let days = minutes / 1_440;
        if days > 1 {
            format!("{days}d")
        } else {
            "24h".into()
        }
    } else if minutes % 60 == 0 {
        format!("{}h", minutes / 60)
    } else {
        format!("{minutes}m")
    })
}

pub fn next_refresh_seconds(interval_seconds: i64) -> i64 {
    interval_seconds.max(5)
}

pub fn next_refresh_delta(interval_seconds: i64) -> Duration {
    Duration::seconds(next_refresh_seconds(interval_seconds))
}

pub fn workday_progress_percent(
    resets_at: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    work_days: u32,
) -> Option<f64> {
    let resets_at = resets_at?;
    if work_days == 0 {
        return None;
    }
    if now >= resets_at {
        return Some(100.0);
    }
    let mut cursor = resets_at - Duration::days(7);
    let mut total_work: f64 = 0.0;
    let mut elapsed_work: f64 = 0.0;
    while cursor < resets_at {
        if cursor.weekday().num_days_from_monday() < work_days {
            total_work += 1.0;
            if cursor <= now {
                elapsed_work += 1.0;
            }
        }
        cursor += Duration::days(1);
    }
    if total_work <= 0.0 {
        None
    } else {
        Some((elapsed_work / total_work * 100.0).clamp(0.0, 100.0))
    }
}

pub fn project_usage_at_reset(
    used_percent: f64,
    samples: &[(f64, f64)],
    resets_at: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
) -> Option<f64> {
    let resets_at = resets_at?;
    if samples.len() < 2 {
        return None;
    }
    let (first_t, first_v) = samples[0];
    let (last_t, last_v) = samples[samples.len() - 1];
    let span = last_t - first_t;
    if span <= 0.0 {
        return None;
    }
    let per_second = (last_v - first_v) / span;
    let hours_left = ((resets_at - now).num_milliseconds() as f64 / 3_600_000.0).max(0.0);
    Some((used_percent + per_second * hours_left * 3_600.0).clamp(0.0, 200.0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Duration, TimeZone};

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2025, 1, 1, 12, 0, 0).unwrap()
    }

    #[test]
    fn formats_countdowns_and_reset_styles() {
        let target = Some(now() + Duration::hours(4) + Duration::minutes(12));
        assert_eq!(format_countdown(target, now()).as_deref(), Some("4h 12m"));
        assert_eq!(
            format_reset(target, "countdown", now()).as_deref(),
            Some("resets in 4h 12m")
        );
        assert_eq!(
            format_reset(target, "both", now()).as_deref(),
            Some("resets in 4h 12m · 16:12")
        );
        assert_eq!(format_reset(None, "countdown", now()), None);
        assert_eq!(format_countdown(Some(now()), now()).as_deref(), Some("now"));
    }

    #[test]
    fn formats_labels_percentages_and_token_scales() {
        assert_eq!(
            compact_window_label(Some(" Session "), Some(300)).as_deref(),
            Some("5h")
        );
        assert_eq!(
            compact_window_label(Some("weekly"), None).as_deref(),
            Some("W")
        );
        assert_eq!(compact_window_label(Some("  "), None), None);
        assert_eq!(format_percent(Some(23.45), 1), "23.4%");
        assert_eq!(format_remaining(Some(110.0), 0), "0%");
        assert_eq!(format_tokens(Some(1_500_000)), "1.5M");
        assert_eq!(format_tokens(None), "0");
        assert_eq!(next_refresh_seconds(1), 5);
        assert_eq!(format_window_span(Some(2_880)), Some("2d".into()));
    }

    #[test]
    fn matches_currency_and_credit_rounding() {
        assert_eq!(format_currency(Some(1234.5), "USD", false), "$1,234");
        assert_eq!(format_currency(Some(12.5), "XXX", false), "12.50 XXX");
        assert_eq!(format_currency(Some(1500.0), "EUR", true), "€1.5k");
        assert_eq!(format_currency(None, "USD", false), "—");
        assert_eq!(format_credits(Some(12.345)), "12.3");
        assert_eq!(format_credits(None), "—");
    }

    #[test]
    fn formats_absolute_dates_updated_age_and_reset_credit_overflow() {
        let tomorrow = now() + Duration::days(1);
        assert_eq!(
            format_absolute(Some(tomorrow), now()).as_deref(),
            Some("Thu 12:00")
        );
        assert_eq!(
            format_updated(Some(now() - Duration::minutes(5)), now()).as_deref(),
            Some("5m ago")
        );
        let expirations = [Some(now() + Duration::hours(1)); 6];
        let credits = format_reset_credits(&expirations, "countdown", now()).unwrap();
        assert_eq!(credits.0, "6 available");
        assert_eq!(credits.1, "1h 0m · 1h 0m · 1h 0m · 1h 0m · +2");
    }

    #[test]
    fn formats_reset_credits_and_pace() {
        let dates = [Some(now() + Duration::hours(4)), None, Some(now())];
        let formatted = format_reset_credits(&dates, "countdown", now()).unwrap();
        assert_eq!(formatted.0, "3 available");
        assert_eq!(formatted.1, "4h 0m · No expiry · now");
        assert_eq!(formatted.2, ["Expires 4h 0m", "No expiry", "Expires now"]);
        assert_eq!(format_reset_credits(&[], "countdown", now()), None);
        assert_eq!(
            format_pace("onTrack", Some(0.0), false, false, "Behind"),
            "On pace"
        );
        assert_eq!(
            format_pace("behind", Some(-4.6), true, false, "Behind"),
            "5% in deficit"
        );
    }

    #[test]
    fn calculates_workday_progress_and_reset_projection() {
        let reset = Utc.with_ymd_and_hms(2025, 1, 6, 12, 0, 0).unwrap();
        let progress = workday_progress_percent(Some(reset), now(), 5).unwrap();
        assert_eq!(progress, 60.0);
        assert_eq!(workday_progress_percent(None, now(), 5), None);
        let samples = [(0.0, 10.0), (3600.0, 20.0)];
        assert_eq!(
            project_usage_at_reset(20.0, &samples, Some(now() + Duration::hours(2)), now()),
            Some(40.0)
        );
        assert_eq!(
            project_usage_at_reset(20.0, &samples[..1], Some(reset), now()),
            None
        );
    }
}
