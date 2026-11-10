//! Stateful notification policy decisions. Delivery and platform APIs stay in
//! the frontend; the policy consumes the same provider snapshot as the UI.

use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Duration, Utc};

use crate::{domain::ProviderUsage, formatting};

#[derive(Clone, Debug, PartialEq)]
pub enum NotificationEvent {
    QuotaThreshold {
        provider_id: String,
        account_email: Option<String>,
        window_key: String,
        used_percent: f64,
        threshold_percent: f64,
        title: String,
        body: String,
    },
    SessionExhausted {
        provider_id: String,
        account_email: Option<String>,
        window_key: String,
        title: String,
        body: String,
    },
    PredictivePace {
        id: String,
        provider_id: String,
        account_email: Option<String>,
        window_key: String,
        title: String,
        body: String,
    },
    CreditExpiry {
        id: String,
        provider_id: String,
        title: String,
        body: String,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct NotificationPreferences {
    pub quota_enabled: bool,
    pub session_thresholds_enabled: bool,
    pub weekly_thresholds_enabled: bool,
    pub session_thresholds: Vec<f64>,
    pub weekly_thresholds: Vec<f64>,
    pub session_exhaustion_enabled: bool,
    pub predictive_pace_enabled: bool,
    pub credit_expiry_enabled: bool,
}

impl Default for NotificationPreferences {
    fn default() -> Self {
        Self {
            quota_enabled: true,
            session_thresholds_enabled: true,
            weekly_thresholds_enabled: true,
            session_thresholds: vec![50.0, 20.0],
            weekly_thresholds: vec![50.0, 20.0],
            session_exhaustion_enabled: true,
            predictive_pace_enabled: true,
            credit_expiry_enabled: true,
        }
    }
}

/// Stateful policy engine. Call once after each successful provider snapshot
/// update, passing the same accounts/windows used to publish that snapshot.
#[derive(Default)]
pub struct NotificationPolicy {
    quota_previous: HashMap<(String, String), f64>,
    exhaustion_seen: HashMap<(String, String, String), bool>,
    pace_notified: HashMap<(String, String, String), (Option<i64>, f64)>,
    credit_expiry_seen: HashSet<(String, Vec<(i64, u32)>)>,
}

impl NotificationPolicy {
    /// Apply all notification policies with an injected UTC clock. Events are
    /// returned in stable groups: quota, exhaustion, pace, then credit expiry.
    pub fn observe(
        &mut self,
        providers: &[ProviderUsage],
        preferences: &NotificationPreferences,
        now: DateTime<Utc>,
    ) -> Vec<NotificationEvent> {
        let mut events = Vec::new();
        self.observe_quota(providers, preferences, &mut events);
        self.observe_exhaustion(providers, preferences, &mut events);
        self.observe_pace(providers, preferences, now, &mut events);
        self.observe_credit_expiry(providers, preferences, now, &mut events);
        events
    }

    fn observe_quota(
        &mut self,
        providers: &[ProviderUsage],
        prefs: &NotificationPreferences,
        events: &mut Vec<NotificationEvent>,
    ) {
        if !prefs.quota_enabled {
            return;
        }
        for provider in providers {
            for window in &provider.windows {
                if !window.usage_known || window.is_placeholder || !window.used_percent.is_finite()
                {
                    continue;
                }
                let (enabled, configured): (bool, &[f64]) = match window.key.as_str() {
                    "primary" => (prefs.session_thresholds_enabled, &prefs.session_thresholds),
                    "secondary" => (prefs.weekly_thresholds_enabled, &prefs.weekly_thresholds),
                    _ => (false, &[]),
                };
                let defaults = [50.0, 20.0];
                let thresholds = if !enabled {
                    &[][..]
                } else if configured.is_empty() {
                    &defaults[..]
                } else {
                    configured
                };
                let marker = (provider.provider_id.clone(), window.key.clone());
                let previous = self.quota_previous.get(&marker).copied();
                let used = window.used_percent;
                let crossed = thresholds
                    .iter()
                    .copied()
                    .filter(|threshold| {
                        used >= *threshold && previous.is_none_or(|p| p < *threshold)
                    })
                    .filter(|threshold| threshold.is_finite())
                    .max_by(f64::total_cmp);
                if let Some(threshold) = crossed {
                    self.quota_previous.insert(marker, used);
                    events.push(NotificationEvent::QuotaThreshold {
                        provider_id: provider.provider_id.clone(),
                        account_email: provider.account_email.clone(),
                        window_key: window.key.clone(),
                        used_percent: used,
                        threshold_percent: threshold,
                        title: "Quota warning".to_owned(),
                        body: format!(
                            "{} {} at {:.0}% (threshold {:.0}%)",
                            provider.display_name, window.title, used, threshold
                        ),
                    });
                } else if previous.is_some_and(|p| used < p) {
                    self.quota_previous.insert(marker, used);
                }
            }
        }
    }

    fn observe_exhaustion(
        &mut self,
        providers: &[ProviderUsage],
        prefs: &NotificationPreferences,
        events: &mut Vec<NotificationEvent>,
    ) {
        let mut present = HashSet::new();
        for provider in providers {
            for window in provider
                .windows
                .iter()
                .filter(|window| window.key == "primary")
            {
                let account = provider.account_email.clone().unwrap_or_default();
                let key = (
                    provider.provider_id.clone(),
                    account.clone(),
                    window.key.clone(),
                );
                present.insert(key.clone());
                if !window.usage_known || window.is_placeholder || !window.used_percent.is_finite()
                {
                    continue;
                }
                let exhausted = window.used_percent >= 100.0;
                let was_exhausted = self.exhaustion_seen.get(&key).copied().unwrap_or(false);
                self.exhaustion_seen.insert(key.clone(), exhausted);
                if prefs.session_exhaustion_enabled && exhausted && !was_exhausted {
                    let account_suffix = provider
                        .account_email
                        .as_ref()
                        .map(|email| format!(" ({email})"))
                        .unwrap_or_default();
                    events.push(NotificationEvent::SessionExhausted {
                        provider_id: provider.provider_id.clone(),
                        account_email: provider.account_email.clone(),
                        window_key: window.key.clone(),
                        title: "Session quota exhausted".to_owned(),
                        body: format!(
                            "{}{} {} is exhausted.",
                            provider.display_name, account_suffix, window.title
                        ),
                    });
                }
            }
        }
        self.exhaustion_seen.retain(|key, _| present.contains(key));
    }

    fn observe_pace(
        &mut self,
        providers: &[ProviderUsage],
        prefs: &NotificationPreferences,
        now: DateTime<Utc>,
        events: &mut Vec<NotificationEvent>,
    ) {
        if !prefs.predictive_pace_enabled {
            return;
        }
        for provider in providers
            .iter()
            .filter(|p| matches!(p.provider_id.as_str(), "codex" | "claude"))
        {
            for window in &provider.windows {
                let Some(reset) = window.resets_at else {
                    continue;
                };
                let key = (
                    provider.provider_id.clone(),
                    provider.account_email.clone().unwrap_or_default(),
                    window.key.clone(),
                );
                let Some(pace) = provider.pace.get(&window.key) else {
                    self.pace_notified.remove(&key);
                    continue;
                };
                if pace.will_last_to_reset {
                    self.pace_notified.remove(&key);
                    continue;
                }
                let Some(eta) = pace.eta_seconds.filter(|eta| eta.is_finite() && *eta > 0.0) else {
                    continue;
                };
                let probability = pace.run_out_probability.unwrap_or(1.0);
                if probability < 0.5 {
                    continue;
                }
                let cycle = (
                    window.window_minutes,
                    reset.timestamp() as f64 + f64::from(reset.timestamp_subsec_nanos()) / 1e9,
                );
                if self
                    .pace_notified
                    .get(&key)
                    .is_some_and(|previous| same_cycle(*previous, cycle))
                {
                    continue;
                }
                self.pace_notified.insert(key, cycle);
                let target = now + Duration::milliseconds((eta * 1000.0).round() as i64);
                let countdown = formatting::format_countdown(Some(target), now)
                    .unwrap_or_else(|| "—".to_owned());
                let title = format!("{} {} pace warning", provider.display_name, window.title);
                let mut body = format!(
                    "At the current pace, this quota may run out in {countdown}, before it resets."
                );
                if let Some(email) = provider.account_email.as_ref() {
                    body = format!("Account {email}. {body}");
                }
                events.push(NotificationEvent::PredictivePace {
                    id: format!("predictive-pace-{}-{}", provider.provider_id, window.key),
                    provider_id: provider.provider_id.clone(),
                    account_email: provider.account_email.clone(),
                    window_key: window.key.clone(),
                    title,
                    body,
                });
            }
        }
    }

    fn observe_credit_expiry(
        &mut self,
        providers: &[ProviderUsage],
        prefs: &NotificationPreferences,
        now: DateTime<Utc>,
        events: &mut Vec<NotificationEvent>,
    ) {
        if !prefs.credit_expiry_enabled {
            return;
        }
        let limit = now + Duration::days(3);
        for provider in providers {
            let mut expiries: Vec<DateTime<Utc>> = provider
                .reset_credits
                .iter()
                .filter_map(|credit| credit.get("expiresAt").or_else(|| credit.get("expires_at")))
                .filter_map(|value| value.as_str())
                .filter_map(|value| crate::domain::parse_timestamp(Some(value)))
                .filter(|expires| *expires > now && *expires <= limit)
                .collect();
            expiries.sort();
            if expiries.is_empty() {
                continue;
            }
            let fingerprint = (
                provider.provider_id.clone(),
                expiries
                    .iter()
                    .map(|date| (date.timestamp(), date.timestamp_subsec_nanos()))
                    .collect::<Vec<_>>(),
            );
            if !self.credit_expiry_seen.insert(fingerprint) {
                continue;
            }
            let first = formatting::format_countdown(expiries.first().copied(), now)
                .unwrap_or_else(|| "soon".to_owned());
            let body = if expiries.len() == 1 {
                format!(
                    "{} rate limit reset expires in {first}.",
                    provider.display_name
                )
            } else {
                format!(
                    "{} {} rate limit resets expire within 3 days — the first one in {first}.",
                    expiries.len(),
                    provider.display_name
                )
            };
            events.push(NotificationEvent::CreditExpiry {
                id: format!("reset-credit-expiry-{}", provider.provider_id),
                provider_id: provider.provider_id.clone(),
                title: "Reset credit expiring".to_owned(),
                body,
            });
        }
    }
}

fn same_cycle(previous: (Option<i64>, f64), current: (Option<i64>, f64)) -> bool {
    if previous.0 != current.0 {
        return false;
    }
    let tolerance = (previous.0.unwrap_or(0) as f64 * 30.0).max(300.0);
    (current.1 - previous.1).abs() < tolerance
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{Pace, RateWindow};
    use chrono::TimeZone;
    use serde_json::json;

    fn provider(used: f64, reset: DateTime<Utc>) -> ProviderUsage {
        let window = RateWindow {
            key: "primary".into(),
            title: "Session".into(),
            used_percent: used,
            resets_at: Some(reset),
            reset_description: None,
            window_minutes: Some(300),
            next_regen_percent: None,
            is_placeholder: false,
            quota_limit: None,
            quota_unit: None,
            usage_known: true,
        };
        ProviderUsage {
            provider_id: "codex".into(),
            display_name: "Codex".into(),
            source: None,
            version: None,
            updated_at: None,
            account_email: Some("fixture@example.invalid".into()),
            plan: None,
            login_method: None,
            windows: vec![window],
            pace: HashMap::from([(
                "primary".into(),
                Pace {
                    stage: "behind".into(),
                    delta_percent: Some(4.0),
                    expected_used_percent: Some(10.0),
                    will_last_to_reset: false,
                    eta_seconds: Some(7_200.0),
                    run_out_probability: None,
                    summary: None,
                },
            )]),
            credits_remaining: None,
            credits_unit: "".into(),
            credits_available: false,
            cost: None,
            status_level: None,
            status_description: None,
            error: None,
            details: Vec::new(),
            reset_credits_available: 1,
            reset_credits: vec![json!({"expiresAt": (reset - Duration::hours(2)).to_rfc3339()})],
            credit_events: Vec::new(),
            accounts: Vec::new(),
            selected_account: None,
            accent_color: String::new(),
            raw: json!({"provider":"codex"}),
        }
    }

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 22, 12, 0, 0)
            .single()
            .unwrap()
    }

