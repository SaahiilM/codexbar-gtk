//! Asynchronous refresh orchestration for provider, spend, session and history
//! state. The public handle is frontend-neutral and publishes immutable DTOs.

use std::{
    collections::{HashMap, HashSet},
    future::Future,
    pin::Pin,
    sync::Arc,
    time::Duration,
};

use chrono::{DateTime, Utc};
use codexbar_core::{
    domain::{self, AgentSession, ProviderUsage, SpendSummary},
    history::{HistoryStore, Sample},
    notifications::{NotificationPolicy, NotificationPreferences},
    ordering::{automatic_tray_selection, order_providers, AutomaticQuotaSelection},
    preferences::PreferencesStore,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::{
    sync::mpsc,
    time::{self, Instant},
};

use crate::{
    cli::{CliError, CliErrorKind, CliService, SharedCliService},
    event_channel, BackendError, BackendErrorKind, BackendEvent, BackendHandle, Cancellation,
    EventPublisher,
};

type CommandFuture<'a, T> = Pin<Box<dyn Future<Output = Result<T, CliError>> + Send + 'a>>;

/// Injectable CLI boundary used by production and deterministic controller tests.
pub trait RefreshCli: Send + Sync + 'static {
    fn usage<'a>(
        &'a self,
        provider: Option<&'a str>,
        all_accounts: bool,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>>;

    fn cost<'a>(
        &'a self,
        provider: Option<&'a str>,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>>;

    fn sessions<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>>;

    fn version<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, String>;
}

impl RefreshCli for CliService {
    fn usage<'a>(
        &'a self,
        provider: Option<&'a str>,
        all_accounts: bool,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        Box::pin(self.usage(provider, None, all_accounts, timeout, cancellation))
    }

    fn cost<'a>(
        &'a self,
        provider: Option<&'a str>,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        Box::pin(self.cost(provider, None, timeout, cancellation))
    }

    fn sessions<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        Box::pin(self.sessions(timeout, cancellation))
    }

    fn version<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, String> {
        Box::pin(self.version(timeout, cancellation))
    }
}

impl RefreshCli for SharedCliService {
    fn usage<'a>(
        &'a self,
        provider: Option<&'a str>,
        all_accounts: bool,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        let service = self.snapshot();
        Box::pin(async move {
            service
                .usage(provider, None, all_accounts, timeout, cancellation)
                .await
        })
    }

    fn cost<'a>(
        &'a self,
        provider: Option<&'a str>,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        let service = self.snapshot();
        Box::pin(async move { service.cost(provider, None, timeout, cancellation).await })
    }

    fn sessions<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, Vec<Value>> {
        let service = self.snapshot();
        Box::pin(async move { service.sessions(timeout, cancellation).await })
    }

    fn version<'a>(
        &'a self,
        timeout: Duration,
        cancellation: Option<Cancellation>,
    ) -> CommandFuture<'a, String> {
        let service = self.snapshot();
        Box::pin(async move { service.version(timeout, cancellation).await })
    }
}

/// Stable error data safe to serialize across a language/UI boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ControllerErrorKind {
    Cancelled,
    Configuration,
    Network,
    Protocol,
    Process,
    Storage,
    Timeout,
    Internal,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ControllerError {
    pub kind: ControllerErrorKind,
    /// An owned copy of a static operation identifier; never free-form text.
    pub operation: String,
}

impl From<BackendError> for ControllerError {
    fn from(error: BackendError) -> Self {
        let kind = match error.kind {
            BackendErrorKind::Cancelled => ControllerErrorKind::Cancelled,
            BackendErrorKind::Configuration => ControllerErrorKind::Configuration,
            BackendErrorKind::Network => ControllerErrorKind::Network,
            BackendErrorKind::Protocol => ControllerErrorKind::Protocol,
            BackendErrorKind::Process => ControllerErrorKind::Process,
            BackendErrorKind::Storage => ControllerErrorKind::Storage,
            BackendErrorKind::Timeout => ControllerErrorKind::Timeout,
            BackendErrorKind::Internal => ControllerErrorKind::Internal,
        };
        Self {
            kind,
            operation: error.operation.to_owned(),
        }
    }
}

