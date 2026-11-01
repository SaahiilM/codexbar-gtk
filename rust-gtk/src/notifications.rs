use codexbar_core::notifications::NotificationEvent;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NotificationContent {
    pub id: String,
    pub title: String,
    pub body: String,
}

/// Convert a typed policy event to a platform-neutral delivery payload. The
/// identifier is stable per event identity and never includes account labels.
pub fn notification_content(event: &NotificationEvent) -> NotificationContent {
    let (kind, identity, title, body) = match event {
        NotificationEvent::QuotaThreshold {
            provider_id,
            account_email,
            window_key,
            threshold_percent,
            title,
            body,
            ..
        } => (
            "quota",
            format!("{provider_id}:{account_email:?}:{window_key}:{threshold_percent}"),
            title,
            body,
        ),
        NotificationEvent::SessionExhausted {
            provider_id,
            account_email,
            window_key,
            title,
            body,
        } => (
            "session-exhausted",
            format!("{provider_id}:{account_email:?}:{window_key}"),
            title,
            body,
        ),
        NotificationEvent::PredictivePace {
            id, title, body, ..
        } => ("predictive-pace", id.clone(), title, body),
        NotificationEvent::CreditExpiry {
            id, title, body, ..
        } => ("credit-expiry", id.clone(), title, body),
    };
    NotificationContent {
        id: format!("codexbar-{kind}-{:016x}", stable_hash(kind, &identity)),
        title: title.clone(),
        body: body.clone(),
    }
}

fn stable_hash(kind: &str, identity: &str) -> u64 {
    kind.bytes()
        .chain([0])
        .chain(identity.bytes())
        .fold(0xcbf29ce484222325, |hash, byte| {
            (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_preserves_policy_copy_but_identifier_hides_account() {
        let event = NotificationEvent::QuotaThreshold {
            provider_id: "fixture-provider".to_owned(),
            account_email: Some("synthetic@example.test".to_owned()),
            window_key: "primary".to_owned(),
            used_percent: 80.0,
            threshold_percent: 80.0,
            title: "Synthetic quota warning".to_owned(),
            body: "Fixture quota is at 80 percent.".to_owned(),
        };
        let content = notification_content(&event);
        assert_eq!(content.title, "Synthetic quota warning");
        assert_eq!(content.body, "Fixture quota is at 80 percent.");
        assert!(!content.id.contains("synthetic@example.test"));
        assert_eq!(content, notification_content(&event));
    }

    #[test]
    fn predictive_and_credit_events_keep_distinct_stable_ids() {
        let pace = NotificationEvent::PredictivePace {
            id: "fixture-pace".to_owned(),
            provider_id: "synthetic".to_owned(),
            account_email: None,
            window_key: "primary".to_owned(),
            title: "Pace".to_owned(),
            body: "Fixture".to_owned(),
        };
        let credit = NotificationEvent::CreditExpiry {
            id: "fixture-credit".to_owned(),
            provider_id: "synthetic".to_owned(),
            title: "Credit".to_owned(),
            body: "Fixture".to_owned(),
        };
        assert_ne!(
            notification_content(&pace).id,
            notification_content(&credit).id
        );
    }
}
