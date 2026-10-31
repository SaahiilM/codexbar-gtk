use chrono::{DateTime, NaiveDate, TimeZone, Utc};
use codexbar_backend::cli::{self, CliError, CliService, SharedCliService};
use codexbar_backend::controller::{
    ControllerCommand, ControllerSnapshot, RefreshControllerConfig, RefreshControllerHandle,
};
use codexbar_backend::login::{
    LoginCompletionKind, LoginError, LoginEvent, LoginPrompt, LoginSession as BackendLoginSession,
    LoginSnapshot, LoginStatus,
};
use codexbar_backend::updates::{self, UpdateCheckRequest, UpdateError, UpdateRelation, Version};
use codexbar_backend::{BackendError, BackendEventKind, BackendStatus};
use codexbar_core::{
    activity, charts, currency, domain, formatting, history, notifications, ordering, pace,
    preferences, providers,
};
use pyo3::exceptions::{PyOSError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyDict, PyFloat, PyInt, PyList};
use serde_json::Value;
use std::collections::HashMap;
use std::ffi::OsString;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Duration;
use std::time::UNIX_EPOCH;
use tokio::runtime::Runtime;
use tokio::sync::{mpsc, watch};

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
type ExtraRateWindowTuple = RateWindowTuple;
type CostInfoTuple = (
    f64,
    f64,
    String,
    Option<String>,
    Option<f64>,
    Option<f64>,
    Option<String>,
);
type DetailRowTuple = (String, String, Option<String>, Option<f64>, String);
type DetailChartTuple = (String, Option<String>, Option<String>, Vec<(String, f64)>);
type DetailSectionTuple = (
    Option<String>,
    Vec<DetailRowTuple>,
    Option<DetailChartTuple>,
);
type ProviderContextTuple = (
    Option<f64>,
    bool,
    Vec<CreditEventTuple>,
    i64,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
);
type CreditEventTuple = (String, String, String, f64);
type AgentSessionTuple = (
    String,
    String,
    String,
    String,
    String,
    i64,
    Option<String>,
    Option<String>,
    String,
);

#[pyclass(name = "HistoryStore")]
struct RustHistoryStore {
    inner: Arc<history::HistoryStore>,
}

#[pyclass(name = "PreferencesStore")]
struct RustPreferencesStore {
    inner: Arc<preferences::PreferencesStore>,
}

#[pyclass(name = "CliService")]
struct RustCliService {
    runtime: Runtime,
    inner: CliService,
}

#[pyclass(name = "LoginSession")]
struct RustLoginSession {
    runtime: Runtime,
    executable: PathBuf,
    timeout: Duration,
    session: Mutex<Option<BackendLoginSession>>,
    events: Mutex<Option<tokio::sync::mpsc::Receiver<LoginEvent>>>,
    state: Mutex<Option<tokio::sync::watch::Receiver<LoginSnapshot>>>,
}

#[pyclass(name = "RefreshController")]
struct RustRefreshController {
    runtime: Option<Runtime>,
    handle: Mutex<Option<RefreshControllerHandle>>,
    state: watch::Receiver<codexbar_backend::BackendState<ControllerSnapshot>>,
    cli: Arc<SharedCliService>,
    cli_reconfigure: codexbar_backend::settings::CliReconfigureActor,
    preferences: Arc<preferences::PreferencesStore>,
    currencies: codexbar_backend::currency::CurrencyService,
    force_refresh: mpsc::Sender<ControllerCommand>,
    package_dir: PathBuf,
    notifications: Mutex<mpsc::Receiver<codexbar_backend::BackendEvent>>,
    shutdown_complete: Arc<AtomicBool>,
}

#[pyclass(name = "NotificationPolicy")]
struct RustNotificationPolicy {
    inner: notifications::NotificationPolicy,
}

#[pymethods]
impl RustNotificationPolicy {
    #[new]
    fn new() -> Self {
        Self {
            inner: notifications::NotificationPolicy::default(),
        }
    }