/// Immutable complete state published by the refresh service.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ControllerSnapshot {
    pub revision: u64,
    pub version: String,
    pub updated_at: Option<DateTime<Utc>>,
    pub last_error: Option<ControllerError>,
    pub cost_error: Option<ControllerError>,
    pub providers: Vec<ProviderUsage>,
    pub spend: Option<SpendSummary>,
    pub sessions: Vec<AgentSession>,
    pub history: Vec<Sample>,
    pub tray_selection: Option<AutomaticQuotaSelection>,
}

impl ControllerSnapshot {
    fn next_revision(&self) -> u64 {
        self.revision.wrapping_add(1)
    }
}

/// Explicit refresh command. Duplicate commands received during a refresh are
/// coalesced into one follow-up refresh.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControllerCommand {
    ForceRefresh,
}

/// Configuration for the refresh task. All services can be shared with the
/// application facade via `Arc`; the controller never owns GUI/Python objects.
pub struct RefreshControllerConfig {
    pub cli: Arc<dyn RefreshCli>,
    pub preferences: Arc<PreferencesStore>,
    pub history: Arc<HistoryStore>,
    pub usage_timeout: Duration,
    pub cost_timeout: Duration,
    pub sessions_timeout: Duration,
    pub version_timeout: Duration,
}

impl RefreshControllerConfig {
    pub fn new(
        cli: CliService,
        preferences: Arc<PreferencesStore>,
        history: Arc<HistoryStore>,
    ) -> Self {
        Self::with_shared_cli(
            Arc::new(SharedCliService::new(Arc::new(cli))),
            preferences,
            history,
        )
    }

    /// Build refresh orchestration from the same B07 CLI service Arc that the
    /// application facade uses for settings operations.
    pub fn with_shared_cli(
        cli: Arc<SharedCliService>,
        preferences: Arc<PreferencesStore>,
        history: Arc<HistoryStore>,
    ) -> Self {
        let refresh_cli: Arc<dyn RefreshCli> = cli;
        Self {
            cli: refresh_cli,
            preferences,
            history,
            usage_timeout: Duration::from_secs(180),
            cost_timeout: Duration::from_secs(180),
            sessions_timeout: Duration::from_secs(60),
            version_timeout: Duration::from_secs(20),
        }
    }
}

/// Public B10 controller handle accepted by the B14 composition facade.
pub struct RefreshControllerHandle {
    backend: BackendHandle<ControllerSnapshot>,
    force_refresh: mpsc::Sender<ControllerCommand>,
    notifications: Option<mpsc::Receiver<BackendEvent>>,
}

impl RefreshControllerHandle {
    pub fn start(config: RefreshControllerConfig) -> Self {
        let (force_refresh, commands) = mpsc::channel(256);
        let (event_publisher, notifications) = event_channel();
        let backend = BackendHandle::spawn(move |cancellation, state| async move {
            run_controller(config, commands, event_publisher, cancellation, state).await
        });
        Self {
            backend,
            force_refresh,
            notifications: Some(notifications),
        }
    }

    /// Async facade spelling for application composition code whose startup
    /// lifecycle is already async. Spawning itself has no blocking work.
    pub async fn start_async(config: RefreshControllerConfig) -> Self {
        Self::start(config)
    }

    /// Latest-value immutable state receiver. Intermediate revisions may be
    /// coalesced; transition events are delivered on the separate bounded mpsc.
    pub fn state(&self) -> tokio::sync::watch::Receiver<crate::BackendState<ControllerSnapshot>> {
        self.backend.state()
    }

    /// Clone this sender to issue explicit refresh requests from a facade.
    pub fn force_refresh_sender(&self) -> mpsc::Sender<ControllerCommand> {
        self.force_refresh.clone()
    }

    pub async fn force_refresh(&self) -> Result<(), mpsc::error::SendError<ControllerCommand>> {
        self.force_refresh
            .send(ControllerCommand::ForceRefresh)
            .await
    }

    /// Transfer the single bounded notification stream to the facade.
    pub fn take_notification_receiver(&mut self) -> Option<mpsc::Receiver<BackendEvent>> {
        self.notifications.take()
    }

    /// Signal cancellation and join the controller task.
    pub async fn shutdown(self) -> Result<(), BackendError> {
        self.backend.shutdown().await
    }
}

#[derive(Default)]
struct RefreshState {
    snapshot: Option<ControllerSnapshot>,
    account_cache: HashMap<String, (Vec<String>, Option<String>)>,
    accounts_done: HashSet<String>,
    notification_policy: NotificationPolicy,
}

