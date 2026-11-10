//! Pure sparkline geometry, ported from `codexbar_gtk/charts.py`.

/// Keep a fixed 0–100% axis and space samples by elapsed time.
pub fn sparkline_coordinates(points: &[(f64, f64)], width: f64, height: f64) -> Vec<(f64, f64)> {
    if width <= 1.0 || height <= 4.0 {
        return Vec::new();
    }
    let valid: Vec<_> = points
        .iter()
        .filter(|(timestamp, value)| timestamp.is_finite() && value.is_finite())
        .map(|&(timestamp, value)| (timestamp, value.clamp(0.0, 100.0)))
        .collect();
    if valid.len() < 2 {
        return Vec::new();
    }
    let first = valid[0].0;
    let duration = valid.last().unwrap().0 - first;
    let use_indices = duration <= 0.0;
    let duration = if use_indices {
        (valid.len() - 1) as f64
    } else {
        duration
    };
    valid
        .iter()
        .enumerate()
        .map(|(index, &(timestamp, value))| {
            let elapsed = if use_indices {
                index as f64
            } else {
                timestamp - first
            };
            (
                (elapsed / duration) * (width - 1.0),
                (height - 2.0) - (value / 100.0) * (height - 4.0),
            )
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uses_elapsed_time_and_a_fixed_quota_axis() {
        assert_eq!(
            sparkline_coordinates(&[(0.0, 0.0), (1.0, 10.0), (10.0, 100.0)], 101.0, 24.0),
            [(0.0, 22.0), (10.0, 20.0), (100.0, 2.0)]
        );
    }

    #[test]
    fn filters_invalid_samples_and_clamps_usage() {
        assert_eq!(
            sparkline_coordinates(&[(0.0, -10.0), (1.0, f64::NAN), (2.0, 120.0)], 101.0, 24.0,),
            [(0.0, 22.0), (100.0, 2.0)]
        );
        assert!(sparkline_coordinates(&[(0.0, 10.0)], 101.0, 24.0).is_empty());
        assert!(sparkline_coordinates(&[(0.0, 0.0), (1.0, 10.0)], 1.0, 24.0).is_empty());
        assert!(sparkline_coordinates(&[(0.0, 0.0), (1.0, 10.0)], 101.0, 4.0).is_empty());
    }

    #[test]
    fn falls_back_to_sample_indices_for_nonpositive_duration() {
        for times in [[3.0, 3.0, 3.0], [3.0, 2.0, 1.0]] {
            let samples: Vec<_> = times.into_iter().map(|time| (time, 50.0)).collect();
            assert_eq!(
                sparkline_coordinates(&samples, 101.0, 24.0),
                [(0.0, 12.0), (50.0, 12.0), (100.0, 12.0)]
            );
        }
    }
}