    /// Apply policies to a provider/account/window snapshot at an injected epoch clock.
    fn observe_json(
        &mut self,
        snapshot_json: &str,
        preferences_json: &str,
        now_epoch_seconds: f64,
    ) -> PyResult<String> {
        let snapshot: Value = serde_json::from_str(snapshot_json)
            .map_err(|_| PyValueError::new_err("notification_snapshot_decode"))?;
        let preferences: Value = serde_json::from_str(preferences_json)
            .map_err(|_| PyValueError::new_err("notification_preferences_decode"))?;
        let Some(providers) = snapshot.as_array() else {
            return Err(PyValueError::new_err("notification_snapshot_shape"));
        };
        if !now_epoch_seconds.is_finite() {
            return Err(PyValueError::new_err("notification_clock_invalid"));
        }
        let providers = providers
            .iter()
            .filter_map(notification_provider_from_json)
            .collect::<Vec<_>>();
        let thresholds = |key: &str| {
            preferences
                .get(key)
                .and_then(Value::as_array)
                .map(|items| items.iter().filter_map(Value::as_f64).collect::<Vec<_>>())
                .unwrap_or_default()
        };
        let prefs = notifications::NotificationPreferences {
            quota_enabled: preferences
                .get("quotaWarningNotificationsEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            session_thresholds_enabled: preferences
                .get("quotaWarningSessionEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            weekly_thresholds_enabled: preferences
                .get("quotaWarningWeeklyEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            session_thresholds: thresholds("quotaWarningSessionThresholds"),
            weekly_thresholds: thresholds("quotaWarningWeeklyThresholds"),
            session_exhaustion_enabled: preferences
                .get("sessionQuotaNotificationsEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            predictive_pace_enabled: preferences
                .get("predictivePaceNotificationsEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            credit_expiry_enabled: preferences
                .get("limitResetNotificationsEnabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
        };
        let seconds = now_epoch_seconds.floor() as i64;
        let nanos = ((now_epoch_seconds - seconds as f64) * 1e9).round() as u32;
        let now = Utc
            .timestamp_opt(seconds, nanos)
            .single()
            .ok_or_else(|| PyValueError::new_err("notification_clock_out_of_range"))?;
        let values = self
            .inner
            .observe(&providers, &prefs, now)
            .into_iter()
            .map(notification_event_json)
            .collect::<Vec<_>>();
        serde_json::to_string(&values)
            .map_err(|_| PyValueError::new_err("notification_event_encode"))
    }
}

fn notification_provider_from_json(value: &Value) -> Option<domain::ProviderUsage> {
    let object = value.as_object()?;
    let provider_id = object.get("provider_id")?.as_str()?.to_owned();
    let display_name = object
        .get("display_name")
        .and_then(Value::as_str)
        .unwrap_or(&provider_id)
        .to_owned();
    let windows = object
        .get("windows")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|window| {
            let key = window.get("key")?.as_str()?.to_owned();
            let used_percent = window.get("used_percent").and_then(Value::as_f64);
            Some(domain::RateWindow {
                title: window
                    .get("title")
                    .and_then(Value::as_str)
                    .unwrap_or(&key)
                    .to_owned(),
                key,
                used_percent: used_percent.unwrap_or(0.0),
                resets_at: window
                    .get("resets_at")
                    .and_then(Value::as_str)
                    .and_then(|value| domain::parse_timestamp(Some(value))),
                reset_description: None,
                window_minutes: window.get("window_minutes").and_then(Value::as_i64),
                next_regen_percent: None,
                is_placeholder: window
                    .get("is_placeholder")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                quota_limit: None,
                quota_unit: None,
                usage_known: window
                    .get("usage_known")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                    && used_percent.is_some(),
            })
        })
        .collect::<Vec<_>>();
    let pace = object
        .get("pace")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .map(|(key, value)| {
            (
                key.clone(),
                domain::Pace {
                    stage: String::new(),
                    delta_percent: None,
                    expected_used_percent: None,
                    will_last_to_reset: value
                        .get("will_last_to_reset")
                        .and_then(Value::as_bool)
                        .unwrap_or(true),
                    eta_seconds: value.get("eta_seconds").and_then(Value::as_f64),
                    run_out_probability: value.get("run_out_probability").and_then(Value::as_f64),
                    summary: None,
                },
            )
        })
        .collect::<std::collections::HashMap<_, _>>();
    let reset_credits = object
        .get("reset_credits")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    Some(domain::ProviderUsage {
        provider_id,
        display_name,
        source: None,
        version: None,
        updated_at: None,
        account_email: object
            .get("account_email")
            .and_then(Value::as_str)
            .filter(|email| !email.is_empty())
            .map(str::to_owned),
        plan: None,
        login_method: None,
        windows,
        pace,
        credits_remaining: None,
        credits_unit: String::new(),
        credits_available: false,
        cost: None,
        status_level: None,
        status_description: None,
        error: None,
        details: Vec::new(),
        reset_credits_available: reset_credits.len() as i64,
        reset_credits,
        credit_events: Vec::new(),
        accounts: Vec::new(),
        selected_account: None,
        accent_color: String::new(),
        raw: value.clone(),
    })
}

fn notification_event_json(event: notifications::NotificationEvent) -> Value {
    match event {
        notifications::NotificationEvent::QuotaThreshold {
            provider_id,
            account_email,
            window_key,
            used_percent,
            threshold_percent,
            title,
            body,
        } => serde_json::json!({
            "kind":"quota_threshold", "provider_id":provider_id, "account_email":account_email, "window_key":window_key,
            "used_percent":used_percent, "threshold_percent":threshold_percent, "title":title, "body":body
        }),
        notifications::NotificationEvent::SessionExhausted {
            provider_id,
            account_email,
            window_key,
            title,
            body,
        } => serde_json::json!({
            "kind":"session_exhausted", "provider_id":provider_id, "account_email":account_email,
            "window_key":window_key, "title":title, "body":body
        }),
        notifications::NotificationEvent::PredictivePace {
            id,
            provider_id,
            account_email,
            window_key,
            title,
            body,
        } => serde_json::json!({
            "kind":"predictive_pace", "id":id, "provider_id":provider_id, "account_email":account_email,
            "window_key":window_key, "title":title, "body":body
        }),
        notifications::NotificationEvent::CreditExpiry {
            id,
            provider_id,
            title,
            body,
        } => serde_json::json!({
            "kind":"credit_expiry", "id":id, "provider_id":provider_id, "title":title, "body":body
        }),
    }
}

#[pyclass(name = "CurrencyConverter")]
struct RustCurrencyConverter {
    inner: codexbar_backend::currency::CurrencyService,
}

#[pymethods]
impl RustCurrencyConverter {
    #[new]
    fn new(cache_path: PathBuf) -> Self {
        Self {
            inner: codexbar_backend::currency::CurrencyService::new(cache_path),
        }
    }
    fn codes(&self) -> Vec<String> {
        currency::CurrencyCatalog::default().codes()
    }
    fn entries(&self) -> Vec<(String, String, f64)> {
        currency::CURRENCIES
            .iter()
            .map(|(c, s, r)| ((*c).into(), (*s).into(), *r))
            .collect()
    }
    fn label(&self, code: &str) -> String {
        currency::CurrencyCatalog::default().label(code)
    }
    fn requires_live_rates(&self, preferred: &str) -> bool {
        let code = preferred.trim().to_uppercase();
        !code.is_empty()
            && code != "AUTO"
            && code != "USD"
            && currency::CurrencyCatalog::default().get(&code).is_some()
    }
    fn rate(&self, code: &str) -> Option<f64> {
        self.inner.rate(code)
    }
    fn convert(&self, amount: f64, source: &str, target: &str) -> Option<f64> {
        self.inner.convert(amount, source, target)
    }
    fn status(&self) -> (f64, String, bool) {
        let status = self.inner.status();
        let source = match status.source {
            codexbar_backend::currency::RateSource::Offline => "offline",
            codexbar_backend::currency::RateSource::Cache => "cache",
            codexbar_backend::currency::RateSource::Live => "live",
        };
        (
            status.fetched_at,
            source.to_owned(),
            status.last_refresh_failed,
        )
    }
    fn ensure_rates(&self, preferred: String) {
        let service = self.inner.clone();
        std::thread::spawn(move || {
            if let Ok(runtime) = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                runtime.block_on(service.ensure_rates(&preferred));
            }
        });
    }
}

#[pymethods]
impl RustPreferencesStore {
    #[new]
    fn new(path: PathBuf) -> Self {
        Self {
            inner: Arc::new(preferences::PreferencesStore::new(path)),
        }
    }

    fn load(&self) {
        self.inner.load();
    }

    fn save(&self) -> PyResult<()> {
        self.inner
            .save()
            .map_err(|error| PyOSError::new_err(format!("preferences save failed: {error}")))
    }

    fn get_json(&self, key: &str) -> Option<String> {
        self.inner
            .get(key)
            .and_then(|value| serde_json::to_string(&value).ok())
    }

    fn set_json(&self, key: String, value_json: &str, persist: bool) -> PyResult<()> {
        let value = serde_json::from_str(value_json)
            .map_err(|error| PyValueError::new_err(format!("invalid preference value: {error}")))?;
        self.inner
            .set(key, value, persist)
            .map_err(|error| PyOSError::new_err(format!("preferences save failed: {error}")))
    }

    fn update_json(&self, values_json: &str) -> PyResult<()> {
        let values = serde_json::from_str::<Value>(values_json).map_err(|error| {
            PyValueError::new_err(format!("invalid preference updates: {error}"))
        })?;
        let Value::Object(values) = values else {
            return Err(PyValueError::new_err(
                "preference updates must be an object",
            ));
        };
        self.inner
            .update(values)
            .map_err(|error| PyOSError::new_err(format!("preferences save failed: {error}")))
    }

    fn reset(&self) -> PyResult<()> {
        self.inner
            .reset()
            .map_err(|error| PyOSError::new_err(format!("preferences reset failed: {error}")))
    }

    fn as_json(&self) -> String {
        serde_json::to_string(&self.inner.values()).unwrap_or_else(|_| "{}".to_owned())
    }

    fn refresh_seconds(&self) -> i64 {
        self.inner.refresh_seconds()
    }

    fn refresh_is_manual(&self) -> bool {
        self.inner.refresh_is_manual()
    }

    fn export_json(&self) -> String {
        serde_json::to_string(&self.inner.export_document()).unwrap_or_else(|_| "{}".to_owned())
    }

    fn import_json(&self, document_json: &str) -> PyResult<()> {
        let document = serde_json::from_str(document_json).map_err(|error| {
            PyValueError::new_err(format!("invalid preference document: {error}"))
        })?;
        self.inner
            .import_document(&document)
            .map_err(|error| PyOSError::new_err(format!("preferences import failed: {error}")))
    }
}

fn cli_error_to_python(error: CliError) -> PyErr {
    PyRuntimeError::new_err(format!("CLI {:?} ({})", error.kind, error.operation))
}

fn static_operation(operation: &str) -> &'static str {
    match operation {
        "cli_usage" => "cli_usage",
        "cli_cost" => "cli_cost",
        "cli_sessions" => "cli_sessions",
        "cli_dashboard" => "cli_dashboard",
        "cli_version" => "cli_version",
        _ => "cli_command",
    }
}

fn run_cli_future<T: Send>(
    py: Python<'_>,
    runtime: &Runtime,
    future: impl Future<Output = T> + Send,
) -> T {
    let handle = runtime.handle().clone();
    py.detach(move || handle.block_on(future))
}

fn login_error_to_python(error: LoginError) -> PyErr {
    PyRuntimeError::new_err(format!("login {:?} (claude_login)", error.kind))
}

fn login_operation_error_to_python(
    error: codexbar_backend::application::LoginOperationError,
) -> PyErr {
    PyRuntimeError::new_err(format!("{} ({})", error.kind.as_str(), error.operation))
}

fn update_error_to_python(error: UpdateError) -> PyErr {
    let category = match error {
        UpdateError::InvalidMarker => "invalid_marker",
        UpdateError::Oversized => "oversized",
        UpdateError::Network => "network",
        UpdateError::Timeout => "timeout",
    };
    PyRuntimeError::new_err(format!("{category} (update_check)"))
}

fn restart_error_to_python(error: codexbar_backend::application::RestartError) -> PyErr {
    PyRuntimeError::new_err(format!("{} ({})", error.category, error.operation))
}

fn icon_cache_error_to_python(error: codexbar_backend::icon_cache::IconCacheError) -> PyErr {
    PyRuntimeError::new_err(format!("{} ({})", error.category, error.operation))
}

fn settings_error_to_python(error: codexbar_backend::settings::SettingsError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

impl RustLoginSession {
    fn create(executable: PathBuf, timeout_seconds: u64) -> PyResult<Self> {
        let runtime =
            Runtime::new().map_err(|_| PyRuntimeError::new_err("process (claude_login)"))?;
        Ok(Self {
            runtime,
            executable,
            timeout: Duration::from_secs(timeout_seconds.max(1)),
            session: Mutex::new(None),
            events: Mutex::new(None),
            state: Mutex::new(None),
        })
    }
}

#[pymethods]
impl RustLoginSession {
    #[new]
    fn new(executable: PathBuf, timeout_seconds: u64) -> PyResult<Self> {
        Self::create(executable, timeout_seconds)
    }

    fn start(&self, py: Python<'_>) -> PyResult<bool> {
        if self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login session lock is poisoned"))?
            .is_some()
        {
            return Ok(true);
        }
        let mut session = run_cli_future(
            py,
            &self.runtime,
            BackendLoginSession::start_claude(self.executable.clone(), self.timeout),
        )
        .map_err(login_error_to_python)?;
        let events = session
            .take_events()
            .ok_or_else(|| PyRuntimeError::new_err("login event stream is unavailable"))?;
        let state = session.state();
        *self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login session lock is poisoned"))? =
            Some(session);
        *self
            .events
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login event lock is poisoned"))? = Some(events);
        *self
            .state
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login state lock is poisoned"))? = Some(state);
        Ok(true)
    }

    fn snapshot(&self) -> PyResult<(String, bool)> {
        let state = self
            .state
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login state lock is poisoned"))?;
        let Some(state) = state.as_ref() else {
            return Ok(("idle".to_owned(), false));
        };
        let snapshot = state.borrow();
        let status = match snapshot.status {
            LoginStatus::Starting => "starting",
            LoginStatus::WaitingForAuthorization => "waiting_for_authorization",
            LoginStatus::WaitingForCode => "waiting_for_code",
            LoginStatus::Finishing => "finishing",
            LoginStatus::Succeeded => "succeeded",
            LoginStatus::Failed => "failed",
            LoginStatus::TimedOut => "timed_out",
            LoginStatus::Cancelled => "cancelled",
        };
        Ok((status.to_owned(), snapshot.needs_code))
    }

    /// Drain transient events. These values may contain authorization data;
    /// callers must keep them in memory and never log or persist them.
    fn poll_events(&self) -> PyResult<Vec<(String, String)>> {
        let mut receiver = self
            .events
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login event lock is poisoned"))?;
        let Some(receiver) = receiver.as_mut() else {
            return Ok(Vec::new());
        };
        let mut events = Vec::new();
        loop {
            match receiver.try_recv() {
                Ok(LoginEvent::AuthorizationUrl(url)) => events.push(("url".into(), url)),
                Ok(LoginEvent::Prompt(LoginPrompt::OpenBrowser)) => {
                    events.push(("prompt".into(), "open_browser".into()))
                }
                Ok(LoginEvent::Prompt(LoginPrompt::PasteCode)) => {
                    events.push(("prompt".into(), "paste_code".into()))
                }
                Ok(LoginEvent::Output(output)) => events.push(("output".into(), output)),
                Err(tokio::sync::mpsc::error::TryRecvError::Empty)
                | Err(tokio::sync::mpsc::error::TryRecvError::Disconnected) => break,
            }
        }
        Ok(events)
    }

    fn submit(&self, text: String) -> PyResult<()> {
        let session = self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login session lock is poisoned"))?;
        let session = session
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("login session has not started"))?;
        self.runtime
            .block_on(session.submit(text))
            .map_err(login_error_to_python)
    }

    fn cancel(&self) -> PyResult<()> {
        let session = self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login session lock is poisoned"))?;
        if let Some(session) = session.as_ref() {
            self.runtime.block_on(session.cancel());
        }
        Ok(())
    }

    fn wait(&self, py: Python<'_>) -> PyResult<(String, Option<u32>)> {
        let session = self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("login session lock is poisoned"))?
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("login session has not started"))?;
        let result =
            run_cli_future(py, &self.runtime, session.wait()).map_err(login_error_to_python)?;
        let kind = match result.kind {
            LoginCompletionKind::Succeeded => "succeeded",
            LoginCompletionKind::Failed => "failed",
            LoginCompletionKind::TimedOut => "timed_out",
            LoginCompletionKind::Cancelled => "cancelled",
        };
        Ok((kind.to_owned(), result.exit_code))
    }
}

#[pymethods]
impl RustCliService {
    #[new]
    fn new(executable: PathBuf, timezone: Option<String>) -> PyResult<Self> {
        let runtime =
            Runtime::new().map_err(|_| PyRuntimeError::new_err("could not start CLI runtime"))?;
        Ok(Self {
            runtime,
            inner: CliService::new(executable, timezone.map(OsString::from)),
        })
    }