async fn run_controller(
    config: RefreshControllerConfig,
    mut commands: mpsc::Receiver<ControllerCommand>,
    events: EventPublisher,
    cancellation: Cancellation,
    publisher: crate::StatePublisher<ControllerSnapshot>,
) -> Result<(), BackendError> {
    let mut data = RefreshState::default();
    let mut commands_open = true;

    // The first usage scan is immediate, including when refresh is manual.
    let mut interval = refresh_interval(&config.preferences);
    run_refresh_cycle(
        &config,
        &mut commands,
        &mut commands_open,
        &events,
        &cancellation,
        &publisher,
        &mut data,
    )
    .await?;
    let mut last_refresh = Instant::now();
    let mut next_poll = interval.map(|duration| last_refresh + duration);
    let mut queued = false;
    loop {
        let check_interval = Duration::from_millis(500);
        let wait = next_poll
            .map(|deadline| {
                deadline
                    .saturating_duration_since(Instant::now())
                    .min(check_interval)
            })
            .unwrap_or(check_interval);
        tokio::select! {
            _ = cancellation.clone().cancelled() => return Ok(()),
            command = commands.recv(), if commands_open => {
                match command {
                    Some(ControllerCommand::ForceRefresh) => {
                        queued = true;
                        while let Ok(ControllerCommand::ForceRefresh) = commands.try_recv() {
                            queued = true;
                        }
                    }
                    None => commands_open = false,
                }
            }
            _ = time::sleep(wait) => {
                interval = refresh_interval(&config.preferences);
                next_poll = interval.map(|current| last_refresh + current);
                if next_poll.is_some_and(|deadline| Instant::now() >= deadline) {
                    queued = true;
                }
            }
        }

        if queued {
            queued = false;
            run_refresh_cycle(
                &config,
                &mut commands,
                &mut commands_open,
                &events,
                &cancellation,
                &publisher,
                &mut data,
            )
            .await?;
            last_refresh = Instant::now();
            interval = refresh_interval(&config.preferences);
            next_poll = interval.map(|duration| last_refresh + duration);
        }
    }
}

async fn run_refresh_cycle(
    config: &RefreshControllerConfig,
    commands: &mut mpsc::Receiver<ControllerCommand>,
    commands_open: &mut bool,
    events: &EventPublisher,
    cancellation: &Cancellation,
    publisher: &crate::StatePublisher<ControllerSnapshot>,
    data: &mut RefreshState,
) -> Result<(), BackendError> {
    loop {
        let mut future = Box::pin(refresh_once(config, events, cancellation, publisher, data));
        let mut should_follow = false;
        loop {
            tokio::select! {
                _ = cancellation.clone().cancelled() => return Ok(()),
                result = &mut future => {
                    result?;
                    break;
                }
                command = commands.recv(), if *commands_open => {
                    match command {
                        Some(ControllerCommand::ForceRefresh) => should_follow = true,
                        None => *commands_open = false,
                    }
                }
            }
        }
        if !should_follow {
            return Ok(());
        }
        // Repeated forces during a pass collapse to one following pass.
    }
}

