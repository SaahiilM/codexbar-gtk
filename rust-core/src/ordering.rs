//! Provider visibility/order and automatic tray quota selection policies.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::domain::ProviderUsage;

/// Return indices into `provider_ids`, hiding providers and applying the saved
/// order while keeping unspecified providers in their original order.
pub fn visible_order(provider_ids: &[String], order: &[String], hidden: &[String]) -> Vec<usize> {
    let hidden: HashSet<&str> = hidden.iter().map(String::as_str).collect();
    let positions: std::collections::HashMap<&str, usize> = order
        .iter()
        .enumerate()
        .map(|(index, provider)| (provider.as_str(), index))
        .collect();
    let mut indices: Vec<usize> = (0..provider_ids.len())
        .filter(|&index| !hidden.contains(provider_ids[index].as_str()))
        .collect();

    // Python sorts by saved position, original position, then provider id.
    // Original position is unique, but preserve the final key for exact parity.
    indices.sort_by_key(|&index| {
        (
            positions
                .get(provider_ids[index].as_str())
                .copied()
                .unwrap_or(10_000),
            index,
            provider_ids[index].as_str(),
        )
    });
    indices
}

/// Apply saved visibility and order preferences to provider DTOs.
///
/// Returned values are owned clones so callers can place them directly in an
/// immutable snapshot without carrying references into UI-owned data.
pub fn order_providers(
    providers: &[ProviderUsage],
    provider_order: &[String],
    hidden_providers: &[String],
) -> Vec<ProviderUsage> {
    let ids: Vec<String> = providers
        .iter()
        .map(|provider| provider.provider_id.clone())
        .collect();
    visible_order(&ids, provider_order, hidden_providers)
        .into_iter()
        .map(|index| providers[index].clone())
        .collect()
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct QuotaCandidate {
    pub used_percent: f64,
    pub placeholder: bool,
    pub window_minutes: Option<i64>,
    pub seconds_until_reset: Option<f64>,
    pub expected_used_percent: Option<f64>,
    pub eta_seconds: Option<f64>,
}

/// Owned selection result suitable for backend snapshots and serialization.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct AutomaticQuotaSelection {
    /// Index into the ordered provider vector passed to selection.
    pub provider_index: usize,
    pub provider_id: String,
    /// Index into `providers[provider_index].windows`.
    pub window_index: usize,
    pub window_key: String,
}

impl QuotaCandidate {
    fn trusted_eta(self) -> Option<f64> {
        self.window_minutes?;
        let reset = self.seconds_until_reset?;
        let expected = self.expected_used_percent?;
        let eta = self.eta_seconds?;
        if expected < 3.0 || !eta.is_finite() || eta <= 0.0 || eta >= reset {
            None
        } else {
            Some(eta)
        }
    }
}

/// Choose the flattened candidate index matching the Python Auto lane policy.
/// A strict comparison preserves the first candidate on exact ties.
pub fn automatic_selection(candidates: &[QuotaCandidate]) -> Option<usize> {
    let mut best: Option<usize> = None;
    for (index, candidate) in candidates.iter().copied().enumerate() {
        if candidate.placeholder
            || !candidate.used_percent.is_finite()
            || candidate.used_percent < 0.0
        {
            continue;
        }
        let replace = best.is_none_or(|best_index| {
            let previous = candidates[best_index];
            let candidate_full = candidate.used_percent >= 100.0;
            let previous_full = previous.used_percent >= 100.0;
            if candidate_full != previous_full {
                return candidate_full;
            }
            match (previous.trusted_eta(), candidate.trusted_eta()) {
                (None, Some(_)) => true,
                (Some(_), None) => false,
                (Some(previous_eta), Some(candidate_eta)) if previous_eta != candidate_eta => {
                    candidate_eta < previous_eta
                }
                _ => candidate.used_percent > previous.used_percent,
            }
        });
        if replace {
            best = Some(index);
        }
    }
    best
}