    fn executable(&self) -> PathBuf {
        self.inner.executable().to_path_buf()
    }

    fn run(
        &self,
        py: Python<'_>,
        args: Vec<String>,
        timeout_seconds: Option<u64>,
    ) -> PyResult<(i32, String, String)> {
        let args = args.into_iter().map(OsString::from).collect::<Vec<_>>();
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let result = run_cli_future(py, &self.runtime, self.inner.run(&args, timeout, None))
            .map_err(cli_error_to_python)?;
        Ok((result.returncode, result.stdout, result.stderr))
    }

    fn run_json(
        &self,
        py: Python<'_>,
        args: Vec<String>,
        timeout_seconds: Option<u64>,
        operation: &str,
    ) -> PyResult<String> {
        let args = args.into_iter().map(OsString::from).collect::<Vec<_>>();
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let value = run_cli_future(
            py,
            &self.runtime,
            self.inner
                .run_json(&args, timeout, None, static_operation(operation)),
        )
        .map_err(cli_error_to_python)?;
        serde_json::to_string(&value)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn claude_auth_status(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(30).max(1));
        let value = run_cli_future(
            py,
            &self.runtime,
            codexbar_backend::login::claude_auth_status(&self.inner, timeout, None),
        );
        serde_json::to_string(&value)
            .map_err(|_| PyRuntimeError::new_err("login status conversion failed"))
    }