async fn refresh_once(
    config: &RefreshControllerConfig,
    events: &EventPublisher,
    cancellation: &Cancellation,
    publisher: &crate::StatePublisher<ControllerSnapshot>,
    data: &mut RefreshState,
) -> Result<(), BackendError> {
    publisher.refreshing();
    let usage = match config
        .cli
        .usage(None, true, config.usage_timeout, Some(cancellation.clone()))
        .await
    {
        Ok(payloads) => payloads,
        Err(error) => {
            let backend_error = error.backend_error();
            if let Some(previous) = data.snapshot.as_mut() {
                previous.revision = previous.next_revision();
                previous.last_error = Some(ControllerError::from(backend_error));
                publisher.fail_with_snapshot(previous.clone(), backend_error);
            } else {
                publisher.fail(backend_error);
            }
            return Ok(());
        }
    };

    let providers: Vec<ProviderUsage> = usage
        .iter()
        .cloned()
        .map(sanitize_usage_payload)
        .filter_map(|payload| domain::provider_usage_from_value(&payload))
        .collect();
    let provider_order = string_array(config.preferences.get("providerOrder"));
    let hidden_providers = string_array(config.preferences.get("hiddenProviders"));
    let mut providers = order_providers(&providers, &provider_order, &hidden_providers);
    collect_accounts(
        config,
        cancellation,
        &mut providers,
        &mut data.account_cache,
        &mut data.accounts_done,
    )
    .await;

    let (spend, cost_error) = collect_spend(
        config,
        cancellation,
        data.snapshot
            .as_ref()
            .and_then(|snapshot| snapshot.spend.clone()),
    )
    .await;
    let sessions = match config
        .cli
        .sessions(config.sessions_timeout, Some(cancellation.clone()))
        .await
    {
        Ok(payloads) => {
            domain::agent_sessions_from_value(&Value::Array(payloads)).unwrap_or_else(|| {
                data.snapshot
                    .as_ref()
                    .map(|snapshot| snapshot.sessions.clone())
                    .unwrap_or_default()
            })
        }
        Err(_) => data
            .snapshot
            .as_ref()
            .map(|snapshot| snapshot.sessions.clone())
            .unwrap_or_default(),
    };

    let now = Utc::now();

    // Record one sample per provider window only after a successful usage scan.
    let timestamp = now.timestamp() as f64 + f64::from(now.timestamp_subsec_nanos()) / 1e9;
    let new_samples: Vec<Sample> = providers
        .iter()
        .flat_map(|provider| {
            provider.windows.iter().map(move |window| Sample {
                timestamp,
                provider: provider.provider_id.clone(),
                window: window.key.clone(),
                used_percent: window.used_percent,
            })
        })
        .collect();
    let history_store = config.history.clone();
    let history = tokio::task::spawn_blocking(move || {
        if !new_samples.is_empty() {
            history_store.append(&new_samples);
        }
        let samples = history_store.read_all();
        if samples.len() > 20_000 {
            history_store.prune_at(timestamp);
        }
        history_store.read_all()
    })
    .await
    .unwrap_or_default();

    let notification_preferences = notification_preferences(&config.preferences);
    for event in data
        .notification_policy
        .observe(&providers, &notification_preferences, now)
    {
        events
            .publish_notification(event)
            .await
            .map_err(|error| error.backend_error())?;
    }

    let version = config
        .cli
        .version(config.version_timeout, Some(cancellation.clone()))
        .await
        .unwrap_or_else(|_| "unknown".to_owned());
    let tray_selection = automatic_tray_selection(&providers, now);
    let last_error = cost_error
        .as_ref()
        .map(|error| ControllerError::from(error.backend_error()));
    let snapshot = ControllerSnapshot {
        revision: data
            .snapshot
            .as_ref()
            .map_or(1, ControllerSnapshot::next_revision),
        version,
        updated_at: Some(now),
        last_error,
        cost_error: cost_error.map(|error| ControllerError::from(error.backend_error())),
        providers,
        spend,
        sessions,
        history,
        tray_selection,
    };
    if let Some(error) = snapshot.last_error.as_ref() {
        let backend_error = controller_error_to_backend(error);
        publisher.publish_with_error(snapshot.clone(), backend_error);
    } else {
        publisher.publish(snapshot.clone());
    }
    data.snapshot = Some(snapshot);
    Ok(())
}

async fn collect_accounts(
    config: &RefreshControllerConfig,
    cancellation: &Cancellation,
    providers: &mut [ProviderUsage],
    account_cache: &mut HashMap<String, (Vec<String>, Option<String>)>,
    accounts_done: &mut HashSet<String>,
) {
    for provider in providers {
        let provider_id = provider.provider_id.clone();
        if !accounts_done.contains(&provider_id) {
            match config
                .cli
                .usage(
                    Some(&provider_id),
                    true,
                    config.usage_timeout,
                    Some(cancellation.clone()),
                )
                .await
            {
                Ok(payloads) => {
                    let mut labels = Vec::new();
                    for payload in payloads {
                        let identity = payload.get("usage").and_then(|usage| usage.get("identity"));
                        let label = identity
                            .and_then(|identity| identity.get("accountEmail"))
                            .or_else(|| payload.get("account"))
                            .or_else(|| {
                                identity.and_then(|identity| identity.get("accountOrganization"))
                            })
                            .and_then(Value::as_str);
                        if let Some(label) = label.filter(|label| !label.is_empty()) {
                            if !labels.iter().any(|known: &String| known == label) {
                                labels.push(label.to_owned());
                            }
                        }
                    }
                    let selected = labels.first().cloned();
                    account_cache.insert(provider_id.clone(), (labels, selected));
                    accounts_done.insert(provider_id.clone());
                }
                Err(_) => continue,
            }
        }
        if let Some((accounts, selected)) = account_cache.get(&provider_id) {
            provider.accounts = accounts.clone();
            provider.selected_account = selected.clone();
        }
    }
}

