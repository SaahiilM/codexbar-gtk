//! Deterministic native dashboard projections.
//!
//! This module translates the immutable B10 snapshot into display values but
//! keeps GTK objects and drawing out of the projection. `Option` and
//! `usage_known` are retained through projection so unavailable data never
//! becomes a displayed zero.

use chrono::{DateTime, Utc};
use codexbar_backend::{controller::ControllerSnapshot, BackendState, BackendStatus};
use codexbar_core::{
    currency::CurrencyCatalog,
    domain::{parse_timestamp, Pace, ProviderUsage},
    formatting,
};
use serde_json::{Map, Value};

#[derive(Clone, Debug, PartialEq)]
pub struct DashboardModel {
    pub status: String,
    pub refresh_error: Option<String>,
    pub overview_title: String,
    pub overview_detail: String,
    pub provider_count: String,
    pub highest_usage: String,
    pub credits: String,
    pub spend: String,
    pub spend_caption: Option<String>,
    pub empty: bool,
    pub providers: Vec<ProviderCardModel>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ProviderCardModel {
    pub provider_id: String,
    pub name: String,
    pub subtitle: String,
    pub accent: String,
    pub badge: Option<String>,
    pub badge_help: Option<String>,
    pub account_count: Option<String>,
    pub credits: Option<String>,
    pub spend: Option<String>,
    pub balance: Option<String>,
    pub error: Option<String>,
    pub windows: Vec<QuotaWindowModel>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct QuotaWindowModel {
    pub title: String,
    pub usage: String,
    pub usage_known: bool,
    pub fraction: Option<f64>,
    pub severity: MeterSeverity,
    pub fill_color: String,
    pub reset: Option<String>,
    pub pace: Option<String>,
    pub pace_severity: MeterSeverity,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum MeterSeverity {
    #[default]
    Normal,
    Warning,
    Critical,
}

struct ProjectionOptions<'a> {
    now: DateTime<Utc>,
    show_identity: bool,
    show_optional: bool,
    show_used: bool,
    show_pace: bool,
    thresholds: &'a [f64],
    reset_style: &'a str,
    preferred_currency: &'a str,
    currencies: &'a CurrencyCatalog,
}

pub fn project_dashboard(
    state: &BackendState<ControllerSnapshot>,
    preferences: &Map<String, Value>,
    currencies: &CurrencyCatalog,
    now: DateTime<Utc>,
) -> DashboardModel {
    let status = match (&state.status, state.snapshot.is_some()) {
        (BackendStatus::Idle, false) => "Loading provider data…".to_owned(),
        (BackendStatus::Refreshing, false) => "Loading provider data…".to_owned(),
        (BackendStatus::Refreshing, true) => "Refreshing provider data…".to_owned(),
        (BackendStatus::Ready, _) => format!("Updated · revision {}", state.sequence),
        (BackendStatus::Failed, true) => "Refresh failed · showing saved data".to_owned(),
        (BackendStatus::Failed, false) => "Provider refresh failed".to_owned(),
        (BackendStatus::Stopped, _) => "Backend stopped".to_owned(),
        (BackendStatus::Idle, true) => "Provider data available".to_owned(),
    };
    let snapshot = state.snapshot.as_deref();
    let refresh_error = match state.status {
        BackendStatus::Failed => Some(if snapshot.is_some() {
            "The latest refresh failed. Previously loaded data is still shown.".to_owned()
        } else {
            "Provider data could not be loaded. Check the CLI configuration and try again."
                .to_owned()
        }),
        BackendStatus::Ready
            if snapshot.is_some_and(|snapshot| {
                snapshot.last_error.is_some() || snapshot.cost_error.is_some()
            }) =>
        {
            Some(
                "Some provider or cost data could not be refreshed; showing available results."
                    .to_owned(),
            )
        }
        _ => None,
    };
    let Some(snapshot) = snapshot else {
        return DashboardModel {
            status,
            refresh_error,
            overview_title: if state.status == BackendStatus::Failed {
                "Provider data is unavailable".into()
            } else {
                "Your usage dashboard is getting ready".into()
            },
            overview_detail: "Provider status and quota details will appear here.".into(),
            provider_count: "—".into(),
            highest_usage: "—".into(),
            credits: "—".into(),
            spend: "—".into(),
            spend_caption: None,
            empty: false,
            providers: Vec::new(),
        };
    };

    let show_identity = !bool_pref(preferences, "hidePersonalInfo", false);
    let show_optional = bool_pref(preferences, "showOptionalCreditsAndExtraUsage", true);
    let show_used = bool_pref(preferences, "usageBarsShowUsed", true);
    let show_pace = bool_pref(preferences, "paceVisible", true);
    let reset_style = string_pref(preferences, "resetTimesOption", "countdown");
    let thresholds = number_array_pref(preferences, "quotaWarningThresholds", &[50.0, 20.0]);
    let preferred_currency = string_pref(preferences, "preferredCurrencyCode", "auto");
    let options = ProjectionOptions {
        now,
        show_identity,
        show_optional,
        show_used,
        show_pace,
        thresholds: &thresholds,
        reset_style: &reset_style,
        preferred_currency: &preferred_currency,
        currencies,
    };
    let providers = snapshot
        .providers
        .iter()
        .map(|provider| project_provider(provider, &options))
        .collect::<Vec<_>>();

    let known_usage = snapshot
        .providers
        .iter()
        .flat_map(|provider| provider.windows.iter())
        .filter(|window| {
            window.usage_known && !window.is_placeholder && window.used_percent.is_finite()
        })
        .map(|window| window.used_percent)
        .collect::<Vec<_>>();
    let highest = known_usage.iter().copied().reduce(f64::max);
    let credits = snapshot
        .providers
        .iter()
        .filter_map(|provider| provider.credits_remaining.filter(|value| *value != 0.0))
        .collect::<Vec<_>>();
    let credit_total = credits
        .iter()
        .copied()
        .sum::<f64>()
        .is_finite()
        .then(|| credits.iter().sum::<f64>())
        .filter(|total| *total != 0.0);
    let overview = overview(snapshot, &thresholds, now);
    let spend_summary = snapshot
        .spend
        .as_ref()
        .filter(|summary| summary.cost_known)
        .map(|summary| {
            let partial = summary.cost_partial || snapshot.cost_error.is_some();
            let caption = if partial {
                Some("Known subtotal".to_owned())
            } else {
                summary.history_label.clone()
            };
            if !summary.cost_known {
                return ("—".to_owned(), None);
            }
            let source = summary.currency.as_str();
            let (amount, code) =
                convert_or_source(summary.total_cost, source, &preferred_currency, currencies);
            (
                format!(
                    "{}{}",
                    if partial { "≥ " } else { "" },
                    formatting::format_currency(Some(amount), &code, false)
                ),
                caption,
            )
        })
        .unwrap_or_else(|| ("—".to_owned(), None));

    DashboardModel {
        status,
        refresh_error,
        overview_title: overview.0,
        overview_detail: overview.1,
        provider_count: snapshot.providers.len().to_string(),
        highest_usage: highest.map_or_else(
            || "—".to_owned(),
            |value| formatting::format_percent(Some(value), 0),
        ),
        credits: credit_total.map_or_else(|| "—".to_owned(), format_integer_credits),
        spend: spend_summary.0,
        spend_caption: spend_summary.1,
        empty: snapshot.providers.is_empty(),
        providers,
    }
}

fn project_provider(
    provider: &ProviderUsage,
    options: &ProjectionOptions<'_>,
) -> ProviderCardModel {
    let mut subtitle = Vec::new();
    if options.show_identity {
        if let Some(plan) = provider.plan.as_deref().filter(|value| !value.is_empty()) {
            subtitle.push(plan.to_owned());
        }
        if let Some(email) = provider
            .account_email
            .as_deref()
            .filter(|value| !value.is_empty())
        {
            subtitle.push(email.to_owned());
        }
    }
    if subtitle.is_empty() {
        if let Some(source) = provider.source.as_deref().filter(|value| !value.is_empty()) {
            subtitle.push(source.to_owned());
        }
    }
    if let Some(updated) = formatting::format_updated(provider.updated_at, options.now) {
        subtitle.push(format!("updated {updated}"));
    }

    let status_badge = provider
        .status_level
        .as_deref()
        .filter(|value| !value.is_empty())
        .map(|value| {
            value
                .replace('_', " ")
                .split_whitespace()
                .map(capitalize)
                .collect::<Vec<_>>()
                .join(" ")
        });
    let reset_credit_dates = provider
        .reset_credits
        .iter()
        .map(|credit| {
            credit
                .get("expires_at")
                .or_else(|| credit.get("expiresAt"))
                .and_then(Value::as_str)
                .and_then(|value| parse_timestamp(Some(value)))
        })
        .collect::<Vec<_>>();
    let (badge, badge_help) = if let Some(status_badge) = status_badge {
        (Some(status_badge), provider.status_description.clone())
    } else if let Some((count, compact, help)) =
        formatting::format_reset_credits(&reset_credit_dates, options.reset_style, options.now)
    {
        let title = provider
            .reset_credits
            .first()
            .and_then(|credit| credit.get("title"))
            .and_then(Value::as_str)
            .filter(|title| !title.is_empty())
            .unwrap_or("Rate limit resets");
        let help = std::iter::once(title.to_owned())
            .chain(std::iter::once(String::new()))
            .chain(
                help.into_iter()
                    .enumerate()
                    .map(|(index, item)| format!("{}. {item}", index + 1)),
            )
            .collect::<Vec<_>>()
            .join("\n");
        (Some(format!("{count} · {compact}")), Some(help))
    } else if provider.reset_credits_available > 0 {
        (
            Some(format!("{} resets", provider.reset_credits_available)),
            None,
        )
    } else {
        (None, None)
    };

    let cost = if options.show_optional {
        provider
            .cost
            .as_ref()
            .filter(|cost| cost.used != 0.0 || cost.limit != 0.0 || cost.balance.is_some())
    } else {
        None
    };
    let spend = cost.and_then(|cost| {
        let source = if cost.currency.trim().is_empty() {
            "USD"
        } else {
            &cost.currency
        };
        if cost.has_limit() {
            let (used, code) = convert_or_source(
                cost.used,
                source,
                options.preferred_currency,
                options.currencies,
            );
            let (limit, limit_code) = convert_or_source(
                cost.limit,
                source,
                options.preferred_currency,
                options.currencies,
            );
            Some(format!(
                "{} of {}",
                formatting::format_currency(Some(used), &code, false),
                formatting::format_currency(Some(limit), &limit_code, false)
            ))
        } else if cost.balance.is_some() {
            let (balance, code) = convert_or_source(
                cost.balance?,
                source,
                options.preferred_currency,
                options.currencies,
            );
            Some(format!(
                "{} balance",
                formatting::format_currency(Some(balance), &code, false)
            ))
        } else {
            let (used, code) = convert_or_source(
                cost.used,
                source,
                options.preferred_currency,
                options.currencies,
            );
            Some(format!(
                "{} spent",
                formatting::format_currency(Some(used), &code, false)
            ))
        }
    });
    let balance = if options.show_optional {
        cost.and_then(|cost| cost.balance).map(|amount| {
            let source = cost.map(|cost| cost.currency.as_str()).unwrap_or("USD");
            let (amount, code) = convert_or_source(
                amount,
                source,
                options.preferred_currency,
                options.currencies,
            );
            formatting::format_currency(Some(amount), &code, false)
        })
    } else {
        None
    };
    let credits = if options.show_optional {
        provider.credits_remaining.map(|value| {
            format!(
                "{} {} remaining",
                formatting::format_credits(Some(value)),
                provider.credits_unit
            )
        })
    } else {
        None
    };

    let windows = provider
        .windows
        .iter()
        .map(|window| {
            let pace = provider.pace_for(window);
            let known =
                window.usage_known && !window.is_placeholder && window.used_percent.is_finite();
            let usage_value = known.then_some(window.used_percent);
            let pace_severity = pace.map_or(MeterSeverity::Normal, pace_severity);
            let meter_severity = usage_value.map_or(MeterSeverity::Normal, |value| {
                severity(value, options.thresholds)
            });
            let fill_color = if !known {
                "#808892".to_owned()
            } else {
                match meter_severity {
                    MeterSeverity::Normal => safe_color(&provider.accent_color),
                    MeterSeverity::Warning => "#e0a030".to_owned(),
                    MeterSeverity::Critical => "#e05252".to_owned(),
                }
            };
            QuotaWindowModel {
                title: window.title.clone(),
                usage: if !known {
                    "Unavailable".into()
                } else if options.show_used {
                    formatting::format_percent(usage_value, 0)
                } else {
                    formatting::format_remaining(usage_value, 0)
                },
                usage_known: known,
                fraction: usage_value.map(|value| (value / 100.0).clamp(0.0, 1.0)),
                severity: meter_severity,
                fill_color,
                reset: formatting::format_reset(window.resets_at, options.reset_style, options.now)
                    .or_else(|| window.reset_description.clone()),
                pace: if options.show_pace {
                    pace.map(format_pace)
                } else {
                    None
                },
                pace_severity,
            }
        })
        .collect();

    ProviderCardModel {
        provider_id: provider.provider_id.clone(),
        name: provider.display_name.clone(),
        subtitle: subtitle.join(" · "),
        accent: provider.accent_color.clone(),
        badge,
        badge_help,
        account_count: (provider.accounts.len() > 1)
            .then(|| format!("{} accounts", provider.accounts.len())),
        credits,
        spend,
        balance,
        error: provider.error.clone(),
        windows,
    }
}

fn overview(
    snapshot: &ControllerSnapshot,
    thresholds: &[f64],
    now: DateTime<Utc>,
) -> (String, String) {
    let active = snapshot
        .providers
        .iter()
        .filter(|provider| !provider.has_error())
        .collect::<Vec<_>>();
    if active.is_empty() {
        return (
            "Nothing to track yet".into(),
            "Enable a provider in Settings → Providers".into(),
        );
    }
    let mut highest: Option<(&ProviderUsage, f64)> = None;
    for provider in &active {
        for window in provider.windows.iter().filter(|window| {
            window.usage_known && !window.is_placeholder && window.used_percent.is_finite()
        }) {
            if highest.is_none_or(|(_, value)| window.used_percent > value) {
                highest = Some((provider, window.used_percent));
            }
        }
    }
    let max_threshold = thresholds.iter().copied().reduce(f64::max).unwrap_or(95.0);
    let min_threshold = thresholds.iter().copied().reduce(f64::min).unwrap_or(50.0);
    let headline = highest.map_or_else(
        || "Usage is unavailable".to_owned(),
        |(provider, value)| {
            if value >= max_threshold {
                format!("{} is running low", provider.display_name)
            } else if value >= min_threshold {
                format!("{} is picking up usage", provider.display_name)
            } else {
                "Everything is within limits".to_owned()
            }
        },
    );
    let next_reset = active
        .iter()
        .flat_map(|provider| {
            provider.windows.iter().filter_map(move |window| {
                window
                    .resets_at
                    .map(|reset| (reset, window.title.to_lowercase()))
            })
        })
        .min_by_key(|(reset, _)| *reset);
    let mut detail = Vec::new();
    if let Some((reset, name)) = next_reset {
        if let Some(countdown) = formatting::format_countdown(Some(reset), now) {
            detail.push(format!("next reset: {name} in {countdown}"));
        }
    }
    if let Some(updated) = snapshot
        .updated_at
        .and_then(|updated| formatting::format_updated(Some(updated), now))
    {
        detail.push(format!("updated {updated}"));
    }
    (headline, detail.join(" · "))
}

fn format_integer_credits(value: f64) -> String {
    let rounded = format!("{value:.0}");
    let negative = rounded.starts_with('-');
    let digits = rounded.trim_start_matches('-');
    let mut groups = Vec::new();
    let mut end = digits.len();
    while end > 3 {
        groups.push(digits[end - 3..end].to_owned());
        end -= 3;
    }
    groups.push(digits[..end].to_owned());
    groups.reverse();
    format!("{}{}", if negative { "-" } else { "" }, groups.join(","))
}

fn convert_or_source(
    amount: f64,
    source: &str,
    preferred: &str,
    currencies: &CurrencyCatalog,
) -> (f64, String) {
    let source = if source.trim().is_empty() {
        "USD"
    } else {
        source.trim()
    };
    let target = preferred.trim().to_uppercase();
    if target.is_empty()
        || target == "AUTO"
        || target == source.to_uppercase()
        || currencies.rate(&target).is_none()
    {
        return (amount, source.to_owned());
    }
    currencies
        .convert(amount, source, &target)
        .map(|converted| (converted, target))
        .unwrap_or_else(|| (amount, source.to_owned()))
}

fn severity(value: f64, thresholds: &[f64]) -> MeterSeverity {
    let mut sorted = thresholds.to_vec();
    sorted.sort_by(|a, b| b.total_cmp(a));
    match sorted.iter().position(|threshold| value >= *threshold) {
        Some(0) => MeterSeverity::Critical,
        Some(_) => MeterSeverity::Warning,
        None => MeterSeverity::Normal,
    }
}

fn safe_color(value: &str) -> String {
    let hex = value.strip_prefix('#').unwrap_or(value);
    if hex.len() == 6 && hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        format!("#{hex}")
    } else {
        "#6366f1".to_owned()
    }
}

fn pace_severity(pace: &Pace) -> MeterSeverity {
    if pace.stage == "farAhead" {
        MeterSeverity::Critical
    } else if pace.in_deficit() {
        MeterSeverity::Warning
    } else {
        MeterSeverity::Normal
    }
}

fn format_pace(pace: &Pace) -> String {
    formatting::format_pace(
        &pace.stage,
        pace.delta_percent,
        pace.in_deficit(),
        pace.in_reserve(),
        pace.stage_label(),
    )
}

fn bool_pref(preferences: &Map<String, Value>, key: &str, fallback: bool) -> bool {
    preferences
        .get(key)
        .and_then(Value::as_bool)
        .unwrap_or(fallback)
}

fn string_pref(preferences: &Map<String, Value>, key: &str, fallback: &str) -> String {
    preferences
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(fallback)
        .to_owned()
}

fn number_array_pref(preferences: &Map<String, Value>, key: &str, fallback: &[f64]) -> Vec<f64> {
    preferences
        .get(key)
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_f64)
                .filter(|value| value.is_finite())
                .collect()
        })
        .filter(|values: &Vec<f64>| !values.is_empty())
        .unwrap_or_else(|| fallback.to_vec())
}