    fn version(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(20).max(1));
        run_cli_future(py, &self.runtime, self.inner.version(timeout, None))
            .map_err(cli_error_to_python)
    }

    fn usage_json(
        &self,
        py: Python<'_>,
        provider: Option<&str>,
        account_index: Option<u32>,
        all_accounts: bool,
        timeout_seconds: Option<u64>,
    ) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let values = run_cli_future(
            py,
            &self.runtime,
            self.inner
                .usage(provider, account_index, all_accounts, timeout, None),
        )
        .map_err(cli_error_to_python)?;
        serde_json::to_string(&values)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn dashboard_json(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let value = run_cli_future(py, &self.runtime, self.inner.dashboard(timeout, None))
            .map_err(cli_error_to_python)?;
        serde_json::to_string(&value)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn cost_json(
        &self,
        py: Python<'_>,
        provider: Option<&str>,
        days: Option<u32>,
        timeout_seconds: Option<u64>,
    ) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let values = run_cli_future(
            py,
            &self.runtime,
            self.inner.cost(provider, days, timeout, None),
        )
        .map_err(cli_error_to_python)?;
        serde_json::to_string(&values)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn sessions_json(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(60).max(1));
        let values = run_cli_future(py, &self.runtime, self.inner.sessions(timeout, None))
            .map_err(cli_error_to_python)?;
        serde_json::to_string(&values)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn config_providers_json(
        &self,
        py: Python<'_>,
        timeout_seconds: Option<u64>,
    ) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(60).max(1));
        let values = run_cli_future(
            py,
            &self.runtime,
            self.inner.config_providers(timeout, None),
        )
        .map_err(cli_error_to_python)?;
        serde_json::to_string(&values)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn set_api_key(
        &self,
        py: Python<'_>,
        provider: &str,
        key: &str,
        timeout_seconds: Option<u64>,
    ) -> PyResult<(i32, String, String)> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let result = run_cli_future(
            py,
            &self.runtime,
            self.inner.set_api_key(provider, key, timeout, None),
        )
        .map_err(cli_error_to_python)?;
        Ok((result.returncode, result.stdout, result.stderr))
    }

    fn provider_action(
        &self,
        py: Python<'_>,
        action: &str,
        provider: &str,
        source: Option<&str>,
        timeout_seconds: Option<u64>,
    ) -> PyResult<(i32, String, String)> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(180).max(1));
        let result = run_cli_future(
            py,
            &self.runtime,
            self.inner
                .provider_action(action, provider, source, timeout, None),
        )
        .map_err(cli_error_to_python)?;
        Ok((result.returncode, result.stdout, result.stderr))
    }

    fn hooks_json(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(30).max(1));
        let value = run_cli_future(py, &self.runtime, self.inner.hooks(timeout, None))
            .map_err(cli_error_to_python)?;
        serde_json::to_string(&value)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }

    fn set_hooks_enabled(
        &self,
        py: Python<'_>,
        enabled: bool,
        timeout_seconds: Option<u64>,
    ) -> PyResult<(i32, String, String)> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(30).max(1));
        let result = run_cli_future(
            py,
            &self.runtime,
            self.inner.set_hooks_enabled(enabled, timeout, None),
        )
        .map_err(cli_error_to_python)?;
        Ok((result.returncode, result.stdout, result.stderr))
    }

    fn plugins_json(&self, py: Python<'_>, timeout_seconds: Option<u64>) -> PyResult<String> {
        let timeout = Duration::from_secs(timeout_seconds.unwrap_or(60).max(1));
        let values = run_cli_future(py, &self.runtime, self.inner.plugins(timeout, None))
            .map_err(cli_error_to_python)?;
        serde_json::to_string(&values)
            .map_err(|_| PyRuntimeError::new_err("CLI JSON conversion failed"))
    }
}

fn backend_status_name(status: BackendStatus) -> &'static str {
    match status {
        BackendStatus::Idle => "idle",
        BackendStatus::Refreshing => "refreshing",
        BackendStatus::Ready => "ready",
        BackendStatus::Failed => "failed",
        BackendStatus::Stopped => "stopped",
    }
}

fn backend_error_json(error: BackendError) -> Value {
    let kind = match error.kind {
        codexbar_backend::BackendErrorKind::Cancelled => "cancelled",
        codexbar_backend::BackendErrorKind::Configuration => "configuration",
        codexbar_backend::BackendErrorKind::Network => "network",
        codexbar_backend::BackendErrorKind::Protocol => "protocol",
        codexbar_backend::BackendErrorKind::Process => "process",
        codexbar_backend::BackendErrorKind::Storage => "storage",
        codexbar_backend::BackendErrorKind::Timeout => "timeout",
        codexbar_backend::BackendErrorKind::Internal => "internal",
    };
    serde_json::json!({"kind": kind, "operation": error.operation})
}

