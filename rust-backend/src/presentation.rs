//! Owned presentation projections for the transitional and native UIs.
//!
//! This module owns spend-view policy without GTK/Python dependencies. The
//! central facade can call these projections with its shared currency service
//! and immutable controller snapshot; the frontend only renders the DTOs.

use std::collections::BTreeMap;

use codexbar_core::{
    activity::{daily_series, DailyCostEntry},
    currency::CurrencyCatalog,
    domain::{ProviderUsage, RateWindow, SpendProvider},
    formatting::compact_window_label,
    ordering::AutomaticQuotaSelection,
};
use serde::Serialize;
use serde_json::Value;

use crate::{
    controller::{ControllerError, ControllerSnapshot},
    currency::CurrencyService,
    BackendState, BackendStatus,
};

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendAmount {
    /// Source-unit amount. `None` is unknown; it is never encoded as zero.
    pub source_amount: Option<f64>,
    /// Converted display amount, or `None` when the source amount is unknown.
    pub display_amount: Option<f64>,
    pub known: bool,
    pub partial: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendCount {
    /// `None` is unknown; `Some(0)` is a known zero count.
    pub value: Option<i64>,
    pub known: bool,
    pub partial: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendViewRequest {
    pub selected_range: String,
    pub preferred_currency: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendDailyPoint {
    pub date: String,
    /// `None` means unknown/unpriced. `Some(0.0)` is a known zero.
    pub source_amount: Option<f64>,
    pub display_amount: Option<f64>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendCoverage {
    pub priced: i64,
    pub unpriced: i64,
    pub has_counts: bool,
    pub provenance: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendEntryRow {
    pub name: String,
    pub source_cost: Option<f64>,
    pub display_cost: Option<f64>,
    pub cost_known: bool,
    pub cost_partial: bool,
    pub tokens: SpendCount,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendProviderRow {
    pub provider: String,
    pub source_cost: Option<f64>,
    pub display_cost: Option<f64>,
    pub cost_known: bool,
    pub cost_partial: bool,
    pub tokens: SpendCount,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SpendViewModel {
    pub backend_sequence: u64,
    pub backend_status: String,
    pub backend_error: Option<ControllerError>,
    /// False means the controller has not published spend data yet.
    pub spend_present: bool,
    /// Matches the current UI's no-activity state, independently from errors.
    pub empty: bool,
    pub selected_range: String,
    pub source_currency: Option<String>,
    pub display_currency: Option<String>,
    pub total: SpendAmount,
    pub session: SpendAmount,
    pub tokens: SpendCount,
    pub session_tokens: SpendCount,
    pub last30: SpendAmount,
    pub last30_tokens: SpendCount,
    pub coverage: SpendCoverage,
    pub provenance: Option<String>,
    pub reporting_period: Option<String>,
    pub history_label: Option<String>,
    pub history_coverage_established: bool,
    pub daily_chart: Vec<SpendDailyPoint>,
    /// Full unfiltered daily data for the GTK heatmap.
    pub heatmap_daily: Vec<Value>,
    pub providers: Vec<SpendProviderRow>,
    pub projects: Vec<SpendEntryRow>,
    pub models: Vec<SpendEntryRow>,
    pub refresh_error: Option<ControllerError>,
    pub cost_error: Option<ControllerError>,
    /// Safe reason code; raw provider/CLI error strings are never copied here.
    pub notice: Option<&'static str>,
}

impl Default for SpendViewModel {
    fn default() -> Self {
        let unknown = SpendAmount {
            source_amount: None,
            display_amount: None,
            known: false,
            partial: false,
        };
        Self {
            spend_present: false,
            backend_sequence: 0,
            backend_status: "idle".to_owned(),
            backend_error: None,
            empty: false,
            selected_range: "30 days".to_owned(),
            source_currency: None,
            display_currency: None,
            total: unknown.clone(),
            session: unknown.clone(),
            tokens: SpendCount {
                value: None,
                known: false,
                partial: false,
            },
            session_tokens: SpendCount {
                value: None,
                known: false,
                partial: false,
            },
            last30: unknown,
            last30_tokens: SpendCount {
                value: None,
                known: false,
                partial: false,
            },
            coverage: SpendCoverage {
                priced: 0,
                unpriced: 0,
                has_counts: false,
                provenance: None,
            },
            provenance: None,
            reporting_period: None,
            history_label: None,
            history_coverage_established: false,
            daily_chart: Vec::new(),
            heatmap_daily: Vec::new(),
            providers: Vec::new(),
            projects: Vec::new(),
            models: Vec::new(),
            refresh_error: None,
            cost_error: None,
            notice: None,
        }
    }
}

/// Project a spend snapshot with the existing chart range and row behavior.
/// Errors stay typed and separate from retained spend data.
pub fn spend_view_model(
    state: &BackendState<ControllerSnapshot>,
    request: &SpendViewRequest,
    currencies: &CurrencyService,
) -> SpendViewModel {
    let range = canonical_range(&request.selected_range);
    let refresh_error = state.last_error.map(Into::into);
    let backend_error = refresh_error.clone();
    let snapshot = state.snapshot.as_deref();
    let cost_error = snapshot.and_then(|snapshot| snapshot.cost_error.as_ref());
    let Some(spend) = snapshot.and_then(|snapshot| snapshot.spend.as_ref()) else {
        let mut model = SpendViewModel::default();
        model.selected_range = range.to_owned();
        model.backend_sequence = state.sequence;
        model.backend_status = status_name(state.status).to_owned();
        model.backend_error = backend_error;
        model.refresh_error = refresh_error;
        model.cost_error = cost_error.cloned();
        model.notice = notice_code(None, model.refresh_error.as_ref(), cost_error);
        return model;
    };

    let source_currency = nonempty_upper(&spend.currency).unwrap_or_else(|| "USD".to_owned());
    let display_currency = display_currency(
        &currencies.catalog(),
        &request.preferred_currency,
        &source_currency,
    );
    let convert = |amount: Option<f64>| -> Option<f64> {
        let amount = amount?;
        if display_currency == source_currency {
            return Some(amount);
        }
        currencies
            .convert(amount, &source_currency, &display_currency)
            .filter(|value| value.is_finite())
    };

    let total_source = spend.cost_known.then_some(spend.total_cost);
    let session_source = spend.session_cost_known.then_some(spend.session_cost);
    let last30_source = spend.last30_cost_known.then_some(spend.last30_cost);
    let priced = *spend.coverage.get("priced").unwrap_or(&0);
    let unpriced = *spend.coverage.get("unpriced").unwrap_or(&0);
    let days = match range {
        "7 days" => Some(7),
        "90 days" => Some(90),
        "All" => None,
        _ => Some(30),
    };
    let daily_entries = spend
        .daily
        .iter()
        .filter_map(|entry| {
            Some(DailyCostEntry {
                date: entry.get("date")?.as_str()?.to_owned(),
                total_cost: entry
                    .get("totalCost")
                    .filter(|value| !value.is_null())
                    .and_then(json_number),
            })
        })
        .collect::<Vec<_>>();
    let daily_chart = daily_series(&daily_entries, days, spend.history_coverage_established)
        .into_iter()
        .map(|point| SpendDailyPoint {
            date: point.date.to_string(),
            source_amount: point.cost,
            display_amount: convert(point.cost),
        })
        .collect();
    let providers = spend
        .providers
        .iter()
        .map(|entry| provider_row(entry, &convert))
        .collect();
    let projects = spend
        .projects
        .iter()
        .take(12)
        .map(|entry| {
            let source_cost = entry
                .get("totalCost")
                .filter(|value| !value.is_null())
                .and_then(json_number);
            let token_value = entry
                .get("totalTokens")
                .and_then(py_float)
                .map(|value| value as i64);
            SpendEntryRow {
                name: value_name(
                    entry
                        .get("name")
                        .filter(|value| value_truthy(value))
                        .or_else(|| entry.get("path")),
                ),
                source_cost,
                display_cost: convert(source_cost),
                cost_known: source_cost.is_some(),
                cost_partial: false,
                tokens: SpendCount {
                    value: token_value,
                    known: token_value.is_some(),
                    partial: false,
                },
            }
        })
        .collect();
    let models = model_rows(&spend.models, &convert);
    let partial_total = spend.cost_partial || cost_error.is_some();
    let notice = notice_code(spend.error.as_deref(), refresh_error.as_ref(), cost_error);

    SpendViewModel {
        backend_sequence: state.sequence,
        backend_status: status_name(state.status).to_owned(),
        backend_error,
        spend_present: true,
        empty: spend.daily.is_empty() && spend.projects.is_empty(),
        selected_range: range.to_owned(),
        source_currency: Some(source_currency.clone()),
        display_currency: Some(display_currency.clone()),
        total: SpendAmount {
            source_amount: total_source,
            display_amount: convert(total_source),
            known: spend.cost_known,
            partial: partial_total,
        },
        session: SpendAmount {
            source_amount: session_source,
            display_amount: convert(session_source),
            known: spend.session_cost_known,
            partial: spend.session_cost_partial || cost_error.is_some(),
        },
        tokens: SpendCount {
            value: spend.total_tokens_known.then_some(spend.total_tokens),
            known: spend.total_tokens_known,
            partial: spend.total_tokens_partial,
        },
        session_tokens: SpendCount {
            value: spend.session_tokens_known.then_some(spend.session_tokens),
            known: spend.session_tokens_known,
            partial: spend.session_tokens_partial,
        },
        last30: SpendAmount {
            source_amount: last30_source,
            display_amount: convert(last30_source),
            known: spend.last30_cost_known,
            partial: spend.last30_cost_partial || cost_error.is_some(),
        },
        last30_tokens: SpendCount {
            value: spend.last30_tokens_known.then_some(spend.last30_tokens),
            known: spend.last30_tokens_known,
            partial: spend.last30_tokens_partial,
        },
        coverage: SpendCoverage {
            priced,
            unpriced,
            has_counts: priced != 0 || unpriced != 0,
            provenance: clean_text(&spend.provenance),
        },
        provenance: clean_text(&spend.provenance),
        reporting_period: clean_option(&spend.reporting_period),
        history_label: clean_option(&spend.history_label),
        history_coverage_established: spend.history_coverage_established,
        daily_chart,
        heatmap_daily: spend.daily.clone(),
        providers,
        projects,
        models,
        refresh_error,
        cost_error: cost_error.cloned(),
        notice,
    }
}

fn canonical_range(value: &str) -> &'static str {
    match value.trim() {
        "7 days" | "7d" => "7 days",
        "90 days" | "90d" => "90 days",
        "All" | "all" => "All",
        _ => "30 days",
    }
}

fn status_name(status: BackendStatus) -> &'static str {
    match status {
        BackendStatus::Idle => "idle",
        BackendStatus::Refreshing => "refreshing",
        BackendStatus::Ready => "ready",
        BackendStatus::Failed => "failed",
        BackendStatus::Stopped => "stopped",
    }
}

fn nonempty_upper(value: &str) -> Option<String> {
    let value = value.trim();
    (!value.is_empty()).then(|| value.to_uppercase())
}

fn display_currency(catalog: &CurrencyCatalog, preferred: &str, source: &str) -> String {
    let preferred = preferred.trim().to_uppercase();
    if preferred.is_empty() || preferred == "AUTO" || preferred == source {
        return source.to_owned();
    }
    if catalog.get(&preferred).is_none() || catalog.convert(1.0, source, &preferred).is_none() {
        return source.to_owned();
    }
    preferred
}

fn json_number(value: &Value) -> Option<f64> {
    py_float(value).filter(|value| value.is_finite())
}

fn py_float(value: &Value) -> Option<f64> {
    match value {
        Value::Number(value) => value.as_f64(),
        Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
        Value::String(value) => value.trim().parse().ok(),
        _ => None,
    }
}

fn value_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn value_name(value: Option<&Value>) -> String {
    match value.filter(|value| value_truthy(value)) {
        Some(Value::String(value)) => value.clone(),
        Some(value) => value.to_string(),
        None => "—".to_owned(),
    }
}

fn provider_row(
    entry: &SpendProvider,
    convert: &impl Fn(Option<f64>) -> Option<f64>,
) -> SpendProviderRow {
    let partial = entry
        .daily
        .iter()
        .any(|daily| daily.get("totalCost").is_none_or(Value::is_null));
    let source_cost = entry.cost_known.then_some(entry.cost);
    SpendProviderRow {
        provider: codexbar_core::providers::display_name(&entry.provider),
        source_cost,
        display_cost: convert(source_cost),
        cost_known: entry.cost_known,
        cost_partial: partial,
        tokens: SpendCount {
            value: entry.tokens_known.then_some(entry.tokens),
            known: entry.tokens_known,
            partial: entry.tokens_partial,
        },
    }
}

fn model_rows(
    entries: &[Value],
    convert: &impl Fn(Option<f64>) -> Option<f64>,
) -> Vec<SpendEntryRow> {
    #[derive(Default)]
    struct Aggregate {
        name: String,
        cost: f64,
        known: bool,
        partial: bool,
        tokens: f64,
        tokens_known: bool,
        tokens_partial: bool,
    }
    let mut groups = BTreeMap::<String, Aggregate>::new();
    let mut order = Vec::<String>::new();
    for entry in entries {
        let name = value_name(
            entry
                .get("modelName")
                .filter(|value| value_truthy(value))
                .or_else(|| entry.get("name")),
        );
        if !groups.contains_key(&name) {
            order.push(name.clone());
        }
        let aggregate = groups.entry(name.clone()).or_insert_with(|| Aggregate {
            name,
            ..Aggregate::default()
        });
        let raw_cost = entry
            .get("cost")
            .filter(|value| value_truthy(value))
            .or_else(|| entry.get("totalCost").filter(|value| value_truthy(value)));
        match raw_cost.and_then(json_number) {
            Some(cost) => {
                aggregate.cost += cost;
                aggregate.known = true;
            }
            None => aggregate.partial = true,
        }
        match entry.get("totalTokens").and_then(py_float) {
            Some(tokens) => {
                aggregate.tokens += tokens;
                aggregate.tokens_known = true;
            }
            None => aggregate.tokens_partial = true,
        }
    }
    let mut rows = order
        .into_iter()
        .filter_map(|name| groups.remove(&name))
        .collect::<Vec<_>>();
    // Stable sorting retains source model order when costs tie.
    rows.sort_by(|left, right| {
        right
            .cost
            .partial_cmp(&left.cost)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    rows.into_iter()
        .take(12)
        .map(|row| {
            let source_cost = row.known.then_some(row.cost);
            SpendEntryRow {
                name: row.name,
                source_cost,
                display_cost: convert(source_cost),
                cost_known: row.known,
                cost_partial: row.partial,
                tokens: SpendCount {
                    value: row.tokens_known.then_some(row.tokens as i64),
                    known: row.tokens_known,
                    partial: row.tokens_partial,
                },
            }
        })
        .collect()
}

fn clean_option(value: &Option<String>) -> Option<String> {
    value.as_ref().filter(|value| !value.is_empty()).cloned()
}

fn clean_text(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_owned())
}

fn notice_code(
    summary_error: Option<&str>,
    refresh_error: Option<&ControllerError>,
    cost_error: Option<&ControllerError>,
) -> Option<&'static str> {
    if refresh_error.is_some() {
        Some("refresh_failed")
    } else if cost_error.is_some() || summary_error.is_some() {
        Some("cost_sources_unavailable")
    } else {
        None
    }
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct TraySummaryRequest {
    pub unified_icon_source: String,
    pub menu_bar_icon_style: String,
    pub switcher_rows_option: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct TraySwitcherRow {
    pub provider_id: String,
    pub text: String,
    pub available: bool,
    pub used_percent: Option<f64>,
    pub window_label: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct TraySummary {
    pub backend_sequence: u64,
    pub backend_status: String,
    pub backend_error: Option<ControllerError>,
    pub available: bool,
    pub unified_icon_source: String,
    pub menu_bar_icon_style: String,
    pub switcher_rows_option: String,
    pub title: String,
    pub tooltip_rows: Vec<String>,
    pub overflow_count: usize,
    pub selected_provider_id: Option<String>,
    pub selected_window_key: Option<String>,
    pub used_percent: Option<f64>,
    pub meter_level: Option<u8>,
    pub accent_color: Option<String>,
    pub initial: Option<String>,
    pub switcher_rows: Vec<TraySwitcherRow>,
}

/// Build tray text/menu policy from the exact immutable B10 snapshot. Automatic
/// uses its stored selection and never re-runs B09 ranking or reindexes vectors.
pub fn tray_summary(
    state: &BackendState<ControllerSnapshot>,
    request: &TraySummaryRequest,
) -> TraySummary {
    let snapshot = state.snapshot.as_deref();
    let providers = snapshot
        .map(|snapshot| snapshot.providers.as_slice())
        .unwrap_or_default();
    let icon_source = match request.unified_icon_source.as_str() {
        "automatic" | "first" => request.unified_icon_source.as_str(),
        _ => "highest",
    };
    let style = if request.menu_bar_icon_style == "iconPercent" {
        "iconPercent"
    } else {
        "meter"
    };
    let rows_option = if request.switcher_rows_option == "all" {
        "all"
    } else {
        "progress"
    };
    let selected = match icon_source {
        "automatic" => snapshot
            .and_then(|snapshot| snapshot.tray_selection.as_ref())
            .and_then(|selection| resolve_stored_selection_from(providers, selection)),
        "first" => first_eligible_window(providers),
        _ => highest_eligible_window(providers),
    };
    let selected_provider = selected.map(|(provider, _window)| provider);
    let selected_window = selected.map(|(_provider, window)| window);
    let used = selected_window.map(|window| window.used_percent);
    let meter = used.map(|value| (value / 10.0).floor().clamp(0.0, 9.0) as u8);
    let title = selected_provider
        .map(|provider| {
            let provider_label = if icon_source == "automatic" {
                selected_window
                    .and_then(|window| unique_compact_label(provider, window))
                    .map(|label| format!("{} {label}", provider.display_name))
                    .unwrap_or_else(|| provider.display_name.clone())
            } else {
                provider.display_name.clone()
            };
            format!("CodexBar GTK · {provider_label}")
        })
        .unwrap_or_else(|| "CodexBar GTK".to_owned());
    let tooltip_rows = tooltip_rows(providers, selected_provider);
    let overflow_count = providers
        .iter()
        .filter(|provider| !provider.has_error())
        .count()
        .saturating_sub(4);
    let switcher_rows = providers
        .iter()
        .filter(|provider| !provider.has_error())
        .map(|provider| switcher_row(provider, rows_option))
        .collect();
    TraySummary {
        backend_sequence: state.sequence,
        backend_status: status_name(state.status).to_owned(),
        backend_error: state.last_error.map(Into::into),
        available: selected.is_some(),
        unified_icon_source: icon_source.to_owned(),
        menu_bar_icon_style: style.to_owned(),
        switcher_rows_option: rows_option.to_owned(),
        title,
        tooltip_rows,
        overflow_count,
        selected_provider_id: selected_provider.map(|provider| provider.provider_id.clone()),
        selected_window_key: selected_window.map(|window| window.key.clone()),
        used_percent: used,
        meter_level: meter,
        accent_color: selected_provider.map(|provider| provider.accent_color.clone()),
        initial: selected_provider.map(|provider| {
            provider
                .display_name
                .chars()
                .next()
                .unwrap_or('?')
                .to_string()
        }),
        switcher_rows,
    }
}

fn resolve_stored_selection_from<'a>(
    providers: &'a [ProviderUsage],
    selection: &AutomaticQuotaSelection,
) -> Option<(&'a ProviderUsage, &'a RateWindow)> {
    let provider = providers.get(selection.provider_index)?;
    if provider.provider_id != selection.provider_id || provider.has_error() {
        return None;
    }
    let window = provider.windows.get(selection.window_index)?;
    if window.key != selection.window_key || !eligible_window(window) {
        return None;
    }
    Some((provider, window))
}

fn first_eligible_window(providers: &[ProviderUsage]) -> Option<(&ProviderUsage, &RateWindow)> {
    providers
        .iter()
        .filter(|provider| !provider.has_error())
        .find_map(|provider| {
            provider
                .windows
                .iter()
                .find(|window| eligible_window(window))
                .map(|window| (provider, window))
        })
}

fn highest_eligible_window(providers: &[ProviderUsage]) -> Option<(&ProviderUsage, &RateWindow)> {
    let mut best: Option<(&ProviderUsage, &RateWindow)> = None;
    for provider in providers.iter().filter(|provider| !provider.has_error()) {
        for window in provider
            .windows
            .iter()
            .filter(|window| eligible_window(window))
        {
            if best.is_none_or(|(_best_provider, best_window)| {
                window.used_percent > best_window.used_percent
            }) {
                best = Some((provider, window));
            }
        }
    }
    best
}

fn eligible_window(window: &RateWindow) -> bool {
    known_window(window) && !window.is_placeholder
}

fn known_window(window: &RateWindow) -> bool {
    window.usage_known && window.used_percent.is_finite() && window.used_percent >= 0.0
}

fn unique_compact_label(provider: &ProviderUsage, window: &RateWindow) -> Option<String> {
    let count = provider
        .windows
        .iter()
        .filter(|item| item.title == window.title && !item.is_placeholder)
        .count();
    (count == 1)
        .then(|| compact_window_label(Some(&window.title), window.window_minutes))
        .flatten()
}

fn tooltip_rows(providers: &[ProviderUsage], selected: Option<&ProviderUsage>) -> Vec<String> {
    let mut rows = vec![selected
        .map(|provider| format!("Provider: {}", provider.display_name))
        .unwrap_or_else(|| "Provider data unavailable".to_owned())];
    let eligible = providers
        .iter()
        .filter(|provider| !provider.has_error())
        .collect::<Vec<_>>();
    for provider in eligible.iter().take(4) {
        let is_selected = selected.is_some_and(|selected| std::ptr::eq(*provider, selected));
        if provider.windows.is_empty() {
            rows.push(if is_selected {
                "Usage unavailable".to_owned()
            } else {
                format!("{}: unavailable", provider.display_name)
            });
            continue;
        }
        let values = provider
            .windows
            .iter()
            .map(|window| {
                if known_window(window) {
                    format!("{}: {:.0}%", window.title, window.used_percent)
                } else {
                    format!("{}: unavailable", window.title)
                }
            })
            .collect::<Vec<_>>()
            .join(" · ");
        rows.push(if is_selected {
            values
        } else {
            format!("{}: {values}", provider.display_name)
        });
    }
    let more = eligible.len().saturating_sub(4);
    if more > 0 {
        rows.push(format!("+ {more} more providers"));
    }
    rows
}

fn switcher_row(provider: &ProviderUsage, rows_option: &str) -> TraySwitcherRow {
    if rows_option == "all" {
        let text = if provider.windows.is_empty() {
            format!("{} — Unavailable", provider.display_name)
        } else {
            let values = provider
                .windows
                .iter()
                .map(|window| {
                    if known_window(window) {
                        format!("{} {:.0}%", window.title, window.used_percent)
                    } else {
                        format!("{} unavailable", window.title)
                    }
                })
                .collect::<Vec<_>>()
                .join(" · ");
            format!("{} — {values}", provider.display_name)
        };
        return TraySwitcherRow {
            provider_id: provider.provider_id.clone(),
            text,
            available: provider.windows.iter().any(known_window),
            used_percent: None,
            window_label: None,
        };
    }

    let mut best: Option<&RateWindow> = None;
    for window in provider
        .windows
        .iter()
        .filter(|window| known_window(window))
    {
        match best {
            None => best = Some(window),
            Some(current)
                if window.used_percent > current.used_percent
                    || (window.used_percent == current.used_percent
                        && current.is_placeholder
                        && !window.is_placeholder) =>
            {
                best = Some(window)
            }
            _ => {}
        }
    }
    let (available, used, lane_label) = match best {
        Some(window) => (
            true,
            Some(window.used_percent),
            unique_compact_label(provider, window),
        ),
        None => (false, None, None),
    };
    let summary = match (used, lane_label.as_deref()) {
        (Some(used), Some(label)) => format!("{label} {used:.0}%"),
        (Some(used), None) => format!("{used:.0}%"),
        (None, _) => "Unavailable".to_owned(),
    };
    let filled = used.map(|value| value / 10.0);
    let bar = filled.map(|value| {
        let count = value.round_ties_even().clamp(0.0, 10.0) as usize;
        format!("{}{}", "▇".repeat(count), "░".repeat(10 - count))
    });
    let summary = bar.map_or(summary.clone(), |bar| {
        if available {
            format!("{bar} {summary}")
        } else {
            summary.clone()
        }
    });
    TraySwitcherRow {
        provider_id: provider.provider_id.clone(),
        text: format!("{} — {summary}", provider.display_name),
        available,
        used_percent: used,
        window_label: lane_label,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::{ControllerError, ControllerErrorKind, ControllerSnapshot};
    use codexbar_core::domain::{AgentSession, Pace, ProviderUsage, RateWindow, SpendSummary};
    use serde_json::json;
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::SystemTime;

    fn spend() -> SpendSummary {
        SpendSummary {
            total_cost: 12.0,
            cost_known: true,
            cost_partial: false,
            currency: "USD".into(),
            total_tokens: 900,
            total_tokens_known: true,
            total_tokens_partial: false,
            coverage: BTreeMap::from([("priced".into(), 3), ("unpriced".into(), 1)])
                .into_iter()
                .collect(),
            provenance: "history_scan".into(),
            reporting_period: Some("all time".into()),
            history_label: Some("History".into()),
            history_coverage_established: false,
            daily: vec![
                json!({"date":"2026-10-01", "totalCost":2.0}),
                json!({"date":"2026-10-03", "totalCost":null}),
            ],
            projects: vec![json!({"name":"synthetic-project", "totalTokens":12})],
            models: vec![
                json!({"modelName":"m1", "cost":2.0, "totalTokens":100}),
                json!({"name":"m1", "cost":null, "totalTokens":50}),
                json!({"name":"m2", "cost":0.0, "totalCost":3.0, "totalTokens":200}),
            ],
            session_cost: 0.0,
            session_cost_known: true,
            session_cost_partial: false,
            session_tokens: 0,
            session_tokens_known: true,
            session_tokens_partial: false,
            last30_cost: 4.0,
            last30_cost_known: true,
            last30_cost_partial: true,
            last30_tokens: 400,
            last30_tokens_known: true,
            last30_tokens_partial: false,
            incomplete_requests: 1,
            error: None,
            providers: vec![SpendProvider {
                provider: "fixture".into(),
                cost: 12.0,
                tokens: 900,
                tokens_known: true,
                tokens_partial: false,
                session_tokens: 0,
                session_tokens_known: true,
                session_tokens_partial: false,
                daily: vec![json!({"date":"2026-10-03", "totalCost":null})],
                projects: Vec::new(),
                priced: true,
                provenance: "history_scan".into(),
                cost_known: true,
            }],
        }
    }

    fn error() -> ControllerError {
        ControllerError {
            kind: ControllerErrorKind::Network,
            operation: "cli_cost".into(),
        }
    }

    fn currencies() -> CurrencyService {
        CurrencyService::new("/tmp/codexbar-b13-no-currency-cache.json")
    }

    fn request(range: &str, currency: &str) -> SpendViewRequest {
        SpendViewRequest {
            selected_range: range.into(),
            preferred_currency: currency.into(),
        }
    }

    fn window(key: &str, known: bool, placeholder: bool, used: f64) -> RateWindow {
        RateWindow {
            key: key.into(),
            title: if key == "primary" {
                "Session".into()
            } else {
                key.into()
            },
            used_percent: used,
            resets_at: None,
            reset_description: None,
            window_minutes: Some(300),
            next_regen_percent: None,
            is_placeholder: placeholder,
            quota_limit: None,
            quota_unit: None,
            usage_known: known,
        }
    }

    fn provider(id: &str, failed: bool, windows: Vec<RateWindow>) -> ProviderUsage {
        ProviderUsage {
            provider_id: id.into(),
            display_name: id.to_uppercase(),
            source: None,
            version: None,
            updated_at: None,
            account_email: None,
            plan: None,
            login_method: None,
            windows,
            pace: HashMap::<String, Pace>::new(),
            credits_remaining: None,
            credits_unit: String::new(),
            credits_available: false,
            cost: None,
            status_level: None,
            status_description: None,
            error: failed.then(|| "synthetic failure".into()),
            details: Vec::new(),
            reset_credits_available: 0,
            reset_credits: Vec::new(),
            credit_events: Vec::new(),
            accounts: Vec::new(),
            selected_account: None,
            accent_color: "#123456".into(),
            raw: json!({}),
        }
    }

    fn snapshot(
        providers: Vec<ProviderUsage>,
        selection: Option<AutomaticQuotaSelection>,
    ) -> ControllerSnapshot {
        ControllerSnapshot {
            revision: 1,
            version: "fixture".into(),
            updated_at: None,
            last_error: None,
            cost_error: None,
            providers,
            spend: None,
            sessions: Vec::<AgentSession>::new(),
            history: Vec::new(),
            tray_selection: selection,
        }
    }

    fn backend_state(
        snapshot: Option<ControllerSnapshot>,
        status: BackendStatus,
        last_error: Option<crate::BackendError>,
    ) -> BackendState<ControllerSnapshot> {
        BackendState {
            sequence: 1,
            changed_at: SystemTime::now(),
            status,
            snapshot: snapshot.map(Arc::new),
            last_error,
        }
    }

    fn spend_state(spend: Option<SpendSummary>) -> BackendState<ControllerSnapshot> {
        let mut snapshot = snapshot(Vec::new(), None);
        snapshot.spend = spend;
        backend_state(Some(snapshot), BackendStatus::Ready, None)
    }

    fn tray_state(snapshot: ControllerSnapshot) -> BackendState<ControllerSnapshot> {
        backend_state(Some(snapshot), BackendStatus::Ready, None)
    }

    fn selection(
        provider_index: usize,
        provider_id: &str,
        window_index: usize,
        window_key: &str,
    ) -> AutomaticQuotaSelection {
        AutomaticQuotaSelection {
            provider_index,
            provider_id: provider_id.into(),
            window_index,
            window_key: window_key.into(),
        }
    }

    fn tray_request(source: &str, rows: &str) -> TraySummaryRequest {
        TraySummaryRequest {
            unified_icon_source: source.into(),
            menu_bar_icon_style: "meter".into(),
            switcher_rows_option: rows.into(),
        }
    }

    #[test]
    fn absent_and_empty_spend_are_distinct_and_errors_are_typed() {
        let state = backend_state(
            None,
            BackendStatus::Refreshing,
            Some(crate::BackendError::new(
                crate::BackendErrorKind::Network,
                "cli_cost",
            )),
        );
        let absent = spend_view_model(&state, &request("7 days", "EUR"), &currencies());
        assert!(!absent.spend_present);
        assert!(!absent.empty);
        assert_eq!(absent.backend_status, "refreshing");
        assert_eq!(absent.selected_range, "7 days");
        assert_eq!(absent.notice, Some("refresh_failed"));
        assert_eq!(absent.refresh_error, Some(error()));

        let mut empty = spend();
        empty.daily.clear();
        empty.projects.clear();
        let present = spend_view_model(
            &spend_state(Some(empty)),
            &request("30d", "auto"),
            &currencies(),
        );
        assert!(present.spend_present);
        assert!(present.empty);
    }

    #[test]
    fn known_zero_unknown_partial_and_coverage_are_preserved() {
        let mut value = spend();
        value.total_cost = 0.0;
        value.cost_known = true;
        value.cost_partial = true;
        value.session_cost_known = false;
        value.last30_cost_known = false;
        let mut state = spend_state(Some(value));
        Arc::make_mut(state.snapshot.as_mut().unwrap()).cost_error = Some(error());
        let view = spend_view_model(&state, &request("30 days", "auto"), &currencies());
        assert_eq!(view.total.source_amount, Some(0.0));
        assert!(view.total.known && view.total.partial);
        assert_eq!(view.session.source_amount, None);
        assert!(!view.session.known);
        assert_eq!(view.last30.source_amount, None);
        assert!(view.last30.partial);
        assert_eq!((view.coverage.priced, view.coverage.unpriced), (3, 1));
        assert_eq!(view.coverage.provenance.as_deref(), Some("history_scan"));
        assert_eq!(view.cost_error, Some(error()));
    }

    #[test]
    fn selected_chart_range_and_full_heatmap_keep_unknown_distinct_from_zero() {
        let value = spend();
        let view = spend_view_model(
            &spend_state(Some(value.clone())),
            &request("7 days", "auto"),
            &currencies(),
        );
        assert_eq!(view.selected_range, "7 days");
        assert_eq!(view.daily_chart.len(), 3);
        assert_eq!(view.daily_chart[1].source_amount, None);
        assert_eq!(view.daily_chart[2].source_amount, None);
        assert_eq!(view.heatmap_daily.len(), 2);
        assert!(!view.history_coverage_established);
        let all = spend_view_model(
            &spend_state(Some(value.clone())),
            &request("All", "auto"),
            &currencies(),
        );
        assert_eq!(all.selected_range, "All");
        assert_eq!(all.daily_chart.len(), 3);
        let mut covered = value.clone();
        covered.history_coverage_established = true;
        let covered_view = spend_view_model(
            &spend_state(Some(covered)),
            &request("90d", "auto"),
            &currencies(),
        );
        assert_eq!(covered_view.selected_range, "90 days");
        assert_eq!(covered_view.daily_chart[1].source_amount, Some(0.0));
    }

    #[test]
    fn currency_falls_back_to_source_and_missing_group_cost_stays_unknown() {
        let value = spend();
        let view = spend_view_model(
            &spend_state(Some(value.clone())),
            &request("invalid", "ZZZ"),
            &currencies(),
        );
        assert_eq!(view.selected_range, "30 days");
        assert_eq!(view.source_currency.as_deref(), Some("USD"));
        assert_eq!(view.display_currency.as_deref(), Some("USD"));
        assert_eq!(view.projects[0].source_cost, None);
        assert!(!view.projects[0].cost_known);
        let model_m1 = view.models.iter().find(|row| row.name == "m1").unwrap();
        assert_eq!(model_m1.source_cost, Some(2.0));
        assert!(model_m1.cost_known && model_m1.cost_partial);
        assert_eq!(model_m1.tokens.value, Some(150));
        assert_eq!(view.models[0].name, "m2");
        let converted = spend_view_model(
            &spend_state(Some(value)),
            &request("30 days", "EUR"),
            &currencies(),
        );
        assert_eq!(converted.display_currency.as_deref(), Some("EUR"));
        assert_eq!(converted.total.display_amount, Some(12.0 * 0.92));
    }

    #[test]
    fn automatic_selection_resolves_original_indices_and_validates_identity() {
        let providers = vec![
            provider("error", true, vec![window("primary", true, false, 99.0)]),
            provider(
                "codex",
                false,
                vec![
                    window("unknown", false, false, 0.0),
                    window("primary", true, false, 0.0),
                ],
            ),
        ];
        let state = tray_state(snapshot(
            providers,
            Some(selection(1, "codex", 1, "primary")),
        ));
        let result = tray_summary(&state, &tray_request("automatic", "progress"));
        assert!(result.available);
        assert_eq!(result.selected_provider_id.as_deref(), Some("codex"));
        assert_eq!(result.selected_window_key.as_deref(), Some("primary"));
        assert_eq!(result.used_percent, Some(0.0));
        assert_eq!(result.meter_level, Some(0));
        assert_eq!(result.title, "CodexBar GTK · CODEX 5h");

        let invalid = tray_state(snapshot(
            state.snapshot.as_deref().unwrap().providers.clone(),
            Some(selection(1, "wrong-id", 1, "primary")),
        ));
        let invalid_result = tray_summary(&invalid, &tray_request("automatic", "progress"));
        assert!(!invalid_result.available);
        assert_eq!(invalid_result.used_percent, None);
    }

    #[test]
    fn automatic_unknown_selection_is_unavailable_not_known_zero() {
        let snapshot = tray_state(snapshot(
            vec![provider(
                "codex",
                false,
                vec![window("unknown", false, false, 0.0)],
            )],
            Some(selection(0, "codex", 0, "unknown")),
        ));
        let result = tray_summary(&snapshot, &tray_request("automatic", "progress"));
        assert!(!result.available);
        assert_eq!(result.used_percent, None);
        assert!(result.switcher_rows[0].text.contains("Unavailable"));
        assert!(result.tooltip_rows.join(" ").contains("unavailable"));
    }

    #[test]
    fn first_and_highest_use_known_nonerror_nonplaceholder_candidates() {
        let providers = vec![
            provider("failed", true, vec![window("primary", true, false, 100.0)]),
            provider(
                "first",
                false,
                vec![
                    window("unknown", false, false, 99.0),
                    window("placeholder", true, true, 98.0),
                    window("known-zero", true, false, 0.0),
                ],
            ),
            provider("highest", false, vec![window("primary", true, false, 90.0)]),
            provider("tie", false, vec![window("primary", true, false, 90.0)]),
        ];
        let snapshot = tray_state(snapshot(providers, None));
        let first = tray_summary(&snapshot, &tray_request("first", "progress"));
        assert_eq!(first.selected_provider_id.as_deref(), Some("first"));
        assert_eq!(first.selected_window_key.as_deref(), Some("known-zero"));
        let highest = tray_summary(&snapshot, &tray_request("highest", "progress"));
        assert_eq!(highest.selected_provider_id.as_deref(), Some("highest"));
        assert_eq!(highest.used_percent, Some(90.0));
    }

    #[test]
    fn tooltip_and_all_windows_keep_unknown_labels_and_filter_errors() {
        let snapshot = tray_state(snapshot(
            vec![
                provider("failed", true, vec![window("primary", true, false, 50.0)]),
                provider(
                    "codex",
                    false,
                    vec![
                        window("unknown", false, false, 0.0),
                        window("primary", true, false, 0.0),
                    ],
                ),
            ],
            None,
        ));
        let mut request = tray_request("first", "all");
        request.menu_bar_icon_style = "iconPercent".into();
        let result = tray_summary(&snapshot, &request);
        assert_eq!(result.menu_bar_icon_style, "iconPercent");
        assert!(!result.tooltip_rows.join(" ").contains("FAILED"));
        assert!(result.switcher_rows[0].text.contains("unknown unavailable"));
        assert!(result.switcher_rows[0].text.contains("Session 0%"));
    }
}