    #[test]
    fn emits_all_policy_kinds_once_and_preserves_threshold_rearm() {
        let now = now();
        let mut policy = NotificationPolicy::default();
        let provider = provider(100.0, now + Duration::hours(24));
        let prefs = NotificationPreferences::default();
        let events = policy.observe(std::slice::from_ref(&provider), &prefs, now);
        assert!(matches!(
            events[0],
            NotificationEvent::QuotaThreshold {
                threshold_percent: 50.0,
                ..
            }
        ));
        assert!(matches!(
            events[1],
            NotificationEvent::SessionExhausted { .. }
        ));
        assert!(matches!(
            events[2],
            NotificationEvent::PredictivePace { .. }
        ));
        assert!(matches!(events[3], NotificationEvent::CreditExpiry { .. }));
        assert!(policy
            .observe(std::slice::from_ref(&provider), &prefs, now)
            .is_empty());

        let mut recovered = provider.clone();
        recovered.windows[0].used_percent = 10.0;
        recovered
            .pace
            .get_mut("primary")
            .unwrap()
            .will_last_to_reset = true;
        policy.observe(&[recovered], &prefs, now);
        let rearmed = policy.observe(&[provider], &prefs, now);
        assert!(rearmed
            .iter()
            .any(|event| matches!(event, NotificationEvent::QuotaThreshold { .. })));
        assert!(rearmed
            .iter()
            .any(|event| matches!(event, NotificationEvent::SessionExhausted { .. })));
        assert!(rearmed
            .iter()
            .any(|event| matches!(event, NotificationEvent::PredictivePace { .. })));
        assert!(!rearmed
            .iter()
            .any(|event| matches!(event, NotificationEvent::CreditExpiry { .. })));
    }