#[pymethods]
impl RustRefreshController {
    #[pyo3(signature = (executable, timezone, preferences, history, currencies, default_executable=None, package_dir=None))]
    #[new]
    fn new(
        executable: PathBuf,
        timezone: Option<String>,
        preferences: PyRef<'_, RustPreferencesStore>,
        history: PyRef<'_, RustHistoryStore>,
        currencies: PyRef<'_, RustCurrencyConverter>,
        default_executable: Option<PathBuf>,
        package_dir: Option<PathBuf>,
    ) -> PyResult<Self> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|_| PyRuntimeError::new_err("could not start refresh runtime"))?;
        let default_executable = default_executable.unwrap_or_else(|| executable.clone());
        let package_dir = package_dir.unwrap_or_else(|| {
            std::env::current_exe()
                .ok()
                .and_then(|path| path.parent().map(Path::to_path_buf))
                .unwrap_or_else(|| PathBuf::from("."))
        });
        let cli = Arc::new(SharedCliService::new(Arc::new(CliService::new(
            executable,
            timezone.map(OsString::from),
        ))));
        let config = RefreshControllerConfig::with_shared_cli(
            cli.clone(),
            preferences.inner.clone(),
            history.inner.clone(),
        );
        let mut handle = {
            let _entered = runtime.enter();
            RefreshControllerHandle::start(config)
        };
        let state = handle.state();
        let force_refresh = handle.force_refresh_sender();
        let cli_reconfigure = codexbar_backend::settings::CliReconfigureActor::start(
            runtime.handle(),
            cli.clone(),
            preferences.inner.clone(),
            default_executable,
            force_refresh.clone(),
        );
        let notifications = handle
            .take_notification_receiver()
            .expect("new controller owns its notification receiver");
        Ok(Self {
            runtime: Some(runtime),
            handle: Mutex::new(Some(handle)),
            state,
            cli,
            cli_reconfigure,
            preferences: preferences.inner.clone(),
            currencies: currencies.inner.clone(),
            force_refresh,
            package_dir,
            notifications: Mutex::new(notifications),
            shutdown_complete: Arc::new(AtomicBool::new(false)),
        })
    }

    /// Read the latest immutable state without waiting for backend work.
    fn state_sequence(&self) -> u64 {
        self.state.borrow().sequence
    }

    fn state_json(&self) -> PyResult<String> {
        let state = self.state.borrow();
        let changed_at = state
            .changed_at
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let snapshot = state
            .snapshot
            .as_ref()
            .map(|snapshot| serde_json::to_value(snapshot.as_ref()))
            .transpose()
            .map_err(|_| PyRuntimeError::new_err("controller_snapshot_encode"))?;
        serde_json::to_string(&serde_json::json!({
            "sequence": state.sequence,
            "changed_at": changed_at,
            "status": backend_status_name(state.status),
            "snapshot": snapshot,
            "last_error": state.last_error.map(backend_error_json),
        }))
        .map_err(|_| PyRuntimeError::new_err("controller_state_encode"))
    }

    /// Return the owned spend presentation DTO from the latest snapshot.
    /// Currency conversion reads the facade's shared in-memory CurrencyService;
    /// this projection never starts or waits for a rate refresh.
    fn spend_view_model_json(&self, py: Python<'_>) -> PyResult<String> {
        let state = self.state.borrow().clone();
        let preferences = self.preferences.clone();
        let currencies = self.currencies.clone();
        py.detach(move || {
            let selected_range = preferences
                .get("spendTimeRange")
                .and_then(|value| value.as_str().map(str::to_owned))
                .unwrap_or_else(|| "30 days".to_owned());
            let preferred_currency = preferences
                .get("preferredCurrencyCode")
                .and_then(|value| value.as_str().map(str::to_owned))
                .unwrap_or_else(|| "auto".to_owned());
            let request = codexbar_backend::presentation::SpendViewRequest {
                selected_range,
                preferred_currency,
            };
            let model =
                codexbar_backend::presentation::spend_view_model(&state, &request, &currencies);
            serde_json::to_string(&model).map_err(|_| "spend_view_model_encode")
        })
        .map_err(PyRuntimeError::new_err)
    }

    /// Return an owned tray projection for the same full snapshot vector used
    /// by the stored B09 selection. No GTK objects or ranking policy cross here.
    fn tray_summary_json(&self, py: Python<'_>) -> PyResult<String> {
        let state = self.state.borrow().clone();
        let preferences = self.preferences.clone();
        py.detach(move || {
            let preference = |key: &str, default: &str| {
                preferences
                    .get(key)
                    .and_then(|value| value.as_str().map(str::to_owned))
                    .unwrap_or_else(|| default.to_owned())
            };
            let request = codexbar_backend::presentation::TraySummaryRequest {
                unified_icon_source: preference("unifiedIconSource", "highest"),
                menu_bar_icon_style: preference("menuBarIconStyle", "meter"),
                switcher_rows_option: preference("switcherRowsOption", "progress"),
            };
            let summary = codexbar_backend::presentation::tray_summary(&state, &request);
            serde_json::to_string(&summary).map_err(|_| "tray_summary_encode")
        })
        .map_err(PyRuntimeError::new_err)
    }

    /// Create a separate B11 PTY login handle; lifecycle/events do not enter
    /// the B10 refresh snapshot or notification stream.
    fn start_claude_login(
        &self,
        py: Python<'_>,
        executable: PathBuf,
        timeout_seconds: u64,
    ) -> PyResult<Py<RustLoginSession>> {
        let session = RustLoginSession::create(executable, timeout_seconds)?;
        Py::new(py, session)
    }

    /// Run B12's bounded network/parser/comparison operation on the controller
    /// runtime and return its owned result through this PyO3 adapter.
    fn check_update(
        &self,
        py: Python<'_>,
        url: &str,
        current_version: &str,
        current_build: &str,
        timeout_seconds: f64,
    ) -> PyResult<Py<PyDict>> {
        if !timeout_seconds.is_finite() || timeout_seconds <= 0.0 {
            return Err(update_error_to_python(UpdateError::Timeout));
        }
        let current =
            Version::new(current_version, current_build).map_err(update_error_to_python)?;
        let timeout = Duration::try_from_secs_f64(timeout_seconds.min(300.0))
            .map_err(|_| update_error_to_python(UpdateError::Timeout))?;
        let request = UpdateCheckRequest::new(current, url.to_owned(), timeout);
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| update_error_to_python(UpdateError::Network))?;
        let check =
            run_cli_future(py, runtime, updates::check(request)).map_err(update_error_to_python)?;
        let relation = match check.relation {
            UpdateRelation::Available => "available",
            UpdateRelation::Current => "current",
            UpdateRelation::Ahead => "ahead",
        };
        let result = PyDict::new(py);
        result.set_item("current_version", check.current.marketing)?;
        result.set_item("current_build", check.current.build)?;
        result.set_item("latest_version", check.latest.marketing)?;
        result.set_item("latest_build", check.latest.build)?;
        result.set_item("relation", relation)?;
        Ok(result.unbind())
    }

    /// Launch `codex login` in the first supported terminal. Discovery,
    /// argv construction and process creation remain in the Rust service.
    fn launch_codex_login_terminal(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let package_dir = self.package_dir.clone();
        py.detach(move || {
            let codex = cli::discover_executable("codex", Some("CODEX_CLI"), &package_dir).ok();
            let terminal = ["konsole", "gnome-terminal", "xterm", "kitty", "alacritty"]
                .iter()
                .find_map(|candidate| cli::find_executable_on_path(candidate));
            codexbar_backend::application::launch_codex_login_terminal_with(
                codex,
                terminal,
                &mut codexbar_backend::application::SystemApplicationLauncher,
            )
            .map_err(login_operation_error_to_python)
        })
        .map(|result| {
            let dict = PyDict::new(py);
            dict.set_item("launched", result.launched)?;
            Ok(dict.unbind())
        })?
    }

    /// Request a systemd restart or relaunch the exact current executable and
    /// OS argv. The GTK caller invokes this from a worker and quits on GLib.
    fn restart_application(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let result = py
            .detach(codexbar_backend::application::restart_application)
            .map_err(restart_error_to_python)?;
        let dict = PyDict::new(py);
        dict.set_item("mode", result.mode.as_str())?;
        Ok(dict.unbind())
    }

    /// Best-effort B14 test seam: compare Rust's process context with argv
    /// sampled by a Python-hosted test without returning/logging argv values.
    #[pyo3(name = "_restart_context_matches")]
    fn restart_context_matches(&self, executable: PathBuf, args: Vec<String>) -> bool {
        let Ok(actual) = codexbar_backend::application::RestartInvocation::current() else {
            return false;
        };
        actual.executable == executable
            && actual.args == args.into_iter().map(OsString::from).collect::<Vec<_>>()
    }

    /// Refresh the user's hicolor icon cache after the GTK layer has written
    /// rendered SVGs. All outcomes are best-effort and carry no paths.
    fn refresh_icon_cache(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let result = py
            .detach(move || codexbar_backend::icon_cache::refresh_icon_cache(&home))
            .map_err(icon_cache_error_to_python)?;
        let dict = PyDict::new(py);
        dict.set_item("status", result.status.as_str())?;
        Ok(dict.unbind())
    }

    /// Load independent typed settings sections through the facade's shared
    /// CLI and preference services. This adapter only serializes the owned DTO.
    fn settings_snapshot_json(&self, py: Python<'_>) -> PyResult<String> {
        let cli = self.cli.snapshot();
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("settings_runtime_stopped"))?;
        let snapshot = run_cli_future(py, runtime, async move {
            codexbar_backend::settings::settings_snapshot(&cli, &home, Duration::from_secs(60))
                .await
        });
        serde_json::to_string(&snapshot)
            .map_err(|_| PyRuntimeError::new_err("settings_snapshot_encode"))
    }

    fn settings_provider_action(
        &self,
        py: Python<'_>,
        action: &str,
        provider_id: &str,
        source: Option<&str>,
    ) -> PyResult<()> {
        use codexbar_backend::settings::{ProviderAction, ProviderSource, SettingsError};
        let invalid =
            || settings_error_to_python(SettingsError::invalid_input("settings_provider_action"));
        let action = match (action, source) {
            ("enable", None) => ProviderAction::Enable,
            ("disable", None) => ProviderAction::Disable,
            ("set-source", Some("auto")) => ProviderAction::SetSource {
                source: ProviderSource::Auto,
            },
            ("set-source", Some("web")) => ProviderAction::SetSource {
                source: ProviderSource::Web,
            },
            ("set-source", Some("cli")) => ProviderAction::SetSource {
                source: ProviderSource::Cli,
            },
            ("set-source", Some("oauth")) => ProviderAction::SetSource {
                source: ProviderSource::Oauth,
            },
            ("set-source", Some("api")) => ProviderAction::SetSource {
                source: ProviderSource::Api,
            },
            _ => return Err(invalid()),
        };
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("settings_runtime_stopped"))?;
        let cli = self.cli.snapshot();
        run_cli_future(
            py,
            runtime,
            codexbar_backend::settings::provider_action(
                &cli,
                action,
                provider_id,
                Duration::from_secs(180),
            ),
        )
        .map_err(settings_error_to_python)
    }

    fn settings_set_api_key(
        &self,
        py: Python<'_>,
        provider_id: &str,
        secret: &str,
    ) -> PyResult<()> {
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("settings_runtime_stopped"))?;
        let cli = self.cli.snapshot();
        run_cli_future(
            py,
            runtime,
            codexbar_backend::settings::set_api_key(
                &cli,
                provider_id,
                secret,
                Duration::from_secs(180),
            ),
        )
        .map_err(settings_error_to_python)
    }

    fn settings_set_hooks_enabled(&self, py: Python<'_>, enabled: bool) -> PyResult<()> {
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("settings_runtime_stopped"))?;
        let cli = self.cli.snapshot();
        run_cli_future(
            py,
            runtime,
            codexbar_backend::settings::set_hooks_enabled(&cli, enabled, Duration::from_secs(30)),
        )
        .map_err(settings_error_to_python)
    }

    fn settings_reconfigure_cli(
        &self,
        py: Python<'_>,
        cli_path: Option<String>,
        timezone: Option<String>,
    ) -> PyResult<Py<PyDict>> {
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("settings_runtime_stopped"))?;
        let result = run_cli_future(
            py,
            runtime,
            self.cli_reconfigure.reconfigure(cli_path, timezone),
        )
        .map_err(settings_error_to_python)?;
        let dict = PyDict::new(py);
        dict.set_item("applied", result.applied)?;
        dict.set_item("refresh_queued", result.refresh_queued)?;
        Ok(dict.unbind())
    }

    fn preferences_export_to(&self, py: Python<'_>, path: PathBuf) -> PyResult<()> {
        let preferences = self.preferences.clone();
        py.detach(move || codexbar_backend::settings::preferences_export_to(&preferences, &path))
            .map_err(settings_error_to_python)
    }

    fn preferences_import_from(&self, py: Python<'_>, path: PathBuf) -> PyResult<()> {
        let preferences = self.preferences.clone();
        py.detach(move || codexbar_backend::settings::preferences_import_from(&preferences, &path))
            .map_err(settings_error_to_python)
    }

    fn preferences_reset(&self, py: Python<'_>) -> PyResult<()> {
        let preferences = self.preferences.clone();
        py.detach(move || codexbar_backend::settings::preferences_reset(&preferences))
            .map_err(settings_error_to_python)
    }

    fn launch_at_login_state(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let state = py
            .detach(move || codexbar_backend::settings::launch_at_login_state(&home))
            .map_err(settings_error_to_python)?;
        let dict = PyDict::new(py);
        dict.set_item("enabled", state.enabled)?;
        Ok(dict.unbind())
    }

    fn set_launch_at_login(
        &self,
        py: Python<'_>,
        enabled: bool,
        app_exec: &str,
    ) -> PyResult<Py<PyDict>> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let preferences = self.preferences.clone();
        let app_exec = app_exec.to_owned();
        let state = py
            .detach(move || {
                codexbar_backend::settings::set_launch_at_login(
                    &preferences,
                    &home,
                    enabled,
                    &app_exec,
                )
            })
            .map_err(settings_error_to_python)?;
        let dict = PyDict::new(py);
        dict.set_item("enabled", state.enabled)?;
        Ok(dict.unbind())
    }

    /// Queue one explicit refresh without blocking the GTK thread.
    fn force_refresh(&self) -> bool {
        self.force_refresh
            .try_send(ControllerCommand::ForceRefresh)
            .is_ok()
    }

    /// Drain typed notification transitions separately from coalescing state.
    fn drain_events_json(&self, max_events: Option<usize>) -> PyResult<String> {
        let limit = max_events.unwrap_or(256).min(256);
        let mut receiver = self
            .notifications
            .lock()
            .map_err(|_| PyRuntimeError::new_err("controller_event_lock"))?;
        let mut items = Vec::new();
        for _ in 0..limit {
            match receiver.try_recv() {
                Ok(event) => {
                    let emitted_at = event
                        .emitted_at
                        .duration_since(UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_secs_f64();
                    let kind = match event.kind {
                        BackendEventKind::Notification(event) => notification_event_json(event),
                    };
                    items.push(serde_json::json!({
                        "sequence": event.sequence,
                        "emitted_at": emitted_at,
                        "event": kind,
                    }));
                }
                Err(mpsc::error::TryRecvError::Empty | mpsc::error::TryRecvError::Disconnected) => {
                    break;
                }
            }
        }
        serde_json::to_string(&items)
            .map_err(|_| PyRuntimeError::new_err("controller_events_encode"))
    }

    /// Request cancellation and join asynchronously; poll `shutdown_complete`.
    fn request_shutdown(&self) -> PyResult<()> {
        let handle = self
            .handle
            .lock()
            .map_err(|_| PyRuntimeError::new_err("controller_handle_lock"))?
            .take();
        let Some(handle) = handle else {
            return Ok(());
        };
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("controller_runtime_stopped"))?;
        let complete = self.shutdown_complete.clone();
        runtime.spawn(async move {
            let _ = handle.shutdown().await;
            complete.store(true, Ordering::Release);
        });
        Ok(())
    }

    fn shutdown_complete(&self) -> bool {
        self.shutdown_complete.load(Ordering::Acquire)
    }
}

