//! Bounded asynchronous currency-rate refresh with a persistent offline cache.
use codexbar_core::currency::{CurrencyCatalog, RateCache, CACHE_TTL_SECONDS};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

const DEFAULT_URL: &str = "https://open.er-api.com/v6/latest/USD";
const MAX_BODY: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RateSource {
    Offline,
    Cache,
    Live,
}

#[derive(Clone, Debug)]
pub struct CurrencyStatus {
    pub fetched_at: f64,
    pub source: RateSource,
    pub last_refresh_failed: bool,
}

#[derive(Clone)]
struct State {
    catalog: CurrencyCatalog,
    fetched_at: f64,
    source: RateSource,
    last_refresh_failed: bool,
}

/// Shared currency service. Failed/malformed HTTP refreshes leave the cache and
/// bundled fallback values available; the GUI can call `ensure_rates` without
/// blocking while requests remain bounded to 15 seconds and 64 KiB.
#[derive(Clone)]
pub struct CurrencyService {
    state: Arc<Mutex<State>>,
    single_flight: Arc<tokio::sync::Mutex<()>>,
    cache_path: PathBuf,
    client: reqwest::Client,
    url: String,
}

impl CurrencyService {
    pub fn new(cache_path: impl Into<PathBuf>) -> Self {
        Self::with_endpoint(cache_path, DEFAULT_URL)
    }
    pub fn with_endpoint(cache_path: impl Into<PathBuf>, url: impl Into<String>) -> Self {
        let cache_path = cache_path.into();
        let (catalog, fetched_at, source) = read_cache(&cache_path).unwrap_or((
            CurrencyCatalog::default(),
            0.0,
            RateSource::Offline,
        ));
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .build()
            .expect("reqwest client configuration is static and valid");
        Self {
            state: Arc::new(Mutex::new(State {
                catalog,
                fetched_at,
                source,
                last_refresh_failed: false,
            })),
            single_flight: Arc::new(tokio::sync::Mutex::new(())),
            cache_path,
            client,
            url: url.into(),
        }
    }
    pub fn catalog(&self) -> CurrencyCatalog {
        self.state
            .lock()
            .expect("currency state lock")
            .catalog
            .clone()
    }
    pub async fn catalog_async(&self) -> CurrencyCatalog {
        self.catalog()
    }
    pub fn status(&self) -> CurrencyStatus {
        let state = self.state.lock().expect("currency state lock");
        CurrencyStatus {
            fetched_at: state.fetched_at,
            source: state.source,
            last_refresh_failed: state.last_refresh_failed,
        }
    }
    pub async fn status_async(&self) -> CurrencyStatus {
        self.status()
    }
    pub fn rate(&self, code: &str) -> Option<f64> {
        if code.trim().is_empty() {
            return Some(1.0);
        }
        self.state.lock().ok()?.catalog.rate(code)
    }
    pub async fn rate_async(&self, code: &str) -> Option<f64> {
        self.rate(code)
    }
    pub fn convert(&self, amount: f64, source: &str, target: &str) -> Option<f64> {
        self.state
            .lock()
            .ok()?
            .catalog
            .convert(amount, source, target)
    }
    pub async fn convert_async(&self, amount: f64, source: &str, target: &str) -> Option<f64> {
        self.convert(amount, source, target)
    }
    pub fn needs_refresh(&self, now: f64) -> bool {
        let state = self.state.lock().expect("currency state lock");
        state.fetched_at <= 0.0
            || now < state.fetched_at
            || now - state.fetched_at >= CACHE_TTL_SECONDS as f64
    }
    pub async fn ensure_rates(&self, preferred: &str) -> bool {
        self.ensure_rates_at(preferred, epoch_seconds()).await
    }
    /// Testable freshness entry point. Callers normally use `ensure_rates`;
    /// the supplied epoch time is used for TTL decisions and cache metadata.
    pub async fn ensure_rates_at(&self, preferred: &str, now: f64) -> bool {
        let preferred = preferred.trim().to_uppercase();
        if preferred.is_empty()
            || preferred == "AUTO"
            || preferred == "USD"
            || self.rate(&preferred).is_none()
        {
            return false;
        }
        if !self.needs_refresh(now) {
            return false;
        }
        let _flight = self.single_flight.lock().await;
        if !self.needs_refresh(now) {
            return false;
        }
        if self.fetch_and_store(now).await.is_ok() {
            return true;
        }
        if let Ok(mut state) = self.state.lock() {
            state.last_refresh_failed = true;
        }
        false
    }
    async fn fetch_and_store(&self, now: f64) -> Result<(), ()> {
        let response = self.client.get(&self.url).send().await.map_err(|_| ())?;
        if !response.status().is_success()
            || response
                .content_length()
                .is_some_and(|size| size > MAX_BODY as u64)
        {
            return Err(());
        }
        let mut response = response;
        let mut body = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| ())? {
            if body.len() + chunk.len() > MAX_BODY {
                return Err(());
            }
            body.extend_from_slice(&chunk);
        }
        let json: serde_json::Value = serde_json::from_slice(&body).map_err(|_| ())?;
        let rates = json
            .get("rates")
            .and_then(serde_json::Value::as_object)
            .ok_or(())?;
        let cache = {
            let mut state = self.state.lock().map_err(|_| ())?;
            let catalog = state.catalog.with_rates(rates);
            state.catalog = catalog.clone();
            state.fetched_at = now;
            state.source = RateSource::Live;
            state.last_refresh_failed = false;
            let rates = catalog
                .codes()
                .into_iter()
                .filter_map(|code| catalog.rate(&code).map(|rate| (code, rate)))
                .collect();
            RateCache {
                fetched_at: now,
                rates,
            }
        };
        write_cache(&self.cache_path, &cache).await;
        Ok(())
    }
}

