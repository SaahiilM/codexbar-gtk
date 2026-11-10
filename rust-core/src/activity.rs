//! Pure helpers ported from `codexbar_gtk/activity.py`.

use chrono::{Datelike, Duration, NaiveDate};
use serde::Serialize;
use std::collections::{HashMap, HashSet};

pub const WEEK_COUNT: usize = 53;
pub const DAY_COUNT: usize = 7;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivityError {
    Overflow,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DailyCostEntry {
    /// ISO date text from the CLI; only the leading `YYYY-MM-DD` is used.
    pub date: String,
    /// `None` represents an unpriced or malformed cost value.
    pub total_cost: Option<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DailyActivity {
    pub date: NaiveDate,
    /// Unknown (`None`) differs from an observed zero-cost day (`Some(0.0)`).
    pub cost: Option<f64>,
}

/// One provider contribution to a date-bucketed token heatmap.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DailyTokenEntry {
    /// ISO date text from a provider's spend history row.
    pub date: String,
    /// An explicit usable count; missing, malformed and negative values are
    /// represented as `None` so they remain unknown instead of becoming zero.
    pub total_tokens: Option<i64>,
}

/// Known subtotal and whether the value omits one or more unknown inputs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct TokenActivityValue {
    /// `None` is unknown; `Some(0)` is an explicit known zero.
    pub tokens: Option<i64>,
    pub partial: bool,
}

/// A day in the Sunday-aligned heatmap window.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TokenActivityDay {
    pub date: NaiveDate,
    pub visible: bool,
    pub value: TokenActivityValue,
}

/// Frontend-neutral 53-week token activity projection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TokenHeatmap {
    pub start: NaiveDate,
    pub today: NaiveDate,
    pub days: Vec<TokenActivityDay>,
    pub weeks: Vec<TokenActivityValue>,
    pub cumulative: Vec<TokenActivityValue>,
    /// `None` is unknown, `Some(0)` is known zero, and levels 1–4 are activity.
    pub daily_levels: Vec<Option<u8>>,
    pub weekly_levels: Vec<Option<u8>>,
    pub cumulative_levels: Vec<Option<u8>>,
}

/// Bucket values into the five heatmap levels (empty plus four shades).
pub fn activity_levels(values: &[i64]) -> Vec<u8> {
    let peak = values.iter().copied().max().unwrap_or(0);
    values
        .iter()
        .map(|value| {
            if *value <= 0 || peak <= 0 {
                0
            } else {
                let ratio = *value as f64 / peak as f64;
                if ratio > 0.75 {
                    4
                } else if ratio > 0.5 {
                    3
                } else if ratio > 0.25 {
                    2
                } else {
                    1
                }
            }
        })
        .collect()
}

/// Sum each Sunday-aligned week, matching the 53-week heatmap window.
pub fn weekly_totals(
    start: NaiveDate,
    values: &HashMap<NaiveDate, i64>,
    today: NaiveDate,
) -> Result<Vec<i64>, ActivityError> {
    (0..WEEK_COUNT)
        .map(|week| {
            (0..DAY_COUNT)
                .map(|day| {
                    let offset = (week * DAY_COUNT + day) as i64;
                    let current = start + Duration::days(offset);
                    if current > today {
                        0
                    } else {
                        values.get(&current).copied().unwrap_or(0).max(0)
                    }
                })
                .try_fold(0_i64, |total, value| {
                    total.checked_add(value).ok_or(ActivityError::Overflow)
                })
        })
        .collect()
}

/// Running total per week, ignoring negative values.
pub fn cumulative_totals(values: &[i64]) -> Result<Vec<i64>, ActivityError> {
    let mut total = 0_i64;
    values
        .iter()
        .map(|value| {
            total = total
                .checked_add((*value).max(0))
                .ok_or(ActivityError::Overflow)?;
            Ok(total)
        })
        .collect()
}

