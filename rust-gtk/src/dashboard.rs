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
    history::Sample,
    pace::{self, AllowanceWindow, MonthlyCost},
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
    pub cost_target: Option<String>,
    pub burndown: Option<BurndownModel>,
    pub detail_charts: Vec<BarChartModel>,
    pub credit_chart: Option<BarChartModel>,
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
    pub warning_markers: Vec<f64>,
    pub workday_tick: Option<f64>,
    pub tick_appearance: String,
    pub daily_target: Option<String>,
    pub trend: Option<TrendModel>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BurndownModel {
    pub projected_percent: f64,
    pub will_run_out: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrendModel {
    pub points: Vec<(f64, f64)>,
    pub accessible_description: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BarChartModel {
    pub title: String,
    pub unit: Option<String>,
    pub points: Vec<(String, f64)>,
    pub accessible_description: String,
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
    markers_visible: bool,
    work_days: u32,
    tick_appearance: &'a str,
    burndown_enabled: bool,
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
    let work_days = number_pref(preferences, "weeklyProgressWorkDays", 5.0).clamp(0.0, 7.0) as u32;
    let tick_appearance = string_pref(preferences, "workdayTickAppearance", "subtle");
    let preferred_currency = string_pref(preferences, "preferredCurrencyCode", "auto");
    let options = ProjectionOptions {
        now,
        show_identity,
        show_optional,
        show_used,
        show_pace,
        thresholds: &thresholds,
        markers_visible: bool_pref(preferences, "quotaWarningMarkersVisible", true),
        work_days,
        tick_appearance: &tick_appearance,
        burndown_enabled: bool_pref(preferences, "quotaBurndownEnabled", true),
        reset_style: &reset_style,
        preferred_currency: &preferred_currency,
        currencies,
    };
    let providers = snapshot
        .providers
        .iter()
        .map(|provider| project_provider(provider, &options, &snapshot.history))
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
    history: &[Sample],
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

    let convert = |amount: f64, source: &str, target: &str| {
        options.currencies.convert(amount, source, target)
    };
    let cost_target = cost.and_then(|cost| {
        let monthly = MonthlyCost {
            used: cost.used,
            limit: cost.limit,
            currency: cost.currency.clone(),
            period: cost.period.clone(),
            resets_at: cost.resets_at,
        };
        pace::format_monthly_cost_target(
            Some(&monthly),
            options.preferred_currency,
            options.now,
            &convert,
        )
    });

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
            let samples =
                quota_history_series(history, &provider.provider_id, &window.key, options.now);
            let trend =
                (known && samples.len() >= 3).then(|| trend_model(&window.title, samples.clone()));
            let allowance = AllowanceWindow {
                is_placeholder: window.is_placeholder,
                usage_known: known,
                window_minutes: window.window_minutes,
                used_percent: window.used_percent,
                quota_limit: window.quota_limit,
                quota_unit: window.quota_unit.clone(),
                resets_at: window.resets_at,
            };
            let daily_target = if options.show_pace {
                pace::format_window_target(
                    &allowance,
                    options.preferred_currency,
                    options.now,
                    &convert,
                )
            } else {
                None
            };
            let workday_tick = if window.key == "secondary" && options.work_days > 0 {
                formatting::workday_progress_percent(
                    window.resets_at,
                    options.now,
                    options.work_days,
                )
            } else {
                None
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
                warning_markers: if known && options.markers_visible {
                    options.thresholds.to_vec()
                } else {
                    Vec::new()
                },
                workday_tick: workday_tick.filter(|_| options.tick_appearance != "hidden"),
                tick_appearance: options.tick_appearance.to_owned(),
                daily_target,
                trend,
            }
        })
        .collect();

    let burndown = if options.burndown_enabled {
        provider.windows.first().and_then(|window| {
            if !window.usage_known || window.is_placeholder || !window.used_percent.is_finite() {
                return None;
            }
            let samples =
                quota_history_series(history, &provider.provider_id, &window.key, options.now);
            let projected = formatting::project_usage_at_reset(
                window.used_percent,
                &samples,
                window.resets_at,
                options.now,
            )?;
            Some(BurndownModel {
                projected_percent: projected,
                will_run_out: projected >= 95.0,
            })
        })
    } else {
        None
    };

    let detail_charts = provider
        .details
        .iter()
        .filter_map(|section| section.chart.as_ref())
        .filter(|chart| !chart.points.is_empty())
        .map(|chart| {
            let title = chart
                .title
                .clone()
                .filter(|title| !title.trim().is_empty())
                .unwrap_or_else(|| "Usage details".to_owned());
            bar_chart_model(title, chart.unit.clone(), chart.points.clone())
        })
        .collect();
    let credit_chart = (!provider.credit_events.is_empty()).then(|| {
        let points = provider
            .credit_events
            .iter()
            .rev()
            .take(24)
            .map(|event| {
                let label = event.date.get(5..10).unwrap_or(&event.date).to_owned();
                (label, event.used)
            })
            .collect::<Vec<_>>();
        bar_chart_model(
            "Credits used".to_owned(),
            None,
            points.into_iter().rev().collect(),
        )
    });

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
        cost_target,
        burndown,
        detail_charts,
        credit_chart,
        error: provider.error.clone(),
        windows,
    }
}