impl Drop for RustRefreshController {
    fn drop(&mut self) {
        if let Ok(handle) = self.handle.get_mut() {
            drop(handle.take());
        }
        if let Some(runtime) = self.runtime.take() {
            // Destruction can happen on GTK's main thread. Cancellation has
            // already been signalled by dropping the handle; never join here.
            runtime.shutdown_background();
        }
    }
}

#[pyfunction]
fn discover_cli_executable(
    name: &str,
    override_env: Option<&str>,
    package_dir: PathBuf,
) -> PyResult<PathBuf> {
    cli::discover_executable(name, override_env, &package_dir).map_err(cli_error_to_python)
}

#[pyfunction]
fn terminal_command_argv(terminal: &str, command: Vec<String>) -> Vec<String> {
    let command = command.into_iter().map(OsString::from).collect::<Vec<_>>();
    codexbar_backend::login::terminal_command_argv(terminal, &command)
        .into_iter()
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect()
}

#[pyfunction]
fn browser_command_argv(opener: &str, url: &str) -> Vec<String> {
    codexbar_backend::login::browser_command_argv(opener, std::ffi::OsStr::new(url))
        .into_iter()
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect()
}

#[pymethods]
impl RustHistoryStore {
    #[new]
    fn new(path: PathBuf, retention_days: i64) -> Self {
        Self {
            inner: Arc::new(history::HistoryStore::new(path, retention_days)),
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
fn extra_rate_window_from_json(payload: &str) -> Option<ExtraRateWindowTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let window = domain::extra_rate_window_from_value(&payload)?;
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
fn cost_from_json(payload: &str) -> Option<CostInfoTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let cost = domain::cost_from_value(&payload)?;
    Some((
        cost.used,
        cost.limit,
        cost.currency,
        cost.period,
        cost.balance,
        cost.personal_used,
        cost.resets_at
            .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
    ))
}

#[pyfunction]
fn detail_section_from_json(payload: &str) -> Option<DetailSectionTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let section = domain::detail_section_from_value(&payload)?;
    Some((
        section.title,
        section
            .rows
            .iter()
            .map(|row| {
                (
                    row.label.clone(),
                    row.value.clone(),
                    row.secondary_value.clone(),
                    row.used_percent,
                    row.severity.clone(),
                )
            })
            .collect(),
        section
            .chart
            .map(|chart| (chart.kind, chart.title, chart.unit, chart.points)),
    ))
}

#[pyfunction]
fn provider_context_from_json(payload: &str) -> Option<ProviderContextTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let context = domain::provider_context_from_value(&payload)?;
    Some((
        context.credits_remaining,
        context.credits_available,
        context
            .credit_events
            .iter()
            .map(|event| {
                (
                    event.id.clone(),
                    event.date.clone(),
                    event.service.clone(),
                    event.used,
                )
            })
            .collect(),
        context.reset_credits_available,
        context.status_level,
        context.status_description,
        context.error,
        context.plan,
    ))
}