/// Select the quota represented by the tray, using the same provider DTOs and
/// explicit clock as the headless controller. Call with `order_providers`'
/// result so indices address the ordered snapshot data.
pub fn automatic_tray_selection(
    providers: &[ProviderUsage],
    now: DateTime<Utc>,
) -> Option<AutomaticQuotaSelection> {
    let mut candidates = Vec::new();
    let mut coordinates = Vec::new();
    for (provider_index, provider) in providers.iter().enumerate() {
        for (window_index, window) in provider.windows.iter().enumerate() {
            let pace = provider.pace.get(&window.key);
            let seconds_until_reset = window.resets_at.map(|reset| {
                let whole_seconds = reset.timestamp() - now.timestamp();
                let fractional_nanos = i64::from(reset.timestamp_subsec_nanos())
                    - i64::from(now.timestamp_subsec_nanos());
                whole_seconds as f64 + fractional_nanos as f64 / 1_000_000_000.0
            });
            candidates.push(QuotaCandidate {
                used_percent: window.used_percent,
                placeholder: window.is_placeholder,
                window_minutes: window.window_minutes,
                seconds_until_reset,
                expected_used_percent: pace.and_then(|pace| pace.expected_used_percent),
                eta_seconds: pace.and_then(|pace| pace.eta_seconds),
            });
            coordinates.push((provider_index, window_index));
        }
    }
    let selected = automatic_selection(&candidates)?;
    let (provider_index, window_index) = coordinates[selected];
    let provider = &providers[provider_index];
    let window = &provider.windows[window_index];
    Some(AutomaticQuotaSelection {
        provider_index,
        provider_id: provider.provider_id.clone(),
        window_index,
        window_key: window.key.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{Pace, RateWindow};
    use chrono::TimeZone;
    use std::collections::HashMap;

    fn candidate(used_percent: f64) -> QuotaCandidate {
        QuotaCandidate {
            used_percent,
            placeholder: false,
            window_minutes: None,
            seconds_until_reset: None,
            expected_used_percent: None,
            eta_seconds: None,
        }
    }

    fn provider(provider_id: &str, used_percent: f64, eta: Option<f64>) -> ProviderUsage {
        let window = RateWindow {
            key: "primary".to_owned(),
            title: "Session".to_owned(),
            used_percent,
            resets_at: Some(
                Utc.with_ymd_and_hms(2026, 10, 31, 12, 0, 0)
                    .single()
                    .unwrap(),
            ),
            reset_description: None,
            window_minutes: Some(300),
            next_regen_percent: None,
            is_placeholder: false,
            quota_limit: None,
            quota_unit: None,
            usage_known: true,
        };
        let pace = Pace {
            stage: "ahead".to_owned(),
            delta_percent: None,
            expected_used_percent: Some(10.0),
            will_last_to_reset: false,
            eta_seconds: eta,
            run_out_probability: None,
            summary: None,
        };
        ProviderUsage {
            provider_id: provider_id.to_owned(),
            display_name: provider_id.to_owned(),
            source: None,
            version: None,
            updated_at: None,
            account_email: None,
            plan: None,
            login_method: None,
            windows: vec![window],
            pace: HashMap::from([("primary".to_owned(), pace)]),
            credits_remaining: None,
            credits_unit: "credits".to_owned(),
            credits_available: false,
            cost: None,
            status_level: None,
            status_description: None,
            error: None,
            details: Vec::new(),
            reset_credits_available: 0,
            reset_credits: Vec::new(),
            credit_events: Vec::new(),
            accounts: Vec::new(),
            selected_account: None,
            accent_color: "#000000".to_owned(),
            raw: serde_json::Value::Null,
        }
    }

    #[test]
    fn visibility_hides_and_sorts_with_stable_unspecified_order() {
        let ids = ["claude", "codex", "gemini", "codex"].map(str::to_owned);
        let order = ["codex".to_owned()];
        let hidden = ["gemini".to_owned()];
        assert_eq!(visible_order(&ids, &order, &hidden), vec![1, 3, 0]);
        assert_eq!(visible_order(&ids, &[], &hidden), vec![0, 1, 3]);
    }

    #[test]
    fn selection_prefers_depleted_and_keeps_exact_ties_stable() {
        assert_eq!(
            automatic_selection(&[candidate(80.0), candidate(100.0), candidate(100.0)]),
            Some(1)
        );
    }

    #[test]
    fn selection_uses_only_trusted_eta_then_usage_and_excludes_placeholders() {
        let mut fast = candidate(45.0);
        fast.window_minutes = Some(300);
        fast.seconds_until_reset = Some(86_400.0);
        fast.expected_used_percent = Some(10.0);
        fast.eta_seconds = Some(7_200.0);

        let mut slow = candidate(70.0);
        slow.window_minutes = Some(300);
        slow.seconds_until_reset = Some(86_400.0);
        slow.expected_used_percent = Some(10.0);
        slow.eta_seconds = Some(18_000.0);

        assert_eq!(automatic_selection(&[slow, fast]), Some(1));
        assert_eq!(automatic_selection(&[candidate(40.0), slow]), Some(1));
        assert_eq!(
            automatic_selection(&[QuotaCandidate {
                placeholder: true,
                ..candidate(100.0)
            }]),
            None
        );
    }

    #[test]
    fn invalid_values_and_untrusted_eta_fall_back_or_are_skipped() {
        let mut sketchy = candidate(20.0);
        sketchy.window_minutes = Some(5);
        sketchy.seconds_until_reset = Some(60.0);
        sketchy.expected_used_percent = Some(2.0);
        sketchy.eta_seconds = Some(10.0);
        assert_eq!(automatic_selection(&[sketchy, candidate(80.0)]), Some(1));
        assert_eq!(
            automatic_selection(&[candidate(f64::NAN), candidate(-1.0)]),
            None
        );
    }

    #[test]
    fn dto_api_returns_owned_ordered_providers_and_stable_selection() {
        let providers = vec![
            provider("claude", 70.0, Some(18_000.0)),
            provider("codex", 45.0, Some(7_200.0)),
            provider("hidden", 100.0, None),
        ];
        let ordered = order_providers(&providers, &["codex".to_owned()], &["hidden".to_owned()]);
        assert_eq!(
            ordered
                .iter()
                .map(|item| item.provider_id.as_str())
                .collect::<Vec<_>>(),
            ["codex", "claude"]
        );
        let selected = automatic_tray_selection(
            &ordered,
            Utc.with_ymd_and_hms(2026, 10, 30, 12, 0, 0)
                .single()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(selected.provider_index, 0);
        assert_eq!(selected.provider_id, "codex");
        assert_eq!(selected.window_index, 0);
        assert_eq!(selected.window_key, "primary");
        let encoded = serde_json::to_string(&selected).unwrap();
        assert_eq!(
            serde_json::from_str::<AutomaticQuotaSelection>(&encoded).unwrap(),
            selected
        );
    }
}