/// Build a daily spend series, preserving missing and explicitly unknown days.
pub fn daily_series(
    entries: &[DailyCostEntry],
    days: Option<i64>,
    history_coverage_established: bool,
) -> Vec<DailyActivity> {
    let mut totals: HashMap<NaiveDate, f64> = HashMap::new();
    let mut unknown: HashSet<NaiveDate> = HashSet::new();

    for entry in entries {
        let date_text = &entry.date;
        let parsed_date = date_text
            .get(..10)
            .and_then(|prefix| {
                NaiveDate::parse_from_str(prefix, "%Y-%m-%d")
                    .or_else(|_| NaiveDate::parse_from_str(prefix, "%G-W%V-%u"))
                    .ok()
            })
            .or_else(|| {
                date_text.get(..8).and_then(|prefix| {
                    NaiveDate::parse_from_str(prefix, "%Y%m%d")
                        .or_else(|_| NaiveDate::parse_from_str(prefix, "%GW%V%u"))
                        .ok()
                })
            })
            .or_else(|| {
                NaiveDate::parse_from_str(date_text, "%Y-%m-%d")
                    .or_else(|_| NaiveDate::parse_from_str(date_text, "%G-W%V-%u"))
                    .or_else(|_| NaiveDate::parse_from_str(date_text, "%Y%m%d"))
                    .or_else(|_| NaiveDate::parse_from_str(date_text, "%GW%V%u"))
                    .ok()
            });
        let Some(date) = parsed_date else {
            continue;
        };
        match entry.total_cost {
            Some(cost) if cost.is_finite() && cost >= 0.0 => {
                *totals.entry(date).or_default() += cost;
            }
            _ => {
                unknown.insert(date);
            }
        }
    }

    if totals.is_empty() && unknown.is_empty() {
        return Vec::new();
    }

    let first_observed = totals
        .keys()
        .chain(unknown.iter())
        .min()
        .copied()
        .expect("at least one observed date");
    let last = totals
        .keys()
        .chain(unknown.iter())
        .max()
        .copied()
        .expect("at least one observed date");
    let first = match days {
        None => first_observed,
        Some(days) => {
            let span = days.max(1) - 1;
            first_observed.max(last - Duration::days(span))
        }
    };

    let count = (last - first).num_days() as usize + 1;
    (0..count)
        .map(|offset| {
            let date = first + Duration::days(offset as i64);
            let cost = if unknown.contains(&date)
                || (!totals.contains_key(&date) && !history_coverage_established)
            {
                None
            } else {
                Some(totals.get(&date).copied().unwrap_or(0.0))
            };
            DailyActivity { date, cost }
        })
        .collect()
}

/// First Sunday of the one-year window ending on `today`.
pub fn align_start(today: NaiveDate) -> NaiveDate {
    let first = today - Duration::days(364);
    first - Duration::days(first.weekday().num_days_from_sunday() as i64)
}