#[pyfunction]
fn provider_usage_from_json(payload: &str) -> Option<String> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let provider = domain::provider_usage_from_value(&payload)?;
    serde_json::to_string(&provider).ok()
}

#[pyfunction]
fn agent_session_from_json(payload: &str) -> Option<AgentSessionTuple> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let session = domain::agent_session_from_value(&payload)?;
    Some((
        session.id,
        session.provider,
        session.state,
        session.project_name,
        session.cwd,
        session.pid,
        session
            .started_at
            .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
        session
            .last_activity_at
            .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
        session.host,
    ))
}

#[pyfunction]
fn agent_sessions_from_json(payload: &str) -> Option<Vec<AgentSessionTuple>> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let sessions = domain::agent_sessions_from_value(&payload)?;
    Some(
        sessions
            .iter()
            .map(|session| {
                (
                    session.id.clone(),
                    session.provider.clone(),
                    session.state.clone(),
                    session.project_name.clone(),
                    session.cwd.clone(),
                    session.pid,
                    session
                        .started_at
                        .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
                    session
                        .last_activity_at
                        .map(|time| time.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
                    session.host.clone(),
                )
            })
            .collect(),
    )
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
fn provider_order_indices(
    provider_ids: Vec<String>,
    provider_order: Vec<String>,
    hidden_providers: Vec<String>,
) -> Vec<usize> {
    ordering::visible_order(&provider_ids, &provider_order, &hidden_providers)
}

#[pyfunction]
fn automatic_quota_candidate(
    used_percent: Vec<f64>,
    placeholders: Vec<bool>,
    candidate_eligible: Vec<bool>,
    window_minutes: Vec<Option<i64>>,
    seconds_until_reset: Vec<Option<f64>>,
    expected_used_percent: Vec<Option<f64>>,
    eta_seconds: Vec<Option<f64>>,
) -> Option<usize> {
    let count = [
        used_percent.len(),
        placeholders.len(),
        candidate_eligible.len(),
        window_minutes.len(),
        seconds_until_reset.len(),
        expected_used_percent.len(),
        eta_seconds.len(),
    ]
    .into_iter()
    .min()
    .unwrap_or_default();
    let mut candidates = Vec::new();
    let mut source_indices = Vec::new();
    for index in 0..count {
        if !candidate_eligible[index] {
            continue;
        }
        candidates.push(ordering::QuotaCandidate {
            used_percent: used_percent[index],
            placeholder: placeholders[index],
            window_minutes: window_minutes[index],
            seconds_until_reset: seconds_until_reset[index],
            expected_used_percent: expected_used_percent[index],
            eta_seconds: eta_seconds[index],
        });
        source_indices.push(index);
    }
    ordering::automatic_selection(&candidates).map(|index| source_indices[index])
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
fn spend_from_json<'py>(payload: &str, py: Python<'py>) -> Option<Bound<'py, PyDict>> {
    let payload: Value = serde_json::from_str(payload).ok()?;
    let summary = domain::spend_from_payloads(&payload);
    let dict = PyDict::new(py);
    dict.set_item("total_cost", summary.total_cost).unwrap();
    dict.set_item("cost_known", summary.cost_known).unwrap();
    dict.set_item("cost_partial", summary.cost_partial).unwrap();
    dict.set_item("currency", summary.currency.as_str())
        .unwrap();
    dict.set_item("total_tokens", summary.total_tokens).unwrap();
    dict.set_item("total_tokens_known", summary.total_tokens_known)
        .unwrap();
    dict.set_item("total_tokens_partial", summary.total_tokens_partial)
        .unwrap();

    let coverage_dict = PyDict::new(py);
    for (key, value) in &summary.coverage {
        coverage_dict.set_item(key.as_str(), *value).unwrap();
    }
    dict.set_item("coverage", coverage_dict).unwrap();

    dict.set_item("provenance", summary.provenance.as_str())
        .unwrap();
    dict.set_item("reporting_period", summary.reporting_period.as_deref())
        .unwrap();
    dict.set_item("history_label", summary.history_label.as_deref())
        .unwrap();
    dict.set_item(
        "history_coverage_established",
        summary.history_coverage_established,
    )
    .unwrap();
    dict.set_item(
        "daily",
        serde_json::to_string(&summary.daily)
            .unwrap_or_default()
            .as_str(),
    )
    .unwrap();
    dict.set_item(
        "projects",
        serde_json::to_string(&summary.projects)
            .unwrap_or_default()
            .as_str(),
    )
    .unwrap();
    dict.set_item(
        "models",
        serde_json::to_string(&summary.models)
            .unwrap_or_default()
            .as_str(),
    )
    .unwrap();
    dict.set_item("session_cost", summary.session_cost).unwrap();
    dict.set_item("session_cost_known", summary.session_cost_known)
        .unwrap();
    dict.set_item("session_cost_partial", summary.session_cost_partial)
        .unwrap();
    dict.set_item("session_tokens", summary.session_tokens)
        .unwrap();
    dict.set_item("session_tokens_known", summary.session_tokens_known)
        .unwrap();
    dict.set_item("session_tokens_partial", summary.session_tokens_partial)
        .unwrap();
    dict.set_item("last30_cost", summary.last30_cost).unwrap();
    dict.set_item("last30_cost_known", summary.last30_cost_known)
        .unwrap();
    dict.set_item("last30_cost_partial", summary.last30_cost_partial)
        .unwrap();
    dict.set_item("last30_tokens", summary.last30_tokens)
        .unwrap();
    dict.set_item("last30_tokens_known", summary.last30_tokens_known)
        .unwrap();
    dict.set_item("last30_tokens_partial", summary.last30_tokens_partial)
        .unwrap();
    dict.set_item("incomplete_requests", summary.incomplete_requests)
        .unwrap();
    dict.set_item("error", summary.error.as_deref()).unwrap();

    let providers_list = PyList::new(
        py,
        summary.providers.iter().map(|provider| {
            let provider_dict = PyDict::new(py);
            provider_dict
                .set_item("provider", provider.provider.as_str())
                .unwrap();
            provider_dict.set_item("cost", provider.cost).unwrap();
            provider_dict.set_item("tokens", provider.tokens).unwrap();
            provider_dict
                .set_item("tokens_known", provider.tokens_known)
                .unwrap();
            provider_dict
                .set_item("tokens_partial", provider.tokens_partial)
                .unwrap();
            provider_dict
                .set_item("session_tokens", provider.session_tokens)
                .unwrap();
            provider_dict
                .set_item("session_tokens_known", provider.session_tokens_known)
                .unwrap();
            provider_dict
                .set_item("session_tokens_partial", provider.session_tokens_partial)
                .unwrap();
            provider_dict
                .set_item(
                    "daily",
                    serde_json::to_string(&provider.daily)
                        .unwrap_or_default()
                        .as_str(),
                )
                .unwrap();
            provider_dict
                .set_item(
                    "projects",
                    serde_json::to_string(&provider.projects)
                        .unwrap_or_default()
                        .as_str(),
                )
                .unwrap();
            provider_dict.set_item("priced", provider.priced).unwrap();
            provider_dict
                .set_item("provenance", provider.provenance.as_str())
                .unwrap();
            provider_dict
                .set_item("cost_known", provider.cost_known)
                .unwrap();
            provider_dict
        }),
    )
    .unwrap();
    dict.set_item("providers", providers_list).unwrap();

    Some(dict)
}