fn capitalize(value: &str) -> String {
    let mut chars = value.chars();
    chars
        .next()
        .map(|first| first.to_uppercase().collect::<String>() + chars.as_str())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use codexbar_backend::BackendStatus;
    use codexbar_core::domain::{CostInfo, RateWindow, SpendSummary};
    use serde_json::json;
    use std::time::SystemTime;

    fn window(key: &str, known: bool, used: f64) -> RateWindow {
        RateWindow {
            key: key.into(),
            title: key.into(),
            used_percent: used,
            resets_at: None,
            reset_description: None,
            window_minutes: Some(300),
            next_regen_percent: None,
            is_placeholder: false,
            quota_limit: None,
            quota_unit: None,
            usage_known: known,
        }
    }

    fn provider(id: &str, windows: Vec<RateWindow>) -> ProviderUsage {
        ProviderUsage {
            provider_id: id.into(),
            display_name: id.into(),
            source: None,
            version: None,
            updated_at: None,
            account_email: None,
            plan: None,
            login_method: None,
            windows,
            pace: Default::default(),
            credits_remaining: None,
            credits_unit: "credits".into(),
            credits_available: false,
            cost: None,
            status_level: None,
            status_description: None,
            error: None,
            details: vec![],
            reset_credits_available: 0,
            reset_credits: vec![],
            credit_events: vec![],
            accounts: vec![],
            selected_account: None,
            accent_color: "#5468ff".into(),
            raw: json!({}),
        }
    }

    fn snapshot(providers: Vec<ProviderUsage>) -> ControllerSnapshot {
        ControllerSnapshot {
            revision: 1,
            version: "0.82.0 (57)".into(),
            updated_at: None,
            last_error: None,
            cost_error: None,
            providers,
            spend: None,
            sessions: vec![],
            history: vec![],
            tray_selection: None,
        }
    }

    fn spend_summary(known: bool, partial: bool) -> SpendSummary {
        SpendSummary {
            total_cost: 3.5,
            cost_known: known,
            cost_partial: partial,
            currency: "USD".into(),
            total_tokens: 10,
            total_tokens_known: true,
            total_tokens_partial: false,
            coverage: Default::default(),
            provenance: "synthetic_history".into(),
            reporting_period: None,
            history_label: Some("History".into()),
            history_coverage_established: true,
            daily: vec![],
            projects: vec![],
            models: vec![],
            session_cost: 0.0,
            session_cost_known: false,
            session_cost_partial: false,
            session_tokens: 0,
            session_tokens_known: false,
            session_tokens_partial: false,
            last30_cost: 0.0,
            last30_cost_known: false,
            last30_cost_partial: false,
            last30_tokens: 0,
            last30_tokens_known: false,
            last30_tokens_partial: false,
            incomplete_requests: 0,
            error: None,
            providers: vec![],
        }
    }

    fn state(
        status: BackendStatus,
        snapshot: Option<ControllerSnapshot>,
    ) -> BackendState<ControllerSnapshot> {
        BackendState {
            sequence: 1,
            changed_at: SystemTime::now(),
            status,
            snapshot: snapshot.map(std::sync::Arc::new),
            last_error: None,
        }
    }

    #[test]
    fn loading_empty_and_retained_failure_are_distinct() {
        let prefs = Map::new();
        let catalog = CurrencyCatalog::default();
        let loading = project_dashboard(
            &state(BackendStatus::Idle, None),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert!(!loading.empty);
        assert_eq!(loading.provider_count, "—");
        assert!(loading.overview_title.contains("getting ready"));

        let empty = project_dashboard(
            &state(BackendStatus::Ready, Some(snapshot(vec![]))),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert!(empty.empty);
        assert_eq!(empty.provider_count, "0");

        let retained = project_dashboard(
            &state(
                BackendStatus::Failed,
                Some(snapshot(vec![provider("alpha", vec![])])),
            ),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert!(retained.refresh_error.is_some());
        assert_eq!(retained.providers.len(), 1);
        assert!(retained.status.contains("saved data"));
    }

    #[test]
    fn unknown_usage_is_unavailable_and_known_zero_remains_zero() {
        let mut only_unknown = provider("unknown", vec![window("session", false, 0.0)]);
        only_unknown.credits_remaining = None;
        let prefs = Map::new();
        let catalog = CurrencyCatalog::default();
        let model = project_dashboard(
            &state(
                BackendStatus::Ready,
                Some(snapshot(vec![only_unknown.clone()])),
            ),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(model.highest_usage, "—");
        assert!(!model.providers[0].windows[0].usage_known);
        assert_eq!(model.providers[0].windows[0].usage, "Unavailable");
        assert_eq!(model.providers[0].windows[0].fraction, None);
        assert_eq!(model.overview_title, "Usage is unavailable");

        let known = provider("known", vec![window("session", true, 0.0)]);
        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(snapshot(vec![known]))),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(model.highest_usage, "0%");
        assert_eq!(model.providers[0].windows[0].usage, "0%");
        assert_eq!(model.providers[0].windows[0].fraction, Some(0.0));
        assert_eq!(model.providers[0].windows[0].fill_color, "#5468ff");

        let high = provider("high", vec![window("session", true, 75.0)]);
        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(snapshot(vec![high]))),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(model.providers[0].windows[0].fill_color, "#e05252");
        assert_eq!(model.overview_title, "high is running low");
    }

    #[test]
    fn preference_visibility_and_provider_order_are_preserved() {
        let mut alpha = provider("alpha", vec![window("session", true, 52.0)]);
        alpha.plan = Some("Pro".into());
        alpha.account_email = Some("synthetic@example.test".into());
        alpha.credits_remaining = Some(0.0);
        let beta = provider("beta", vec![window("session", true, 20.0)]);
        let prefs = serde_json::from_value::<Map<String, Value>>(
            json!({"hidePersonalInfo":true,"usageBarsShowUsed":false}),
        )
        .unwrap();
        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(snapshot(vec![alpha, beta]))),
            &prefs,
            &CurrencyCatalog::default(),
            Utc::now(),
        );
        assert_eq!(
            model
                .providers
                .iter()
                .map(|p| p.provider_id.as_str())
                .collect::<Vec<_>>(),
            ["alpha", "beta"]
        );
        assert!(!model.providers[0]
            .subtitle
            .contains("synthetic@example.test"));
        assert_eq!(model.providers[0].windows[0].usage, "48%");
        assert_eq!(
            model.providers[0].credits.as_deref(),
            Some("0.00 credits remaining")
        );
        assert_eq!(model.credits, "—");
    }

    #[test]
    fn unsupported_currency_falls_back_to_source_currency() {
        let (amount, code) = convert_or_source(4.25, "USD", "ZZZ", &CurrencyCatalog::default());
        assert_eq!(amount, 4.25);
        assert_eq!(code, "USD");
    }

    #[test]
    fn spend_partial_caption_and_unknown_state_are_preserved() {
        let prefs = Map::new();
        let catalog = CurrencyCatalog::default();

        let mut partial_snapshot = snapshot(vec![]);
        partial_snapshot.spend = Some(spend_summary(true, true));
        let partial = project_dashboard(
            &state(BackendStatus::Ready, Some(partial_snapshot)),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(partial.spend, "≥ $3.50");
        assert_eq!(partial.spend_caption.as_deref(), Some("Known subtotal"));

        let mut complete_snapshot = snapshot(vec![]);
        complete_snapshot.spend = Some(spend_summary(true, false));
        let complete = project_dashboard(
            &state(BackendStatus::Ready, Some(complete_snapshot)),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(complete.spend, "$3.50");
        assert_eq!(complete.spend_caption.as_deref(), Some("History"));

        let mut unknown_snapshot = snapshot(vec![]);
        unknown_snapshot.spend = Some(spend_summary(false, false));
        let unknown = project_dashboard(
            &state(BackendStatus::Ready, Some(unknown_snapshot)),
            &prefs,
            &catalog,
            Utc::now(),
        );
        assert_eq!(unknown.spend, "—");
        assert_eq!(unknown.spend_caption, None);
    }

    #[test]
    fn provider_cost_and_reset_credit_chips_keep_reference_behavior() {
        let now = DateTime::parse_from_rfc3339("2026-10-31T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut fixture = provider("Codex", vec![window("primary", true, 0.0)]);
        fixture.cost = Some(CostInfo {
            used: 0.0,
            limit: 0.0,
            currency: "USD".into(),
            period: None,
            balance: None,
            personal_used: None,
            resets_at: None,
        });
        fixture.reset_credits = vec![json!({
            "title": "Synthetic credit",
            "expires_at": "2026-11-01T12:00:00Z"
        })];
        fixture.credits_remaining = Some(25.5);
        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(snapshot(vec![fixture]))),
            &Map::new(),
            &CurrencyCatalog::default(),
            now,
        );
        let card = &model.providers[0];
        assert_eq!(card.spend, None); // default zero CostInfo is not a known charge
        assert!(card
            .badge
            .as_deref()
            .is_some_and(|badge| badge.starts_with("1 available · ")));
        assert!(card
            .badge_help
            .as_deref()
            .is_some_and(|help| help.contains("1. Expires ")));
        assert_eq!(model.credits, "26");
    }

    #[test]
    fn meter_severity_uses_existing_threshold_order_policy() {
        assert_eq!(severity(75.0, &[50.0, 20.0]), MeterSeverity::Critical);
        assert_eq!(severity(25.0, &[50.0, 20.0]), MeterSeverity::Warning);
        assert_eq!(severity(10.0, &[50.0, 20.0]), MeterSeverity::Normal);
    }
}
