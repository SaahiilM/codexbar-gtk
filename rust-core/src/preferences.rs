//! Thread-safe JSON preferences with portable import/export and private atomic
//! persistence, matching the transitional GTK client's settings contract.

use serde_json::{json, Map, Value};
use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

#[derive(Debug)]
pub struct PreferencesStore {
    path: PathBuf,
    values: Mutex<Map<String, Value>>,
}

impl PreferencesStore {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        let store = Self {
            path: path.into(),
            values: Mutex::new(default_values()),
        };
        store.load();
        store
    }

    pub fn default_path() -> PathBuf {
        std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".config/codexbar-gtk/settings.json")
    }

    pub fn values(&self) -> Map<String, Value> {
        self.lock_values().clone()
    }

    pub fn get(&self, key: &str) -> Option<Value> {
        self.lock_values().get(key).cloned()
    }

    pub fn set(&self, key: impl Into<String>, value: Value, persist: bool) -> io::Result<()> {
        self.lock_values().insert(key.into(), value);
        if persist {
            self.save()?;
        }
        Ok(())
    }

    pub fn update(&self, updates: Map<String, Value>) -> io::Result<()> {
        self.lock_values().extend(updates);
        self.save()
    }

    pub fn reset(&self) -> io::Result<()> {
        *self.lock_values() = default_values();
        self.save()
    }

    /// Load only known keys. Missing, malformed, unreadable, or non-object
    /// documents leave the complete default set in place, as the Python store
    /// does today.
    pub fn load(&self) {
        let mut current = self.lock_values();
        let mut values = default_values();
        if let Ok(contents) = fs::read_to_string(&self.path) {
            if let Ok(Value::Object(stored)) = serde_json::from_str::<Value>(&contents) {
                let defaults = default_values();
                for (key, value) in stored {
                    if defaults.contains_key(&key) {
                        values.insert(key, value);
                    }
                }
            }
        }
        *current = values;
    }

    pub fn save(&self) -> io::Result<()> {
        let values = self.lock_values();
        save_atomic(&self.path, &values)
    }

    pub fn refresh_seconds(&self) -> i64 {
        match self
            .get("refreshFrequency")
            .as_ref()
            .and_then(Value::as_str)
        {
            Some("manual") => 0,
            Some("1m") => 60,
            Some("2m") => 120,
            Some("5m") => 300,
            Some("15m") => 900,
            Some("30m") => 1800,
            _ => 300,
        }
    }

    pub fn refresh_is_manual(&self) -> bool {
        self.get("refreshFrequency")
            .as_ref()
            .and_then(Value::as_str)
            == Some("manual")
    }

    pub fn export_document(&self) -> Value {
        json!({"version": 1, "preferences": Value::Object(self.values())})
    }

    pub fn import_document(&self, document: &Value) -> io::Result<()> {
        let Some(imported) = document
            .as_object()
            .and_then(|object| object.get("preferences"))
            .and_then(Value::as_object)
        else {
            return Ok(());
        };
        let defaults = default_values();
        let updates = imported
            .iter()
            .filter(|(key, _)| defaults.contains_key(*key))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        self.update(updates)
    }

    fn lock_values(&self) -> MutexGuard<'_, Map<String, Value>> {
        self.values
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

fn save_atomic(path: &Path, values: &Map<String, Value>) -> io::Result<()> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)?;
    }

    let mut temporary_name = OsString::from(path.as_os_str());
    temporary_name.push(".tmp");
    let temporary_path = PathBuf::from(temporary_name);
    let result = (|| {
        let mut options = OpenOptions::new();
        options.create(true).truncate(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary_path)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&temporary_path, fs::Permissions::from_mode(0o600))?;
        }
        serde_json::to_writer_pretty(&mut file, values)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        file.flush()?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary_path, path)?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temporary_path);
    }
    result
}

