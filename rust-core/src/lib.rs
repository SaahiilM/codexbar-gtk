//! Rust implementation of CodexBar's business logic.
//!
//! Migration is intentionally incremental: Python remains the production path
//! until each Rust module has parity tests and an explicit integration step.

pub mod activity;
pub mod formatting;
pub mod history;
pub mod pace;
pub mod providers;