async fn collect_spend(
    config: &RefreshControllerConfig,
    cancellation: &Cancellation,
    previous: Option<SpendSummary>,
) -> (Option<SpendSummary>, Option<CliError>) {
    if config
        .preferences
        .get("costUsageEnabled")
        .and_then(|value| value.as_bool())
        == Some(false)
    {
        return (None, None);
    }
    let payloads = match config
        .cli
        .cost(
            Some("both"),
            config.cost_timeout,
            Some(cancellation.clone()),
        )
        .await
    {
        Ok(payloads) => payloads,
        Err(original) => {
            let mut payloads = Vec::new();
            let mut succeeded = false;
            for provider in ["codex", "claude"] {
                match config
                    .cli
                    .cost(
                        Some(provider),
                        config.cost_timeout,
                        Some(cancellation.clone()),
                    )
                    .await
                {
                    Ok(values) => {
                        payloads.extend(values);
                        succeeded = true;
                    }
                    Err(_) => payloads.push(json!({
                        "provider": provider,
                        "error": { "message": "provider cost scan failed" }
                    })),
                }
            }
            if !succeeded {
                return (previous, Some(original));
            }
            payloads
        }
    };
    let mut payloads = payloads;
    let mut had_scan_error = false;
    for payload in &mut payloads {
        if payload.get("error").is_some_and(json_truthy) {
            payload["error"] = json!({"message": "provider cost scan failed"});
            had_scan_error = true;
        }
    }
    let mut fresh = domain::spend_from_payloads(&Value::Array(payloads));
    if had_scan_error {
        fresh.error = Some("Partial provider cost data".to_owned());
        fresh.cost_partial = true;
    }
    if fresh.providers.is_empty() && fresh.error.is_some() {
        (
            previous,
            Some(CliError {
                kind: CliErrorKind::Io,
                operation: "cli_cost",
            }),
        )
    } else {
        let partial = fresh.error.is_some();
        (
            Some(fresh),
            partial.then_some(CliError {
                kind: CliErrorKind::Io,
                operation: "cli_cost",
            }),
        )
    }
}

fn refresh_interval(preferences: &PreferencesStore) -> Option<Duration> {
    let seconds = preferences.refresh_seconds();
    (seconds > 0).then(|| Duration::from_secs(seconds as u64))
}

fn string_array(value: Option<Value>) -> Vec<String> {
    value
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|value| value.as_str().map(str::to_owned))
        .collect()
}

fn number_array(value: Option<Value>, default: Vec<f64>) -> Vec<f64> {
    value
        .and_then(|value| value.as_array().cloned())
        .map(|values| {
            values
                .into_iter()
                .filter_map(|value| value.as_f64())
                .collect()
        })
        .filter(|values: &Vec<f64>| !values.is_empty())
        .unwrap_or(default)
}

fn preference_bool(preferences: &PreferencesStore, key: &str, default: bool) -> bool {
    preferences
        .get(key)
        .and_then(|value| value.as_bool())
        .unwrap_or(default)
}