#[pyfunction]
fn preferences_defaults_json() -> String {
    serde_json::to_string(&preferences::default_values()).unwrap_or_else(|_| "{}".to_owned())
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
    module.add_class::<RustPreferencesStore>()?;
    module.add_class::<RustCurrencyConverter>()?;
    module.add_class::<RustNotificationPolicy>()?;
    module.add_class::<RustCliService>()?;
    module.add_class::<RustLoginSession>()?;
    module.add_class::<RustRefreshController>()?;
    module.add_function(wrap_pyfunction!(discover_cli_executable, module)?)?;
    module.add_function(wrap_pyfunction!(terminal_command_argv, module)?)?;
    module.add_function(wrap_pyfunction!(browser_command_argv, module)?)?;
    module.add_function(wrap_pyfunction!(sparkline_coordinates, module)?)?;
    module.add_function(wrap_pyfunction!(canonical_id, module)?)?;
    module.add_function(wrap_pyfunction!(display_name, module)?)?;
    module.add_function(wrap_pyfunction!(short_name, module)?)?;
    module.add_function(wrap_pyfunction!(accent_color, module)?)?;
    module.add_function(wrap_pyfunction!(all_provider_ids, module)?)?;
    module.add_function(wrap_pyfunction!(backend_name, module)?)?;
    module.add_function(wrap_pyfunction!(parse_timestamp, module)?)?;
    module.add_function(wrap_pyfunction!(rate_window_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(extra_rate_window_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(cost_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(detail_section_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(provider_context_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(agent_session_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(agent_sessions_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(pace_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(optional_float, module)?)?;
    module.add_function(wrap_pyfunction!(optional_int, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_has_error, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_max_used_percent, module)?)?;
    module.add_function(wrap_pyfunction!(provider_usage_subtitle, module)?)?;
    module.add_function(wrap_pyfunction!(provider_order_indices, module)?)?;
    module.add_function(wrap_pyfunction!(automatic_quota_candidate, module)?)?;
    module.add_function(wrap_pyfunction!(detail_chart_peak, module)?)?;
    module.add_function(wrap_pyfunction!(agent_session_is_running, module)?)?;
    module.add_function(wrap_pyfunction!(spend_from_json, module)?)?;
    module.add_function(wrap_pyfunction!(preferences_defaults_json, module)?)?;
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