/// Bucket duplicate provider rows by date and build the option-aware token
/// heatmap. Cost-history coverage is deliberately not an input: it establishes
/// cost gaps only, not token-count coverage.
pub fn token_heatmap(entries: &[DailyTokenEntry], today: NaiveDate) -> TokenHeatmap {
    #[derive(Default)]
    struct Bucket {
        subtotal: i64,
        known: bool,
        partial: bool,
    }

    let mut buckets = HashMap::<NaiveDate, Bucket>::new();
    for entry in entries {
        let Some(date) = parse_heatmap_date(&entry.date) else {
            continue;
        };
        let bucket = buckets.entry(date).or_default();
        match entry.total_tokens.filter(|value| *value >= 0) {
            Some(count) => {
                bucket.known = true;
                if let Some(total) = bucket.subtotal.checked_add(count) {
                    bucket.subtotal = total;
                } else {
                    // Preserve the known subtotal and make the loss explicit.
                    bucket.partial = true;
                }
            }
            None => bucket.partial = true,
        }
    }

    let start = align_start(today);
    let first_visible = today - Duration::days(364);
    let days = (0..WEEK_COUNT * DAY_COUNT)
        .map(|index| {
            let date = start + Duration::days(index as i64);
            let visible = date >= first_visible && date <= today;
            let bucket = buckets.get(&date);
            let value = if visible {
                TokenActivityValue {
                    tokens: bucket
                        .filter(|bucket| bucket.known)
                        .map(|bucket| bucket.subtotal),
                    partial: bucket.is_some_and(|bucket| bucket.partial),
                }
            } else {
                TokenActivityValue {
                    tokens: None,
                    partial: false,
                }
            };
            TokenActivityDay {
                date,
                visible,
                value,
            }
        })
        .collect::<Vec<_>>();

    let mut weeks = Vec::with_capacity(WEEK_COUNT);
    let mut cumulative = Vec::with_capacity(WEEK_COUNT);
    let mut running_total = 0_i64;
    let mut running_known = false;
    let mut running_partial = false;
    for week in 0..WEEK_COUNT {
        let mut subtotal = 0_i64;
        let mut known = false;
        let mut partial = false;
        for day in &days[week * DAY_COUNT..(week + 1) * DAY_COUNT] {
            if !day.visible {
                continue;
            }
            match day.value.tokens {
                Some(tokens) => {
                    known = true;
                    if let Some(total) = subtotal.checked_add(tokens) {
                        subtotal = total;
                    } else {
                        partial = true;
                    }
                }
                None => partial = true,
            }
            partial |= day.value.partial;
        }
        let week_value = TokenActivityValue {
            tokens: known.then_some(subtotal),
            partial,
        };
        weeks.push(week_value);

        if week_value.tokens.is_some() {
            running_known = true;
            if let Some(total) = running_total.checked_add(week_value.tokens.unwrap_or_default()) {
                running_total = total;
            } else {
                running_partial = true;
            }
        }
        running_partial |= week_value.partial;
        cumulative.push(TokenActivityValue {
            tokens: running_known.then_some(running_total),
            partial: running_partial,
        });
    }

    let daily_values = days.iter().map(|day| day.value).collect::<Vec<_>>();
    TokenHeatmap {
        start,
        today,
        daily_levels: token_activity_levels(&daily_values),
        weekly_levels: token_activity_levels(&weeks),
        cumulative_levels: token_activity_levels(&cumulative),
        days,
        weeks,
        cumulative,
    }
}

fn token_activity_levels(values: &[TokenActivityValue]) -> Vec<Option<u8>> {
    let peak = values
        .iter()
        .filter_map(|value| value.tokens)
        .max()
        .unwrap_or(0);
    values
        .iter()
        .map(|value| {
            let tokens = value.tokens?;
            Some(if tokens <= 0 || peak <= 0 {
                0
            } else {
                let ratio = tokens as f64 / peak as f64;
                if ratio > 0.75 {
                    4
                } else if ratio > 0.5 {
                    3
                } else if ratio > 0.25 {
                    2
                } else {
                    1
                }
            })
        })
        .collect()
}