    #[test]
    fn disabled_exhaustion_still_tracks_and_disappearance_rearms_it() {
        let now = now();
        let provider = provider(100.0, now + Duration::hours(24));
        let mut policy = NotificationPolicy::default();
        let prefs = NotificationPreferences {
            session_exhaustion_enabled: false,
            ..Default::default()
        };
        assert!(!policy
            .observe(std::slice::from_ref(&provider), &prefs, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::SessionExhausted { .. })));
        let mut unknown = provider.clone();
        unknown.windows[0].usage_known = false;
        unknown.windows[0].used_percent = 0.0;
        assert!(!policy
            .observe(&[unknown], &prefs, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::SessionExhausted { .. })));
        let enabled = NotificationPreferences::default();
        assert!(!policy
            .observe(std::slice::from_ref(&provider), &enabled, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::SessionExhausted { .. })));
        policy.observe(&[], &enabled, now);
        assert!(policy
            .observe(&[provider], &enabled, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::SessionExhausted { .. })));
    }

    #[test]
    fn pace_cycle_tolerates_small_reset_corrections_but_rearms_on_new_cycle() {
        let now = now();
        let mut policy = NotificationPolicy::default();
        let prefs = NotificationPreferences::default();
        let first = provider(20.0, now + Duration::hours(24));
        assert!(policy
            .observe(std::slice::from_ref(&first), &prefs, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::PredictivePace { .. })));
        let mut corrected = first.clone();
        corrected.windows[0].resets_at = Some(now + Duration::hours(24) + Duration::minutes(2));
        assert!(!policy
            .observe(std::slice::from_ref(&corrected), &prefs, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::PredictivePace { .. })));
        corrected.windows[0].resets_at = Some(now + Duration::hours(30));
        assert!(policy
            .observe(&[corrected], &prefs, now)
            .iter()
            .any(|e| matches!(e, NotificationEvent::PredictivePace { .. })));
    }
}