fn quota_history_series(
    history: &[Sample],
    provider_id: &str,
    window_key: &str,
    now: DateTime<Utc>,
) -> Vec<(f64, f64)> {
    let now_seconds = now.timestamp() as f64 + f64::from(now.timestamp_subsec_nanos()) / 1e9;
    let cutoff = now_seconds - 24.0 * 60.0 * 60.0;
    let mut points = history
        .iter()
        .filter(|sample| {
            sample.provider == provider_id
                && sample.window == window_key
                && sample.timestamp.is_finite()
                && sample.timestamp >= cutoff
                && sample.used_percent.is_finite()
        })
        .map(|sample| (sample.timestamp, sample.used_percent))
        .collect::<Vec<_>>();
    points.sort_by(|left, right| left.0.total_cmp(&right.0));
    points
}

fn trend_model(window_title: &str, points: Vec<(f64, f64)>) -> TrendModel {
    let first = points.first().map(|point| point.1).unwrap_or_default();
    let last = points.last().map(|point| point.1).unwrap_or_default();
    TrendModel {
        accessible_description: format!(
            "{} quota history over the last 24 hours: {} readings, from {:.0}% to {:.0}%.",
            window_title,
            points.len(),
            first,
            last
        ),
        points,
    }
}

fn bar_chart_model(
    title: String,
    unit: Option<String>,
    points: Vec<(String, f64)>,
) -> BarChartModel {
    let points = points
        .into_iter()
        .filter(|(_, value)| value.is_finite())
        .collect::<Vec<_>>();
    let unit_description = unit
        .as_deref()
        .map(|unit| format!(" ({unit})"))
        .unwrap_or_default();
    let accessible_description = if points.is_empty() {
        format!("{title}: no chart data{unit_description}")
    } else {
        let readings = points
            .iter()
            .map(|(label, value)| format!("{label}: {value:.2}"))
            .collect::<Vec<_>>()
            .join(", ");
        format!(
            "{title}, {} readings{unit_description}: {readings}",
            points.len()
        )
    };
    BarChartModel {
        title,
        unit,
        points,
        accessible_description,
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

fn number_pref(preferences: &Map<String, Value>, key: &str, fallback: f64) -> f64 {
    preferences
        .get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .unwrap_or(fallback)
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
    use codexbar_core::domain::{
        CostInfo, CreditEvent, DetailChart, DetailSection, RateWindow, SpendSummary,
    };
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

    fn sample(timestamp: f64, provider: &str, window: &str, used_percent: f64) -> Sample {
        Sample {
            timestamp,
            provider: provider.to_owned(),
            window: window.to_owned(),
            used_percent,
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
    fn history_projection_keeps_known_usage_and_uses_only_recent_matching_samples() {
        use chrono::{Duration, TimeZone};

        let now = Utc.with_ymd_and_hms(2026, 10, 31, 12, 0, 0).unwrap();
        let now_seconds = now.timestamp() as f64;
        let mut primary = window("primary", true, 70.0);
        primary.resets_at = Some(now + Duration::hours(2));
        let mut secondary = window("secondary", true, 0.0);
        secondary.window_minutes = Some(30 * 1_440);
        secondary.quota_limit = Some(900.0);
        secondary.quota_unit = Some("credits".into());
        secondary.used_percent = 40.0;
        secondary.resets_at = Some(now + Duration::days(20));
        let mut weekly = window("secondary", true, 55.0);
        weekly.window_minutes = Some(7 * 1_440);
        weekly.resets_at = Some(now + Duration::days(5));

        let mut fixture = provider("alpha", vec![primary, secondary]);
        fixture.cost = Some(CostInfo {
            used: 25.0,
            limit: 100.0,
            currency: "USD".into(),
            period: Some("This month".into()),
            balance: None,
            personal_used: None,
            resets_at: Some(now + Duration::days(20)),
        });
        fixture.details = vec![DetailSection {
            title: Some("Synthetic model usage".into()),
            rows: vec![],
            chart: Some(DetailChart {
                kind: "bars".into(),
                title: Some("Tokens by model".into()),
                unit: Some("tokens".into()),
                points: (0..26)
                    .map(|index| (format!("m{index}"), index as f64))
                    .collect(),
            }),
        }];
        fixture.credit_events = (0..26)
            .map(|index| CreditEvent {
                id: format!("e{index}"),
                date: format!("2026-10-{:02}", index + 1),
                service: "synthetic".into(),
                used: index as f64,
            })
            .collect();

        let mut fixture_snapshot = snapshot(vec![fixture, provider("beta", vec![weekly])]);
        fixture_snapshot.history = vec![
            sample(now_seconds - 25.0 * 3_600.0, "alpha", "primary", 10.0),
            sample(now_seconds - 7_200.0, "alpha", "primary", 20.0),
            sample(now_seconds - 3_600.0, "alpha", "primary", 25.0),
            sample(now_seconds - 1_800.0, "alpha", "primary", 30.0),
            sample(now_seconds - 1_800.0, "other", "primary", 95.0),
            sample(now_seconds - 1_800.0, "alpha", "secondary", 0.0),
        ];

        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(fixture_snapshot)),
            &Map::new(),
            &CurrencyCatalog::default(),
            now,
        );
        let card = &model.providers[0];
        let primary = &card.windows[0];
        let trend = primary.trend.as_ref().expect("three recent readings");
        assert_eq!(trend.points.len(), 3);
        assert_eq!(trend.points.first().unwrap().1, 20.0);
        assert_eq!(trend.points.last().unwrap().1, 30.0);
        assert!(trend.accessible_description.contains("3 readings"));
        let burndown = card.burndown.as_ref().expect("known primary with history");
        assert!(burndown.projected_percent > 82.0 && burndown.projected_percent < 85.0);
        assert!(!burndown.will_run_out);
        assert_eq!(primary.warning_markers, [50.0, 20.0]);
        assert!(card.windows[1]
            .daily_target
            .as_deref()
            .is_some_and(|target| target.starts_with("≈ ")));
        assert_eq!(model.providers[1].windows[0].workday_tick, Some(40.0));
        assert!(card
            .cost_target
            .as_deref()
            .is_some_and(|target| target.starts_with("≈ $")));
        let detail = &card.detail_charts[0];
        assert_eq!(detail.points.len(), 26);
        assert_eq!(detail.points.first().unwrap().0, "m0");
        assert!(detail.accessible_description.contains("26 readings"));
        assert!(detail.accessible_description.contains("(tokens)"));
        let credits = card.credit_chart.as_ref().unwrap();
        assert_eq!(credits.points.len(), 24);
        assert_eq!(credits.points.first().unwrap().0, "10-03");
        assert!(credits.accessible_description.contains("10-03: 2.00"));
    }

    #[test]
    fn unknown_usage_and_empty_history_never_create_zero_trends_or_burndown() {
        use chrono::{Duration, TimeZone};

        let now = Utc.with_ymd_and_hms(2026, 10, 31, 12, 0, 0).unwrap();
        let mut unknown = window("primary", false, 0.0);
        unknown.resets_at = Some(now + Duration::hours(2));
        let mut fixture_snapshot = snapshot(vec![provider("alpha", vec![unknown])]);
        let now_seconds = now.timestamp() as f64;
        fixture_snapshot.history = vec![
            sample(now_seconds - 7_200.0, "alpha", "primary", 0.0),
            sample(now_seconds - 3_600.0, "alpha", "primary", 0.0),
            sample(now_seconds - 1_800.0, "alpha", "primary", 0.0),
        ];
        let model = project_dashboard(
            &state(BackendStatus::Ready, Some(fixture_snapshot)),
            &Map::new(),
            &CurrencyCatalog::default(),
            now,
        );
        let card = &model.providers[0];
        assert_eq!(card.windows[0].usage, "Unavailable");
        assert!(card.windows[0].trend.is_none());
        assert!(card.burndown.is_none());

        let mut known = window("primary", true, 0.0);
        known.resets_at = Some(now + Duration::hours(2));
        let model = project_dashboard(
            &state(
                BackendStatus::Ready,
                Some(snapshot(vec![provider("alpha", vec![known])])),
            ),
            &Map::new(),
            &CurrencyCatalog::default(),
            now,
        );
        assert_eq!(model.providers[0].windows[0].usage, "0%");
        assert!(model.providers[0].windows[0].trend.is_none());
        assert!(model.providers[0].burndown.is_none());
    }

    #[test]
    fn marker_preferences_and_tick_style_are_respected() {
        use chrono::{Duration, TimeZone};

        let now = Utc.with_ymd_and_hms(2026, 10, 31, 12, 0, 0).unwrap();
        let mut secondary = window("secondary", true, 55.0);
        secondary.resets_at = Some(now + Duration::days(5));
        let preferences = serde_json::from_value::<Map<String, Value>>(json!({
            "quotaWarningMarkersVisible": false,
            "workdayTickAppearance": "hidden",
            "weeklyProgressWorkDays": 5
        }))
        .unwrap();
        let model = project_dashboard(
            &state(
                BackendStatus::Ready,
                Some(snapshot(vec![provider("alpha", vec![secondary])])),
            ),
            &preferences,
            &CurrencyCatalog::default(),
            now,
        );
        let quota = &model.providers[0].windows[0];
        assert!(quota.warning_markers.is_empty());
        assert_eq!(quota.workday_tick, None);
        assert_eq!(quota.tick_appearance, "hidden");
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
