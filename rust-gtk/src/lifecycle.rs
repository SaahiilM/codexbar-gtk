use std::time::{Duration, Instant};

/// Wait for a graphical session to become usable before constructing the
/// application. The installed user unit intentionally starts before the tray
/// host, so an unavailable display during login is a transient condition.
pub fn wait_for_display(timeout: Duration) -> bool {
    wait_for_display_with(
        || gtk::init().is_ok() && gtk::gdk::Display::default().is_some(),
        timeout,
        Duration::from_millis(250),
        std::thread::sleep,
    )
}

pub fn wait_for_display_with(
    mut check: impl FnMut() -> bool,
    timeout: Duration,
    interval: Duration,
    mut sleep: impl FnMut(Duration),
) -> bool {
    let started = Instant::now();
    loop {
        if check() {
            return true;
        }
        let remaining = timeout.saturating_sub(started.elapsed());
        if remaining.is_zero() {
            return false;
        }
        sleep(interval.min(remaining));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn returns_when_display_becomes_ready() {
        let attempts = Cell::new(0);
        let sleeps = Cell::new(0);
        let ready = wait_for_display_with(
            || {
                let attempt = attempts.get() + 1;
                attempts.set(attempt);
                attempt == 3
            },
            Duration::from_secs(2),
            Duration::from_millis(250),
            |_| sleeps.set(sleeps.get() + 1),
        );
        assert!(ready);
        assert_eq!(attempts.get(), 3);
        assert_eq!(sleeps.get(), 2);
    }

    #[test]
    fn reports_unavailable_display_after_deadline() {
        let sleeps = Cell::new(0);
        let ready = wait_for_display_with(
            || false,
            Duration::ZERO,
            Duration::from_millis(250),
            |_| sleeps.set(sleeps.get() + 1),
        );
        assert!(!ready);
        assert_eq!(sleeps.get(), 0);
    }
}
