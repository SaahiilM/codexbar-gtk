# Rust core changelog

The Rust core is versioned independently from the GTK application. Every merged
Rust migration PR bumps the package version in `Cargo.toml` and `Cargo.lock` and
records its changes here.

## 0.1.0 — 2026-10-28

- Establish the parallel Rust business-logic crate and CI checks.
- Port formatting, quota-window labels, reset-credit summaries, pace text,
  workday progress, and reset usage projections from `codexbar_gtk/format.py`.
- Keep Python as the production implementation; no service callers are switched.
