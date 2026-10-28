//! Local JSON-lines quota history store, ported from `codexbar_gtk/history.py`.

use serde_json::{json, Map, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub const RETENTION_DAYS: i64 = 30;
pub const DEFAULT_RELATIVE_PATH: &str = ".config/codexbar-gtk/history.jsonl";

#[derive(Debug, Clone, PartialEq)]
pub struct Sample {
    pub timestamp: f64,
    pub provider: String,
    pub window: String,
    pub used_percent: f64,
}

/// Append-only sample log with a small in-memory read cache.
pub struct HistoryStore {
    path: PathBuf,
    retention_days: i64,
    write_lock: Mutex<()>,
    cache: Mutex<Option<Vec<Sample>>>,
}

impl HistoryStore {
    pub fn new(path: impl Into<PathBuf>, retention_days: i64) -> Self {
        Self {
            path: path.into(),
            retention_days,
            write_lock: Mutex::new(()),
            cache: Mutex::new(None),
        }
    }

    pub fn default_path() -> PathBuf {
        std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join(DEFAULT_RELATIVE_PATH)
    }

    pub fn default_store() -> Self {
        Self::new(Self::default_path(), RETENTION_DAYS)
    }

    /// Append samples, ignoring filesystem errors as the Python client does.
    pub fn append(&self, samples: &[Sample]) {
        if samples.is_empty() {
            return;
        }
        let Ok(_guard) = self.write_lock.lock() else {
            return;
        };
        if ensure_parent(&self.path).is_err() {
            return;
        }
        let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        else {
            return;
        };
        for sample in samples {
            let record = json!({
                "t": round_two(sample.timestamp),
                "p": sample.provider,
                "w": sample.window,
                "u": round_two(sample.used_percent),
            });
            if serde_json::to_writer(&mut file, &record).is_err() || file.write_all(b"\n").is_err()
            {
                return;
            }
        }
        self.invalidate_cache();
    }

    /// Drop samples older than the retention period, using the supplied clock.
    pub fn prune_at(&self, now: f64) {
        let cutoff = now - self.retention_days as f64 * 86_400.0;
        let kept: Vec<Sample> = self
            .read_all()
            .into_iter()
            .filter(|sample| sample.timestamp >= cutoff)
            .collect();
        let Ok(_guard) = self.write_lock.lock() else {
            return;
        };
        if ensure_parent(&self.path).is_err() {
            return;
        }
        let Ok(mut file) = File::create(&self.path) else {
            return;
        };
        for sample in kept {
            let record = json!({
                "t": round_two(sample.timestamp),
                "p": sample.provider,
                "w": sample.window,
                "u": round_two(sample.used_percent),
            });
            if serde_json::to_writer(&mut file, &record).is_err() || file.write_all(b"\n").is_err()
            {
                return;
            }
        }
        self.invalidate_cache();
    }

    pub fn prune(&self) {
        self.prune_at(unix_time_seconds());
    }

    /// Read the history, ignoring blank or malformed JSON lines.
    pub fn read_all(&self) -> Vec<Sample> {
        if let Ok(cache) = self.cache.lock() {
            if let Some(samples) = cache.as_ref() {
                return samples.clone();
            }
        }

        let mut samples = Vec::new();
        if let Ok(file) = File::open(&self.path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let Ok(Value::Object(record)) = serde_json::from_str::<Value>(line) else {
                    continue;
                };
                if let Some(sample) = sample_from_record(&record) {
                    samples.push(sample);
                }
            }
        }

        if let Ok(mut cache) = self.cache.lock() {
            *cache = Some(samples.clone());
        }
        samples
    }

    /// Return sorted `(timestamp, used_percent)` points within the last `hours`.
    pub fn series_at(&self, provider: &str, window: &str, hours: f64, now: f64) -> Vec<(f64, f64)> {
        let cutoff = now - hours * 3_600.0;
        let mut points: Vec<(f64, f64)> = self
            .read_all()
            .into_iter()
            .filter(|sample| {
                sample.provider == provider && sample.window == window && sample.timestamp >= cutoff
            })
            .map(|sample| (sample.timestamp, sample.used_percent))
            .collect();
        points.sort_by(|left, right| left.0.total_cmp(&right.0));
        points
    }

    pub fn series(&self, provider: &str, window: &str, hours: f64) -> Vec<(f64, f64)> {
        self.series_at(provider, window, hours, unix_time_seconds())
    }

    fn invalidate_cache(&self) {
        if let Ok(mut cache) = self.cache.lock() {
            *cache = None;
        }
    }
}