fn notification_preferences(preferences: &PreferencesStore) -> NotificationPreferences {
    NotificationPreferences {
        quota_enabled: preference_bool(preferences, "quotaWarningNotificationsEnabled", true),
        session_thresholds_enabled: preference_bool(
            preferences,
            "quotaWarningSessionEnabled",
            true,
        ),
        weekly_thresholds_enabled: preference_bool(preferences, "quotaWarningWeeklyEnabled", true),
        session_thresholds: number_array(
            preferences.get("quotaWarningSessionThresholds"),
            vec![50.0, 20.0],
        ),
        weekly_thresholds: number_array(
            preferences.get("quotaWarningWeeklyThresholds"),
            vec![50.0, 20.0],
        ),
        session_exhaustion_enabled: preference_bool(
            preferences,
            "sessionQuotaNotificationsEnabled",
            true,
        ),
        predictive_pace_enabled: preference_bool(
            preferences,
            "predictivePaceNotificationsEnabled",
            true,
        ),
        credit_expiry_enabled: preference_bool(preferences, "limitResetNotificationsEnabled", true),
    }
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

fn sanitize_usage_payload(mut payload: Value) -> Value {
    if let Some(error) = payload.get_mut("error") {
        if json_truthy(error) {
            *error = json!({"message": "provider usage reported an error"});
        }
    }
    if let Some(error) = payload
        .get_mut("usage")
        .and_then(Value::as_object_mut)
        .and_then(|usage| usage.get_mut("error"))
    {
        if json_truthy(error) {
            *error = json!({"message": "provider usage reported an error"});
        }
    }
    payload
}

fn controller_error_to_backend(error: &ControllerError) -> BackendError {
    let kind = match error.kind {
        ControllerErrorKind::Cancelled => BackendErrorKind::Cancelled,
        ControllerErrorKind::Configuration => BackendErrorKind::Configuration,
        ControllerErrorKind::Network => BackendErrorKind::Network,
        ControllerErrorKind::Protocol => BackendErrorKind::Protocol,
        ControllerErrorKind::Process => BackendErrorKind::Process,
        ControllerErrorKind::Storage => BackendErrorKind::Storage,
        ControllerErrorKind::Timeout => BackendErrorKind::Timeout,
        ControllerErrorKind::Internal => BackendErrorKind::Internal,
    };
    let operation = match error.operation.as_str() {
        "cli_usage" => "cli_usage",
        "cli_cost" => "cli_cost",
        "cli_sessions" => "cli_sessions",
        "cli_version" => "cli_version",
        "notification_event_publish" => "notification_event_publish",
        _ => "refresh_controller",
    };
    BackendError::new(kind, operation)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        collections::VecDeque,
        path::PathBuf,
        sync::{
            atomic::{AtomicUsize, Ordering},
            Mutex,
        },
    };
    use tokio::time::timeout;

    struct FakeCli {
        usage: Mutex<VecDeque<Result<Vec<Value>, CliError>>>,
        cost: Mutex<VecDeque<Result<Vec<Value>, CliError>>>,
        sessions: Mutex<VecDeque<Result<Vec<Value>, CliError>>>,
        version: Mutex<VecDeque<Result<String, CliError>>>,
        usage_calls: AtomicUsize,
        usage_delay: Duration,
    }

    impl FakeCli {
        fn new() -> Self {
            Self {
                usage: Mutex::new(VecDeque::from([Ok(vec![provider_payload(100.0)])])),
                cost: Mutex::new(VecDeque::from([Ok(vec![cost_payload(4.25)])])),
                sessions: Mutex::new(VecDeque::from([Ok(vec![session_payload()])])),
                version: Mutex::new(VecDeque::from([Ok("fixture-cli 1.2".into())])),
                usage_calls: AtomicUsize::new(0),
                usage_delay: Duration::ZERO,
            }
        }

        fn result<T: Clone>(
            queue: &Mutex<VecDeque<Result<T, CliError>>>,
            fallback: T,
        ) -> Result<T, CliError> {
            queue.lock().unwrap().pop_front().unwrap_or(Ok(fallback))
        }
    }

    impl RefreshCli for FakeCli {
        fn usage<'a>(
            &'a self,
            _provider: Option<&'a str>,
            _all_accounts: bool,
            _timeout: Duration,
            _cancellation: Option<Cancellation>,
        ) -> CommandFuture<'a, Vec<Value>> {
            self.usage_calls.fetch_add(1, Ordering::SeqCst);
            let result = Self::result(&self.usage, vec![provider_payload(100.0)]);
            let delay = self.usage_delay;
            Box::pin(async move {
                if !delay.is_zero() {
                    time::sleep(delay).await;
                }
                result
            })
        }

        fn cost<'a>(
            &'a self,
            _provider: Option<&'a str>,
            _timeout: Duration,
            _cancellation: Option<Cancellation>,
        ) -> CommandFuture<'a, Vec<Value>> {
            Box::pin(async move { Self::result(&self.cost, vec![cost_payload(4.25)]) })
        }

        fn sessions<'a>(
            &'a self,
            _timeout: Duration,
            _cancellation: Option<Cancellation>,
        ) -> CommandFuture<'a, Vec<Value>> {
            Box::pin(async move { Self::result(&self.sessions, vec![session_payload()]) })
        }

        fn version<'a>(
            &'a self,
            _timeout: Duration,
            _cancellation: Option<Cancellation>,
        ) -> CommandFuture<'a, String> {
            Box::pin(async move { Self::result(&self.version, "fixture-cli 1.2".to_owned()) })
        }
    }

    fn cli_error(operation: &'static str) -> CliError {
        CliError {
            kind: CliErrorKind::Io,
            operation,
        }
    }

    fn provider_payload(used: f64) -> Value {
        json!({
            "provider": "codex",
            "usage": {
                "primary": { "usedPercent": used, "windowMinutes": 300 },
                "identity": { "accountEmail": "fixture@example.invalid" }
            }
        })
    }

    fn cost_payload(cost: f64) -> Value {
        json!({
            "provider": "codex", "currencyCode": "USD",
            "totals": { "totalCost": cost, "totalTokens": 100, "priced": true }
        })
    }

    fn session_payload() -> Value {
        json!({
            "id": "fixture-session", "provider": "codex", "state": "running",
            "projectName": "synthetic", "cwd": "/tmp/synthetic", "pid": 10,
            "host": "fixture"
        })
    }

    struct TestPaths(PathBuf);
    impl TestPaths {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("codexbar-b10-{label}-{}.jsonl", std::process::id()));
            let _ = std::fs::remove_file(&path);
            Self(path)
        }
    }
    impl Drop for TestPaths {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }

    fn test_config(fake: Arc<FakeCli>, label: &str) -> RefreshControllerConfig {
        let paths = TestPaths::new(label);
        // Keep the path alive through the HistoryStore; preferences can use a
        // distinct ephemeral file because manual mode is written in memory.
        let preferences = Arc::new(PreferencesStore::new(
            paths.0.with_extension("settings.json"),
        ));
        preferences
            .set("refreshFrequency", json!("manual"), false)
            .unwrap();
        RefreshControllerConfig {
            cli: fake,
            preferences,
            history: Arc::new(HistoryStore::new(paths.0.clone(), 30)),
            usage_timeout: Duration::from_secs(1),
            cost_timeout: Duration::from_secs(1),
            sessions_timeout: Duration::from_secs(1),
            version_timeout: Duration::from_secs(1),
        }
    }

    async fn wait_revision(
        state: &mut tokio::sync::watch::Receiver<crate::BackendState<ControllerSnapshot>>,
        revision: u64,
    ) {
        timeout(Duration::from_secs(2), async {
            loop {
                if state
                    .borrow()
                    .snapshot
                    .as_ref()
                    .is_some_and(|snapshot| snapshot.revision >= revision)
                {
                    return;
                }
                state.changed().await.unwrap();
            }
        })
        .await
        .expect("controller should publish requested revision");
    }

    #[tokio::test]
    async fn starts_immediately_publishes_tray_and_typed_events_and_records_history() {
        let fake = Arc::new(FakeCli::new());
        let mut handle =
            RefreshControllerHandle::start_async(test_config(fake.clone(), "initial")).await;
        let mut state = handle.state();
        wait_revision(&mut state, 1).await;
        let snapshot = state.borrow().snapshot.as_ref().unwrap().clone();
        assert_eq!(fake.usage_calls.load(Ordering::SeqCst), 2); // state scan + account scan
        assert_eq!(snapshot.version, "fixture-cli 1.2");
        assert_eq!(snapshot.providers.len(), 1);
        assert!(snapshot.providers[0].windows[0].usage_known);
        assert_eq!(
            snapshot.tray_selection.as_ref().unwrap().provider_id,
            "codex"
        );
        assert_eq!(snapshot.history.len(), 1);
        let mut receiver = handle.take_notification_receiver().unwrap();
        let first = receiver.recv().await.unwrap();
        let second = receiver.recv().await.unwrap();
        assert_eq!((first.sequence, second.sequence), (0, 1));
        assert!(matches!(
            first.kind,
            crate::BackendEventKind::Notification(_)
        ));
        assert!(matches!(
            second.kind,
            crate::BackendEventKind::Notification(_)
        ));
        handle.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn failed_cost_fallback_retains_prior_spend_and_session_without_losing_usage() {
        let fake = Arc::new(FakeCli::new());
        fake.usage.lock().unwrap().extend([
            Ok(vec![provider_payload(100.0)]), // first pass account listing
            Ok(vec![provider_payload(65.0)]),
        ]);
        fake.cost.lock().unwrap().extend([
            Err(cli_error("cli_cost")),
            Ok(vec![]),
            Err(cli_error("cli_cost")),
        ]);
        fake.sessions
            .lock()
            .unwrap()
            .push_back(Err(cli_error("cli_sessions")));
        fake.version
            .lock()
            .unwrap()
            .push_back(Ok("fixture-cli 1.3".into()));
        let handle = RefreshControllerHandle::start(test_config(fake, "retention"));
        let mut state = handle.state();
        wait_revision(&mut state, 1).await;
        let before = state.borrow().snapshot.as_ref().unwrap().clone();
        handle.force_refresh().await.unwrap();
        wait_revision(&mut state, 2).await;
        let after = state.borrow().snapshot.as_ref().unwrap().clone();
        assert_eq!(after.providers[0].windows[0].used_percent, 65.0);
        assert_eq!(after.spend, before.spend);
        assert_eq!(after.sessions, before.sessions);
        assert_eq!(after.cost_error.as_ref().unwrap().operation, "cli_cost");
        assert_eq!(after.history.len(), 2);
        handle.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn partial_cost_fallback_uses_fresh_source_and_keeps_stable_error_context() {
        let fake = Arc::new(FakeCli::new());
        fake.cost.lock().unwrap().extend([
            Err(cli_error("cli_cost")),
            Ok(vec![cost_payload(8.75)]),
            Err(cli_error("cli_cost")),
        ]);
        let handle = RefreshControllerHandle::start(test_config(fake, "partial-cost"));
        let mut state = handle.state();
        wait_revision(&mut state, 1).await;
        handle.force_refresh().await.unwrap();
        wait_revision(&mut state, 2).await;
        let current = state.borrow();
        let snapshot = current.snapshot.as_ref().unwrap();
        let spend = snapshot.spend.as_ref().unwrap();
        assert_eq!(spend.total_cost, 8.75);
        assert!(spend.cost_partial);
        assert_eq!(spend.error.as_deref(), Some("Partial provider cost data"));
        assert_eq!(snapshot.last_error.as_ref().unwrap().operation, "cli_cost");
        assert_eq!(current.status, crate::BackendStatus::Ready);
        assert!(current.last_error.is_some());
        drop(current);
        handle.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn usage_failure_advances_error_revision_but_retains_last_snapshot() {
        let fake = Arc::new(FakeCli::new());
        fake.usage.lock().unwrap().extend([
            Ok(vec![provider_payload(100.0)]), // account listing
            Err(cli_error("cli_usage")),
        ]);
        let handle = RefreshControllerHandle::start(test_config(fake, "usage-failure"));
        let mut state = handle.state();
        wait_revision(&mut state, 1).await;
        let before = state.borrow().snapshot.as_ref().unwrap().clone();
        handle.force_refresh().await.unwrap();
        timeout(Duration::from_secs(2), async {
            loop {
                let current = state.borrow();
                if current.status == crate::BackendStatus::Failed {
                    break;
                }
                drop(current);
                state.changed().await.unwrap();
            }
        })
        .await
        .expect("usage failure should be published");
        let current = state.borrow();
        let after = current.snapshot.as_ref().unwrap();
        assert_eq!(after.revision, 2);
        assert_eq!(after.providers, before.providers);
        assert_eq!(after.spend, before.spend);
        assert_eq!(after.sessions, before.sessions);
        assert_eq!(after.history, before.history);
        assert_eq!(after.last_error.as_ref().unwrap().operation, "cli_usage");
        assert_eq!(current.last_error.unwrap().operation, "cli_usage");
        drop(current);
        handle.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn force_requests_during_one_refresh_create_exactly_one_follow_up() {
        let fake = Arc::new(FakeCli::new());
        // Account collection contributes one usage command after the initial
        // state scan, so hold that first refresh open for the force burst.
        let mut fake = Arc::try_unwrap(fake).ok().unwrap();
        fake.usage_delay = Duration::from_millis(80);
        let fake = Arc::new(fake);
        let handle = RefreshControllerHandle::start(test_config(fake.clone(), "coalesce"));
        while fake.usage_calls.load(Ordering::SeqCst) == 0 {
            time::sleep(Duration::from_millis(2)).await;
        }
        let sender = handle.force_refresh_sender();
        for _ in 0..6 {
            sender.send(ControllerCommand::ForceRefresh).await.unwrap();
        }
        let mut state = handle.state();
        wait_revision(&mut state, 2).await;
        time::sleep(Duration::from_millis(650)).await;
        assert_eq!(fake.usage_calls.load(Ordering::SeqCst), 3); // initial state + account + one follow-up
        assert_eq!(state.borrow().snapshot.as_ref().unwrap().revision, 2);
        handle.shutdown().await.unwrap();
    }
}