fn parse_heatmap_date(value: &str) -> Option<NaiveDate> {
    let prefix = value.get(..10).unwrap_or(value);
    NaiveDate::parse_from_str(prefix, "%Y-%m-%d")
        .or_else(|_| NaiveDate::parse_from_str(prefix, "%G-W%V-%u"))
        .ok()
        .or_else(|| {
            value.get(..8).and_then(|prefix| {
                NaiveDate::parse_from_str(prefix, "%Y%m%d")
                    .or_else(|_| NaiveDate::parse_from_str(prefix, "%GW%V%u"))
                    .ok()
            })
        })
        .or_else(|| {
            NaiveDate::parse_from_str(value, "%Y-%m-%d")
                .or_else(|_| NaiveDate::parse_from_str(value, "%G-W%V-%u"))
                .or_else(|_| NaiveDate::parse_from_str(value, "%Y%m%d"))
                .or_else(|_| NaiveDate::parse_from_str(value, "%GW%V%u"))
                .ok()
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    fn date(value: &str) -> NaiveDate {
        NaiveDate::parse_from_str(value, "%Y-%m-%d").unwrap()
    }

    fn entry(date: &str, total_cost: Option<f64>) -> DailyCostEntry {
        DailyCostEntry {
            date: date.into(),
            total_cost,
        }
    }

    #[test]
    fn activity_levels_use_strict_quartile_thresholds() {
        assert_eq!(
            activity_levels(&[0, 1, 25, 50, 75, 100, -4]),
            [0, 1, 1, 2, 3, 4, 0]
        );
        assert_eq!(activity_levels(&[-3, 0]), [0, 0]);
        assert!(activity_levels(&[]).is_empty());
    }

    #[test]
    fn weekly_and_cumulative_totals_clamp_negative_values() {
        let start = date("2026-10-18"); // Sunday
        let today = start + Duration::days(9);
        let values = HashMap::from([
            (start, 3),
            (start + Duration::days(1), -2),
            (start + Duration::days(2), 5),
            (start + Duration::days(7), 4),
            (start + Duration::days(10), 99), // future relative to today
        ]);
        let weekly = weekly_totals(start, &values, today).unwrap();
        assert_eq!(weekly.len(), WEEK_COUNT);
        assert_eq!(weekly[0], 8);
        assert_eq!(weekly[1], 4);
        assert_eq!(cumulative_totals(&[3, -2, 5, 4]).unwrap(), [3, 3, 8, 12]);
    }

    #[test]
    fn weekly_and_cumulative_totals_report_i64_overflow() {
        let start = date("2026-10-18");
        let values = HashMap::from([(start, i64::MAX), (start + Duration::days(1), i64::MAX)]);
        assert!(weekly_totals(start, &values, start + Duration::days(1)).is_err());
        assert!(cumulative_totals(&[i64::MAX, i64::MAX]).is_err());
    }

    #[test]
    fn daily_series_fills_known_gaps_and_preserves_unknown_days() {
        let entries = [
            entry("2026-10-20", Some(2.5)),
            entry("2026-10-20T12:00:00Z", Some(1.5)),
            entry("2026-10-22", None),
            entry("2026-10-23", Some(f64::NAN)),
            entry("not-a-date", Some(8.0)),
        ];
        let series = daily_series(&entries, Some(30), true);
        assert_eq!(series.len(), 4);
        assert_eq!(
            series[0],
            DailyActivity {
                date: date("2026-10-20"),
                cost: Some(4.0)
            }
        );
        assert_eq!(
            series[1],
            DailyActivity {
                date: date("2026-10-21"),
                cost: Some(0.0)
            }
        );
        assert_eq!(
            series[2],
            DailyActivity {
                date: date("2026-10-22"),
                cost: None
            }
        );
        assert_eq!(
            series[3],
            DailyActivity {
                date: date("2026-10-23"),
                cost: None
            }
        );
    }

    #[test]
    fn token_heatmap_sums_duplicate_dates_and_keeps_unknown_separate_from_zero() {
        let today = date("2026-10-24");
        let start = align_start(today);
        let heatmap = token_heatmap(
            &[
                DailyTokenEntry {
                    date: "2026-10-18".into(),
                    total_tokens: Some(12),
                },
                DailyTokenEntry {
                    date: "2026-10-18T12:00:00Z".into(),
                    total_tokens: Some(8),
                },
                DailyTokenEntry {
                    date: "2026-10-18".into(),
                    total_tokens: None,
                },
                DailyTokenEntry {
                    date: "2026-10-19".into(),
                    total_tokens: None,
                },
                DailyTokenEntry {
                    date: "2026-10-20".into(),
                    total_tokens: Some(0),
                },
                DailyTokenEntry {
                    date: "2026-10-20".into(),
                    total_tokens: Some(7),
                },
            ],
            today,
        );

        let sunday = (date("2026-10-18") - start).num_days() as usize;
        let monday = sunday + 1;
        let tuesday = sunday + 2;
        let wednesday = sunday + 3;
        let week = sunday / DAY_COUNT;
        assert_eq!(heatmap.days[sunday].value.tokens, Some(20));
        assert!(heatmap.days[sunday].value.partial);
        assert_eq!(heatmap.days[monday].value.tokens, None);
        assert!(heatmap.days[monday].value.partial);
        assert_eq!(heatmap.days[tuesday].value.tokens, Some(7));
        assert!(!heatmap.days[tuesday].value.partial);
        assert_eq!(heatmap.days[wednesday].value.tokens, None);
        assert!(!heatmap.days[wednesday].value.partial);
        assert_eq!(heatmap.weeks[week].tokens, Some(27));
        assert!(heatmap.weeks[week].partial);
        assert_eq!(heatmap.cumulative[week].tokens, Some(27));
        assert!(heatmap.cumulative[week].partial);
        assert_eq!(heatmap.days.len(), WEEK_COUNT * DAY_COUNT);
        assert!(heatmap
            .days
            .iter()
            .any(|day| day.date == today && day.visible));
        assert!(heatmap
            .days
            .iter()
            .all(|day| day.date <= today || !day.visible));
    }

    #[test]
    fn token_heatmap_strict_thresholds_and_sunday_week_edges_are_stable() {
        let today = date("2026-10-24");
        let heatmap = token_heatmap(
            &[
                DailyTokenEntry {
                    date: "2026-10-18".into(),
                    total_tokens: Some(25),
                },
                DailyTokenEntry {
                    date: "2026-10-19".into(),
                    total_tokens: Some(50),
                },
                DailyTokenEntry {
                    date: "2026-10-20".into(),
                    total_tokens: Some(75),
                },
                DailyTokenEntry {
                    date: "2026-10-21".into(),
                    total_tokens: Some(100),
                },
                DailyTokenEntry {
                    date: "2025-10-20".into(),
                    total_tokens: Some(999),
                },
            ],
            today,
        );
        let start = heatmap.start;
        assert_eq!(start.weekday().num_days_from_sunday(), 0);
        let sunday = (date("2026-10-18") - start).num_days() as usize;
        assert_eq!(
            &heatmap.daily_levels[sunday..sunday + 4],
            &[Some(1), Some(2), Some(3), Some(4)]
        );
        let week = sunday / DAY_COUNT;
        assert_eq!(heatmap.weeks[week].tokens, Some(250));
        assert_eq!(heatmap.weekly_levels[week], Some(4));
        assert!(!heatmap.days[0].visible);
        assert!(heatmap
            .days
            .iter()
            .any(|day| day.date == date("2025-10-20") && !day.visible));
        assert!(heatmap
            .days
            .iter()
            .any(|day| day.date == today && day.visible));
    }

    #[test]
    fn token_heatmap_accepts_python_iso_calendar_date_shapes() {
        let today = date("2026-10-24");
        let basic = DailyTokenEntry {
            date: "20261022".into(),
            total_tokens: Some(3),
        };
        let week_date = DailyTokenEntry {
            date: "2026-W43-6".into(),
            total_tokens: Some(4),
        };
        let heatmap = token_heatmap(&[basic, week_date], today);
        let at = |date: NaiveDate| (date - heatmap.start).num_days() as usize;
        assert_eq!(heatmap.days[at(date("2026-10-22"))].value.tokens, Some(3));
        assert_eq!(heatmap.days[at(today)].value.tokens, Some(4));
    }

    #[test]
    fn daily_series_obeys_coverage_and_requested_range() {
        let entries = [
            entry("2026-10-01", Some(1.0)),
            entry("2026-10-10", Some(2.0)),
        ];
        let series = daily_series(&entries, Some(3), false);
        assert_eq!(series.len(), 3);
        assert_eq!(
            series[0],
            DailyActivity {
                date: date("2026-10-08"),
                cost: None
            }
        );
        assert_eq!(
            series[1],
            DailyActivity {
                date: date("2026-10-09"),
                cost: None
            }
        );
        assert_eq!(
            series[2],
            DailyActivity {
                date: date("2026-10-10"),
                cost: Some(2.0)
            }
        );
        assert_eq!(daily_series(&[], None, true), []);
        assert_eq!(daily_series(&entries, None, true).len(), 10);
    }

    #[test]
    fn aligns_start_to_sunday() {
        let today = date("2026-10-22"); // Thursday
        let start = align_start(today);
        assert_eq!((today - start).num_days() % DAY_COUNT as i64, 4);
        assert_eq!(start.weekday().num_days_from_sunday(), 0);
    }
}