pub fn default_values() -> Map<String, Value> {
    let value = json!({
        "refreshFrequency": "adaptive",
        "refreshAllProvidersOnMenuOpen": true,
        "launchAtLogin": false,
        "preferredCurrencyCode": "auto",
        "costUsageBucketTimeZone": "",
        "cliPath": "",
        "usageBarsShowUsed": true,
        "menuBarIconStyle": "meter",
        "unifiedIconSource": "highest",
        "menuBarColorPace": true,
        "switcherRowsOption": "progress",
        "workdayTickAppearance": "subtle",
        "quotaBurndownEnabled": true,
        "resetTimesOption": "countdown",
        "paceVisible": true,
        "quotaWarningMarkersVisible": true,
        "quotaWarningSessionEnabled": true,
        "quotaWarningWeeklyEnabled": true,
        "quotaWarningThresholds": [50, 20],
        "quotaWarningSessionThresholds": [50, 20],
        "quotaWarningWeeklyThresholds": [50, 20],
        "weeklyProgressWorkDays": 5,
        "showOptionalCreditsAndExtraUsage": true,
        "mergeIcons": true,
        "menuBarColorByProvider": true,
        "hidePersonalInfo": false,
        "providerOrder": [],
        "hiddenProviders": [],
        "sessionQuotaNotificationsEnabled": true,
        "quotaWarningNotificationsEnabled": true,
        "limitResetNotificationsEnabled": true,
        "predictivePaceNotificationsEnabled": true,
        "statusChecksEnabled": true,
        "costUsageEnabled": true,
        "costSummaryDisplayStyle": "both",
        "costReportingPeriod": "month-to-date",
        "costComparisonPeriodsEnabled": true,
        "spendTimeRange": "30d",
        "showTray": true,
        "showPopupOnStart": false,
        "debugMenuEnabled": false,
    });
    value
        .as_object()
        .expect("preferences defaults are an object")
        .clone()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let id = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir()
                .join(format!("codexbar-preferences-{}-{id}", std::process::id()));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn loads_only_known_keys_over_defaults() {
        let temp = TempDir::new();
        let path = temp.path().join("settings.json");
        fs::write(
            &path,
            r#"{"refreshFrequency":"2m","usageBarsShowUsed":false,"unknown":9}"#,
        )
        .unwrap();
        let store = PreferencesStore::new(path);
        assert_eq!(store.get("refreshFrequency"), Some(json!("2m")));
        assert_eq!(store.get("usageBarsShowUsed"), Some(json!(false)));
        assert_eq!(store.get("unknown"), None);
        assert_eq!(store.get("showTray"), Some(json!(true)));
    }

    #[test]
    fn malformed_and_non_object_documents_keep_defaults() {
        let temp = TempDir::new();
        let path = temp.path().join("settings.json");
        fs::write(&path, "{").unwrap();
        let store = PreferencesStore::new(&path);
        assert_eq!(store.values(), default_values());
        fs::write(&path, "[]").unwrap();
        store.load();
        assert_eq!(store.values(), default_values());
    }

    #[test]
    fn updates_resets_and_exports_portable_documents() {
        let temp = TempDir::new();
        let store = PreferencesStore::new(temp.path().join("settings.json"));
        let mut updates = Map::new();
        updates.insert("refreshFrequency".into(), json!("manual"));
        updates.insert("unknown".into(), json!(true));
        store.update(updates).unwrap();
        assert_eq!(store.refresh_seconds(), 0);
        assert!(store.refresh_is_manual());
        let document = store.export_document();
        assert_eq!(document["version"], json!(1));
        assert_eq!(document["preferences"]["unknown"], json!(true));

        store.reset().unwrap();
        assert_eq!(store.values(), default_values());
    }

    #[test]
    fn imports_known_portable_keys_and_ignores_unknown_keys() {
        let temp = TempDir::new();
        let store = PreferencesStore::new(temp.path().join("settings.json"));
        store
            .import_document(&json!({
                "version": 999,
                "preferences": {
                    "refreshFrequency": "15m",
                    "futureOption": "keep out",
                }
            }))
            .unwrap();
        assert_eq!(store.get("refreshFrequency"), Some(json!("15m")));
        assert_eq!(store.get("futureOption"), None);
    }

    #[test]
    fn writes_with_private_permissions_and_reports_storage_errors() {
        let temp = TempDir::new();
        let path = temp.path().join("settings.json");
        let store = PreferencesStore::new(&path);
        store.set("showTray", json!(false), true).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&fs::read(&path).unwrap()).unwrap()["showTray"],
            json!(false)
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }

        let blocker = temp.path().join("not-a-directory");
        fs::write(&blocker, "file").unwrap();
        let failing = PreferencesStore::new(blocker.join("settings.json"));
        assert!(failing.save().is_err());
    }

    #[test]
    fn refresh_interval_mapping_matches_python() {
        let temp = TempDir::new();
        let store = PreferencesStore::new(temp.path().join("settings.json"));
        for (frequency, seconds) in [
            ("manual", 0),
            ("1m", 60),
            ("2m", 120),
            ("5m", 300),
            ("15m", 900),
            ("30m", 1800),
            ("adaptive", 300),
            ("unknown", 300),
        ] {
            store
                .set("refreshFrequency", json!(frequency), false)
                .unwrap();
            assert_eq!(store.refresh_seconds(), seconds, "{frequency}");
            assert_eq!(store.refresh_is_manual(), frequency == "manual");
        }
    }

    #[test]
    fn concurrent_updates_leave_a_complete_valid_document() {
        let temp = TempDir::new();
        let path = temp.path().join("settings.json");
        let store = std::sync::Arc::new(PreferencesStore::new(&path));
        let workers: Vec<_> = (0..8)
            .map(|worker| {
                let store = store.clone();
                std::thread::spawn(move || {
                    for index in 0..8 {
                        store
                            .set(format!("worker-{worker}-{index}"), json!(index), true)
                            .unwrap();
                    }
                })
            })
            .collect();
        for worker in workers {
            worker.join().unwrap();
        }

        let stored: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        for worker in 0..8 {
            for index in 0..8 {
                assert_eq!(stored[format!("worker-{worker}-{index}")], json!(index));
            }
        }
    }
}