fn ensure_parent(path: &Path) -> std::io::Result<()> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn round_two(value: f64) -> f64 {
    (value * 100.0).round_ties_even() / 100.0
}

fn unix_time_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or_default()
}

fn sample_from_record(record: &Map<String, Value>) -> Option<Sample> {
    Some(Sample {
        timestamp: value_as_f64(record.get("t")).unwrap_or(0.0),
        provider: value_as_string(record.get("p")).unwrap_or_default(),
        window: value_as_string(record.get("w")).unwrap_or_default(),
        used_percent: value_as_f64(record.get("u")).unwrap_or(0.0),
    })
}

fn value_as_f64(value: Option<&Value>) -> Option<f64> {
    match value? {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.parse().ok(),
        Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
        _ => None,
    }
}

fn value_as_string(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::String(text) => Some(text.clone()),
        Value::Null => Some("None".into()),
        Value::Bool(value) => Some(if *value { "True" } else { "False" }.into()),
        Value::Number(number) => Some(number.to_string()),
        Value::Array(_) | Value::Object(_) => Some(value?.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT_TEST_ID: AtomicUsize = AtomicUsize::new(0);

    struct TestFile(PathBuf);

    impl TestFile {
        fn new() -> Self {
            let id = NEXT_TEST_ID.fetch_add(1, Ordering::Relaxed);
            Self(std::env::temp_dir().join(format!(
                "codexbar-history-{}-{id}.jsonl",
                std::process::id()
            )))
        }

        fn store(&self, retention_days: i64) -> HistoryStore {
            HistoryStore::new(&self.0, retention_days)
        }
    }

    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn sample(timestamp: f64, provider: &str, window: &str, used_percent: f64) -> Sample {
        Sample {
            timestamp,
            provider: provider.into(),
            window: window.into(),
            used_percent,
        }
    }

    #[test]
    fn appends_json_lines_and_queries_sorted_series() {
        let file = TestFile::new();
        let store = file.store(30);
        store.append(&[
            sample(1_000.126, "codex", "primary", 10.236),
            sample(800.0, "codex", "primary", 5.0),
            sample(900.0, "codex", "secondary", 3.0),
        ]);
        assert_eq!(store.read_all().len(), 3);
        assert_eq!(
            store.series_at("codex", "primary", 1.0, 1_000.0),
            [(800.0, 5.0), (1_000.13, 10.24)]
        );
        let contents = fs::read_to_string(&file.0).unwrap();
        assert!(contents
            .lines()
            .all(|line| serde_json::from_str::<Value>(line).is_ok()));
        let first: Value = serde_json::from_str(contents.lines().next().unwrap()).unwrap();
        assert_eq!(first["p"], "codex");
        assert_eq!(first["w"], "primary");
        assert_eq!(first["u"], 10.24);
    }

    #[test]
    fn skips_blank_and_malformed_records_and_caches_reads() {
        let file = TestFile::new();
        let store = file.store(30);
        store.append(&[sample(10.0, "claude", "weekly", 20.0)]);
        OpenOptions::new()
            .append(true)
            .open(&file.0)
            .unwrap()
            .write_all(b"\nnot json\n[]\n")
            .unwrap();
        assert_eq!(store.read_all(), [sample(10.0, "claude", "weekly", 20.0)]);
    }

    #[test]
    fn prune_keeps_samples_on_or_after_the_retention_cutoff() {
        let file = TestFile::new();
        let store = file.store(1);
        store.append(&[
            sample(1_000.0, "codex", "primary", 10.0),
            sample(86_400.0, "codex", "primary", 20.0),
            sample(86_400.1, "codex", "primary", 30.0),
        ]);
        store.prune_at(172_800.0);
        assert_eq!(
            store.read_all(),
            [
                sample(86_400.0, "codex", "primary", 20.0),
                sample(86_400.1, "codex", "primary", 30.0),
            ]
        );
    }
}
