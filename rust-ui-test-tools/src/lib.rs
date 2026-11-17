//! Shared contracts for native UI test tooling.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AccessibleCell {
    pub role: String,
    pub name: String,
    pub text: Option<String>,
    pub pid: u32,
    pub states: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AccessibleRow {
    pub role: String,
    pub identity: String,
    pub pid: u32,
    pub states: Vec<String>,
    pub descendants: Vec<AccessibleCell>,
}

/// Return exact visible same-process filename rows with unique tree identities.
pub fn exact_selected_row_records(
    rows: &[AccessibleRow],
    filename: &str,
    app_pid: u32,
    require_selected: bool,
) -> Vec<AccessibleRow> {
    let mut matches = Vec::new();
    for row in rows {
        let states: HashSet<&str> = row.states.iter().map(String::as_str).collect();
        if row.role != "table row"
            || row.pid != app_pid
            || row.identity.is_empty()
            || !states.contains("showing")
            || !states.contains("sensitive")
            || (require_selected && !states.contains("selected"))
        {
            continue;
        }
        if row.descendants.iter().any(|cell| {
            matches!(cell.role.as_str(), "label" | "table cell")
                && cell.pid == app_pid
                && cell.states.iter().any(|s| s == "showing")
                && cell.states.iter().any(|s| s == "sensitive")
                && (cell.name == filename || cell.text.as_deref() == Some(filename))
        }) {
            matches.push(row.clone());
        }
    }
    let identities: HashSet<&str> = matches.iter().map(|row| row.identity.as_str()).collect();
    if identities.len() != matches.len() {
        Vec::new()
    } else {
        matches
    }
}

pub fn target_window_contains(geometry: [i32; 4], x: i32, y: i32) -> bool {
    let [gx, gy, width, height] = geometry;
    width > 0
        && height > 0
        && gx <= x
        && x < gx.saturating_add(width)
        && gy <= y
        && y < gy.saturating_add(height)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GuardSample {
    pub pid: u32,
    pub active: bool,
    pub top_hit: bool,
    pub cursor: [i32; 2],
    pub received: f64,
}

/// Fresh KWin observation gate used before any allowed physical-input path.
pub fn guarded_target(sample: GuardSample, expected_pid: u32, point: [i32; 2], now: f64) -> bool {
    let age = now - sample.received;
    (0.15..=0.35).contains(&age)
        && sample.pid == expected_pid
        && sample.active
        && sample.top_hit
        && sample.cursor == point
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(identity: &str, row_pid: u32, filename: &str, selected: bool) -> AccessibleRow {
        let mut row_states = vec!["showing".into(), "sensitive".into()];
        if selected {
            row_states.push("selected".into());
        }
        AccessibleRow {
            role: "table row".into(),
            identity: identity.into(),
            pid: row_pid,
            states: row_states,
            descendants: vec![AccessibleCell {
                role: "label".into(),
                name: filename.into(),
                text: None,
                pid: row_pid,
                states: vec!["showing".into(), "sensitive".into()],
            }],
        }
    }

    #[test]
    fn chooser_requires_exact_visible_same_pid_selected_cell_and_unique_identity() {
        assert_eq!(
            exact_selected_row_records(
                &[row("tree:2", 41, "settings.json", true)],
                "settings.json",
                41,
                true
            )
            .len(),
            1
        );
        assert!(exact_selected_row_records(
            &[row("tree:2", 42, "settings.json", true)],
            "settings.json",
            41,
            true
        )
        .is_empty());
        assert!(exact_selected_row_records(
            &[row("tree:2", 41, "settings.json.bak", true)],
            "settings.json",
            41,
            true
        )
        .is_empty());
        assert!(exact_selected_row_records(
            &[row("tree:2", 41, "settings.json", false)],
            "settings.json",
            41,
            true
        )
        .is_empty());
        assert!(exact_selected_row_records(
            &[
                row("tree:2", 41, "settings.json", true),
                row("tree:2", 41, "settings.json", true)
            ],
            "settings.json",
            41,
            true
        )
        .is_empty());
    }

    #[test]
    fn guarded_input_requires_fresh_exact_topmost_target_and_cursor() {
        let sample = GuardSample {
            pid: 41,
            active: true,
            top_hit: true,
            cursor: [10, 20],
            received: 9.8,
        };
        assert!(guarded_target(sample, 41, [10, 20], 10.0));
        assert!(!guarded_target(
            GuardSample {
                received: 9.0,
                ..sample
            },
            41,
            [10, 20],
            10.0
        ));
        assert!(!guarded_target(
            GuardSample {
                top_hit: false,
                ..sample
            },
            41,
            [10, 20],
            10.0
        ));
        assert!(!guarded_target(
            GuardSample { pid: 42, ..sample },
            41,
            [10, 20],
            10.0
        ));
    }

    #[test]
    fn window_bounds_are_half_open_and_reject_invalid_geometry() {
        assert!(target_window_contains([100, 200, 80, 60], 100, 200));
        assert!(target_window_contains([100, 200, 80, 60], 179, 259));
        assert!(!target_window_contains([100, 200, 80, 60], 180, 260));
        assert!(!target_window_contains([0, 0, 0, 20], 0, 1));
    }
}