fn epoch_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}
fn read_cache(path: &Path) -> Option<(CurrencyCatalog, f64, RateSource)> {
    let json = std::fs::read_to_string(path).ok()?;
    let cache = RateCache::parse(&json)?;
    let mut rates = serde_json::Map::new();
    for (code, rate) in cache.rates {
        rates.insert(code, serde_json::Value::from(rate));
    }
    Some((
        CurrencyCatalog::default().with_rates(&rates),
        cache.fetched_at,
        RateSource::Cache,
    ))
}
async fn write_cache(path: &Path, cache: &RateCache) {
    let Some(parent) = path.parent() else {
        return;
    };
    if tokio::fs::create_dir_all(parent).await.is_err() {
        return;
    }
    let mut temp = path.as_os_str().to_os_string();
    temp.push(format!(".{}.tmp", std::process::id()));
    let temp = PathBuf::from(temp);
    if tokio::fs::write(&temp, cache.serialize()).await.is_ok()
        && tokio::fs::rename(&temp, path).await.is_err()
    {
        let _ = tokio::fs::remove_file(temp).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cache_loaded_and_stale_detection_injected_time() {
        let dir = std::env::temp_dir().join(format!("currency-cache-{}", std::process::id()));
        let file = dir.join("rates.json");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(&file, r#"{"fetchedAt":100,"rates":{"EUR":1.2}}"#).unwrap();
        let service = CurrencyService::with_endpoint(&file, "http://127.0.0.1:1");
        assert_eq!(service.rate("eur"), Some(1.2));
        assert!(!service.needs_refresh(101.0));
        assert!(service.needs_refresh(100.0 + CACHE_TTL_SECONDS as f64));
        let _ = std::fs::remove_dir_all(dir);
    }
    #[tokio::test]
    async fn offline_refresh_retains_cached_rates() {
        let dir = std::env::temp_dir().join(format!("currency-offline-{}", std::process::id()));
        let file = dir.join("rates.json");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(&file, r#"{"fetchedAt":0,"rates":{"EUR":1.25}}"#).unwrap();
        let service = CurrencyService::with_endpoint(&file, "http://127.0.0.1:1");
        assert!(!service.ensure_rates("EUR").await);
        assert_eq!(service.convert(100.0, "USD", "EUR"), Some(125.0));
        assert_eq!(service.status().source, RateSource::Cache);
        assert!(service.status().last_refresh_failed);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[tokio::test]
    async fn injected_http_refresh_is_single_flight_and_persists_live_rates() {
        use std::io::{Read, Write};
        use std::sync::atomic::{AtomicUsize, Ordering};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = calls.clone();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            server_calls.fetch_add(1, Ordering::SeqCst);
            let mut request = [0; 1024];
            let _ = stream.read(&mut request);
            let body = r#"{"rates":{"USD":1,"EUR":1.25,"XXX":15}}"#;
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        });
        let dir = std::env::temp_dir().join(format!("currency-live-{}", std::process::id()));
        let file = dir.join("rates.json");
        let service = CurrencyService::with_endpoint(&file, format!("http://{address}/rates"));
        let (a, b) = tokio::join!(
            service.ensure_rates_at("EUR", 1234.0),
            service.ensure_rates_at("EUR", 1234.0)
        );
        assert!(a || b);
        server.join().unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(service.status().source, RateSource::Live);
        assert_eq!(service.status().fetched_at, 1234.0);
        assert_eq!(service.convert(100.0, "USD", "EUR"), Some(125.0));
        let reloaded = CurrencyService::with_endpoint(&file, "http://127.0.0.1:1");
        assert_eq!(reloaded.status().source, RateSource::Cache);
        assert_eq!(reloaded.convert(100.0, "USD", "EUR"), Some(125.0));
        let _ = std::fs::remove_dir_all(dir);
    }

    #[tokio::test]
    async fn response_without_content_length_is_stopped_at_the_body_limit() {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 1024];
            let _ = stream.read(&mut request);
            let body = "x".repeat(MAX_BODY + 1);
            write!(stream, "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{body}").unwrap();
        });
        let dir = std::env::temp_dir().join(format!("currency-large-{}", std::process::id()));
        let service = CurrencyService::with_endpoint(
            dir.join("rates.json"),
            format!("http://{address}/rates"),
        );
        assert!(!service.ensure_rates("EUR").await);
        assert!(service.status().last_refresh_failed);
        assert_eq!(service.convert(100.0, "USD", "EUR"), Some(92.0));
        server.join().unwrap();
        let _ = std::fs::remove_dir_all(dir);
    }
}
