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
    cache: Mutex<Option<Vec<Sample>>>,
}

impl HistoryStore {
    pub fn new(path: impl Into<PathBuf>, retention_days: i64) -> Self {
        Self {
            path: path.into(),
            retention_days,
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
        let Ok(mut cache) = self.cache.lock() else {
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
        // Even a partial write must invalidate the previous read cache.
        *cache = None;
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
    }

    /// Drop samples older than the retention period, using the supplied clock.
    pub fn prune_at(&self, now: f64) {
        let cutoff = now - self.retention_days as f64 * 86_400.0;
        let Ok(mut cache) = self.cache.lock() else {
            return;
        };
        let samples = cache.get_or_insert_with(|| read_samples(&self.path));
        let kept: Vec<Sample> = samples
            .iter()
            .filter(|sample| sample.timestamp >= cutoff)
            .cloned()
            .collect();
        if ensure_parent(&self.path).is_err() {
            return;
        }
        let Ok(mut file) = File::create(&self.path) else {
            return;
        };
        *cache = None;
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
    }

    pub fn prune(&self) {
        self.prune_at(unix_time_seconds());
    }

    /// Read the history, ignoring blank or malformed JSON lines.
    pub fn read_all(&self) -> Vec<Sample> {
        let Ok(mut cache) = self.cache.lock() else {
            return Vec::new();
        };
        cache
            .get_or_insert_with(|| read_samples(&self.path))
            .clone()
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
}

fn read_samples(path: &Path) -> Vec<Sample> {
    let mut samples = Vec::new();
    if let Ok(file) = File::open(path) {
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
    samples
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
    // Decimal formatting rounds the original binary float like Python round(x, 2).
    // Multiplying by 100 first incorrectly turns 2.675 into the exact tie 267.5.
    format!("{value:.2}").parse().unwrap_or(value)
}

fn unix_time_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or_default()
}

fn sample_from_record(record: &Map<String, Value>) -> Option<Sample> {
    Some(Sample {
        timestamp: value_as_f64(record.get("t").unwrap_or(&json!(0.0)))?,
        provider: record.get("p").map_or(Some(""), Value::as_str)?.into(),
        window: record.get("w").map_or(Some(""), Value::as_str)?.into(),
        used_percent: value_as_f64(record.get("u").unwrap_or(&json!(0.0)))?,
    })
}

fn value_as_f64(value: &Value) -> Option<f64> {
    let number = match value {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.trim().parse().ok(),
        Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
        _ => None,
    }?;
    number.is_finite().then_some(number)
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
    fn decimal_rounding_matches_python_without_multiplying_first() {
        assert_eq!(round_two(2.675), 2.67);
        assert_eq!(round_two(1.005), 1.0);
        assert_eq!(round_two(1.015), 1.01);
        assert_eq!(round_two(1.225), 1.23);
        assert_eq!(round_two(-2.675), -2.67);
        assert_eq!(round_two(1e308), 1e308);
    }

    #[test]
    fn malformed_fields_are_skipped_instead_of_becoming_zero_samples() {
        let file = TestFile::new();
        fs::write(&file.0, "{\"t\":null}\n{\"u\":\"bad\"}\n{\"p\":[]}\n{}\n").unwrap();
        assert_eq!(file.store(30).read_all(), [sample(0.0, "", "", 0.0)]);
    }

    #[test]
    fn concurrent_writes_reads_and_prunes_keep_retained_samples() {
        let file = TestFile::new();
        let store = file.store(30);
        std::thread::scope(|scope| {
            for index in 0..16 {
                let store = &store;
                scope.spawn(move || {
                    store.append(&[sample(1_000.0, "codex", "primary", index as f64)]);
                    store.read_all();
                    store.prune_at(2_000.0);
                });
            }
        });
        assert_eq!(store.read_all().len(), 16);
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
