//! Currency catalog and deterministic USD-pivoted conversion policy.
use std::collections::BTreeMap;

pub const CACHE_TTL_SECONDS: u64 = 24 * 60 * 60;

/// Bundled fallback values and labels, kept in parity with `currency.py`.
pub const CURRENCIES: &[(&str, &str, f64)] = &[
    ("USD", "$", 1.0),
    ("GBP", "£", 0.79),
    ("EUR", "€", 0.92),
    ("CZK", "Kč", 21.0),
    ("CNY", "¥", 7.27),
    ("JPY", "¥", 154.0),
    ("KRW", "₩", 1428.90),
    ("CAD", "$", 1.38),
    ("AUD", "$", 1.55),
    ("HKD", "$", 7.80),
    ("TWD", "NT$", 32.30),
    ("SGD", "$", 1.34),
    ("INR", "₹", 84.50),
    ("CHF", "Fr.", 0.80),
    ("AED", "د.إ", 3.6725),
    ("TRY", "₺", 48.5),
    ("NZD", "$", 1.761),
    ("SEK", "kr", 9.908),
    ("NOK", "kr", 9.480),
    ("DKK", "kr", 6.554),
    ("PLN", "zł", 3.838),
    ("BRL", "R$", 5.117),
    ("MXN", "$", 17.47),
    ("ZAR", "R", 16.36),
    ("THB", "฿", 33.37),
    ("IDR", "Rp", 17836.0),
    ("VND", "₫", 25962.0),
    ("UAH", "₴", 44.86),
    ("ILS", "₪", 3.109),
];

#[derive(Clone, Debug, PartialEq)]
pub struct Rate {
    pub code: String,
    pub symbol: String,
    pub value: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CurrencyCatalog {
    rates: BTreeMap<String, Rate>,
}

impl Default for CurrencyCatalog {
    fn default() -> Self {
        let rates = CURRENCIES
            .iter()
            .map(|(code, symbol, value)| {
                (
                    (*code).to_owned(),
                    Rate {
                        code: (*code).to_owned(),
                        symbol: (*symbol).to_owned(),
                        value: *value,
                    },
                )
            })
            .collect();
        Self { rates }
    }
}

impl CurrencyCatalog {
    pub fn get(&self, code: &str) -> Option<&Rate> {
        self.rates.get(&code.trim().to_uppercase())
    }
    pub fn codes(&self) -> Vec<String> {
        CURRENCIES
            .iter()
            .map(|(code, _, _)| (*code).to_owned())
            .collect()
    }
    pub fn label(&self, code: &str) -> String {
        let normalized = code.trim().to_uppercase();
        self.get(&normalized).map_or(normalized.clone(), |rate| {
            format!("{normalized} ({})", rate.symbol)
        })
    }
    pub fn rate(&self, code: &str) -> Option<f64> {
        self.get(code).map(|rate| rate.value)
    }
    pub fn convert(&self, amount: f64, source: &str, target: &str) -> Option<f64> {
        let src = source.trim().to_uppercase();
        let dst = target.trim().to_uppercase();
        if src.is_empty() || dst.is_empty() || src == dst {
            return Some(amount);
        }
        let sr = self.rate(&src)?;
        let dr = self.rate(&dst)?;
        if sr <= 0.0 || dr <= 0.0 {
            return None;
        }
        Some(amount / sr * dr)
    }
    /// Replace known catalog rates only; the USD pivot is always exactly one.
    pub fn with_rates(&self, rates: &serde_json::Map<String, serde_json::Value>) -> Self {
        let mut result = self.clone();
        for (code, value) in rates {
            let code = code.to_uppercase();
            if code == "USD" {
                continue;
            }
            if let (Some(old), Some(value)) = (result.rates.get(&code).cloned(), value.as_f64()) {
                if value.is_finite() && value > 0.0 {
                    result.rates.insert(code, Rate { value, ..old });
                }
            }
        }
        result
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct RateCache {
    pub fetched_at: f64,
    pub rates: BTreeMap<String, f64>,
}

impl RateCache {
    pub fn parse(json: &str) -> Option<Self> {
        let payload: serde_json::Value = serde_json::from_str(json).ok()?;
        let fetched_at = payload.get("fetchedAt")?.as_f64()?;
        if !fetched_at.is_finite() || fetched_at < 0.0 {
            return None;
        }
        let rates = payload.get("rates")?.as_object()?;
        let mut cleaned = BTreeMap::new();
        for (code, value) in rates {
            let code = code.to_uppercase();
            if CurrencyCatalog::default().get(&code).is_some() {
                if let Some(rate) = value
                    .as_f64()
                    .filter(|rate| rate.is_finite() && *rate > 0.0)
                {
                    cleaned.insert(code, rate);
                }
            }
        }
        if cleaned.is_empty() {
            return None;
        }
        cleaned.insert("USD".into(), 1.0);
        Some(Self {
            fetched_at,
            rates: cleaned,
        })
    }
    pub fn serialize(&self) -> String {
        serde_json::json!({"fetchedAt": self.fetched_at, "rates": self.rates}).to_string()
    }
    pub fn is_fresh(&self, now: f64) -> bool {
        now.is_finite()
            && now >= self.fetched_at
            && now - self.fetched_at < CACHE_TTL_SECONDS as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn catalog_labels_and_order_match_python() {
        let c = CurrencyCatalog::default();
        assert_eq!(
            c.codes(),
            CURRENCIES
                .iter()
                .map(|x| x.0.to_string())
                .collect::<Vec<_>>()
        );
        assert_eq!(c.label("eur"), "EUR (€)");
        assert_eq!(c.label("xxx"), "XXX");
    }
    #[test]
    fn conversion_handles_empty_same_unknown_and_usd_pivot() {
        let c = CurrencyCatalog::default();
        assert_eq!(c.convert(3.0, "eur", "EUR"), Some(3.0));
        assert_eq!(c.convert(100.0, "USD", "EUR"), Some(92.0));
        assert_eq!(c.convert(92.0, "EUR", "USD"), Some(100.0));
        assert_eq!(c.convert(1.0, "USD", "ZZZ"), None);
        assert_eq!(c.convert(3.0, "", "XXX"), Some(3.0));
    }
    #[test]
    fn cache_filters_unknown_and_invalid_rates_and_roundtrips() {
        let cache = RateCache::parse(
            r#"{"fetchedAt":1000,"rates":{"USD":4,"EUR":1.2,"XXX":2,"GBP":0,"CAD":"bad"}}"#,
        )
        .unwrap();
        assert_eq!(cache.rates.len(), 2);
        assert_eq!(cache.rates["USD"], 1.0);
        assert_eq!(RateCache::parse(&cache.serialize()), Some(cache));
    }
    #[test]
    fn ttl_boundary_is_expired() {
        let c = RateCache {
            fetched_at: 100.0,
            rates: BTreeMap::new(),
        };
        assert!(c.is_fresh(100.0));
        assert!(!c.is_fresh(100.0 + CACHE_TTL_SECONDS as f64));
    }
}
