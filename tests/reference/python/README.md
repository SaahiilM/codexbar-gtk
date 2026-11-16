# Archived Python implementation and assertion reference

This is a transitional review archive, not a completed Python cleanup and not
an application search path, package, installer input, CI test root, or rollback
path. Roll back with a verified native Git commit/tag or preserved native
artifact and the ownership-aware native installer. Keep the archive until root
has reviewed the full assertion map and both Python execution modes on the
coverage peer branch.

`legacy/codexbar_gtk/` contains the former application and PyO3 adapter.
`legacy/test_*.py` contains the former application/parity tests. Shared
synthetic fixtures used by native Rust tests remain in `tests/fixtures/`.
The eight support-retired preview/GTK smoke tools are intentionally absent:
`preview.py`, `preview_b09_synthetic.py`, `preview_b10_controller.py`,
`preview_currency.py`, `preview_notifications.py`, `gtk_smoke_b13_settings.py`,
`gtk_smoke_b13_spend_tray.py`, and `gtk_smoke_b13b2_actions.py`. Their Git
history remains available; do not re-archive them.

## Assertion crosswalk

Native IDs below are Rust test function names, with their source module shown.
They identify coverage that exists; they do not imply every assertion in a
large archived Python module has a native equivalent. Assertions that exercise
the removed Python wrapper or PyO3 transport are classified as
**legacy-wrapper-only / retired**. Product-policy or UI behavior without a
listed native ID remains a coverage gap. Do not use aggregate test counts as a
substitute for this mapping.

| Archived file | Existing native coverage IDs | Disposition and remaining scope |
| --- | --- | --- |
| `test_app.py` | The full method-level crosswalk is `rust-backend/tests/legacy_assertion_map.md` at validated peer commit `cb0d2ba6ba9812433fd16e0a6fdebfe3280a715e` (based on `e7973fa`); representative current IDs are listed in that map, including provider/domain/spend/format/history/notification/ordering/pace tests and GTK metadata/dashboard tests. | That peer removes 26 methods after explicit edge-case equivalence mapping; it is not imported into this branch. Root accepts Rust's rejection of a nonexistent configured CLI path as intentional stricter validation. The old missing-binary Python exception itself is wrapper-only; native spawn failure and first-refresh readiness are covered by controller `missing_cli_fails_first_refresh_immediately_with_typed_process_error`. Display-ready/no-sleep is covered by GTK lifecycle `immediate_display_readiness_does_not_sleep`; callback exception behavior remains wrapper-only and injected monotonic deadline cadence has no native assertion. |
| `test_b10_controller_parity.py` | Controller `starts_immediately_publishes_tray_and_typed_events_and_records_history`, `cli_usage_refresh_publishes_safe_claude_warning_and_both_quotas`; native backend `headless_backend_cli_http_pty_events_cancellation_and_join` | The two Python wrapper/PyO3 serialization assertions are legacy-wrapper-only / retired. Native runtime behavior has separate Rust coverage; no assertion-count equivalence is claimed. |
| `test_claudeplatform_login.py` | `claudeplatform_login::tests::exact_argv_stdin_eof_and_sanitized_success`, `nonzero_malformed_and_trailing_json_fail_closed`, `rejects_multiline_and_oversized_input_before_spawn`, `timeout_cancels_and_reaps_child_group`, `explicit_cancel_kills_and_joins_the_process_group` | Mapped to native process/response/cancellation contracts. |
| `test_cli_service.py` | Integration `python_cli_service_assertions_match_rust_service_contract`; unit `command_uses_argv_boundaries_and_returns_both_streams_and_status`, `timeout_kills_and_reaps_child_with_sanitized_error`, `command_methods_preserve_envelopes_and_invalid_json_is_safe` | Mapped Rust service contract coverage. Python adapter invocation itself is legacy-wrapper-only / retired. |
| `test_provider_icons.py` | `icons::tests::provider_artwork_prefers_decodable_brand_then_monochrome_then_label`, `embedded_catalog_has_python_aliases_and_provider_fallback_assets`; integration `provider_artwork_decodes_outside_repository_cwd_and_keeps_textual_fallback` | Catalog/fallback coverage is native. Retain the three ignored positive GTK checks and keep the negative missing-loader precondition separate. |
| `test_python_settings_facade.py` | Settings `settings_actor_rejects_invalid_imported_cli_path_without_commit_or_swap`, `cli_reconfigure_rejects_invalid_path_without_persisting_or_swapping`, `cli_reconfigure_keeps_inflight_old_config_and_uses_new_argv_timezone_after_commit`, `hooks_plugins_and_provider_actions_return_owned_typed_values`, `launch_at_login_updates_desktop_entry_and_shared_preferences` | At validated peer head `cb0d2ba6ba9812433fd16e0a6fdebfe3280a715e`, the parity/action method has explicit native facade coverage and is retired; the second method remains mapped to reconfigure/error contracts. Root accepts the Rust nonexistent-path rejection as intentional stricter validation. The Python compatibility facade itself is legacy-wrapper-only / retired. |
| `test_rust_activity_integration.py` | Core `activity::tests::activity_levels_use_strict_quartile_thresholds`, `weekly_and_cumulative_totals_clamp_negative_values`, `daily_series_fills_known_gaps_and_preserves_unknown_days`, `daily_series_obeys_coverage_and_requested_range`, `token_heatmap_strict_thresholds_and_sunday_week_edges_are_stable`, `token_heatmap_accepts_python_iso_calendar_date_shapes`; controller `history_records_known_zero_but_skips_unknown_and_placeholder_windows` | Python-to-PyO3 adapter forwarding and backend-selector wrapper are legacy-wrapper-only / retired; underlying Rust behavior remains covered. |
| `test_rust_application_actions_integration.py` | Backend `application` tests `failed_systemd_spawn_falls_back_to_current_executable_and_argv`, `systemd_and_fallback_spawn_failure_is_a_static_restart_error`, `codex_terminal_login_missing_cli_is_static_and_sanitized`, `codex_terminal_spawn_failure_has_no_path_or_process_output`; GTK routing tests in `rust-gtk/src/lib.rs` | PyO3 facade transport/restart-context comparison is legacy-wrapper-only / retired. Native actions and launch routing have separate Rust tests. |
| `test_rust_catalog_parity.py` | Core `providers::tests::catalog_is_sorted_and_all_ids_resolve`, `aliases_resolve_to_canonical_metadata`, `v084_provider_descriptor_details_match_the_tagged_contract`, `returns_expected_names_colors_and_unknown_fallbacks`; `currency::tests::catalog_labels_and_order_match_python` | Python-to-Rust catalog comparison harness and adapter are legacy-wrapper-only / retired. Native catalog assertions remain; no parity assertion-count equivalence is claimed. |
| `test_rust_charts_integration.py` | Core `charts::tests::uses_elapsed_time_and_a_fixed_quota_axis`, `filters_invalid_samples_and_clamps_usage`, `falls_back_to_sample_indices_for_nonpositive_duration`; GTK dashboard chart projection tests | Python adapter dispatch and randomized Python-reference comparison are legacy-wrapper-only / retired. Native geometry coverage does not assert the removed adapter call path. |
| `test_rust_currency_integration.py` | `currency::tests::cache_loaded_and_stale_detection_injected_time`, `offline_refresh_retains_cached_rates`, `injected_http_refresh_is_single_flight_and_persists_live_rates`; GTK `unsupported_currency_falls_back_to_source_currency` | Python shared-converter facade is legacy-wrapper-only / retired. Native cache/network/conversion policy has Rust coverage. |
| `test_rust_domain_integration.py` | Core `domain::tests::standard_window_payload_normalization_preserves_unknown_and_zero`, `provider_context_normalization_preserves_credits_status_error_plan`, `detail_section_normalization_preserves_rows_and_chart`, `spend_aggregation_preserves_totals_tokens_and_coverage`, `spend_aggregation_totals_not_double_counted`; controller `spend_counter_overflow_is_clear_and_retains_the_last_spend`, `usage_window_overflow_is_clear_and_retains_the_last_snapshot`; GTK dashboard unknown/known-zero tests | Python adapter projection is legacy-wrapper-only / retired. Named native DTO/domain contracts remain; no total assertion equivalence is claimed. |
| `test_rust_format_integration.py` | Core `formatting::tests::formats_labels_percentages_and_token_scales`, `matches_currency_and_credit_rounding`, `formats_reset_credits_and_pace`, `calculates_workday_progress_and_reset_projection` | Python formatting-adapter calls and non-UTC Python-only input characterization are legacy-wrapper-only / retired. |
| `test_rust_history_integration.py` | Core `history::tests::appends_json_lines_and_queries_sorted_series`, `skips_blank_and_malformed_records_and_caches_reads`, `concurrent_writes_reads_and_prunes_keep_retained_samples`, `prune_keeps_samples_on_or_after_the_retention_cutoff`; controller `history_records_known_zero_but_skips_unknown_and_placeholder_windows` | Python facade selection/path reconfiguration and adapter forwarding are legacy-wrapper-only / retired. Native storage format and retention are covered; not every Python filesystem failure assertion is mapped. |
| `test_rust_login_integration.py` | Backend `login::tests::terminal_argv_preserves_arguments_and_gnome_separator`, `fake_pty_login_streams_prompt_and_reaps_successful_child`, `login_actor_keeps_auth_output_out_of_frontend_events`, `login_actor_shutdown_cancels_and_reaps_active_pty_child`, `fake_pty_timeout_kills_process_group_descendants`, `fake_pty_cancel_kills_process_group_descendants`; end-to-end `headless_backend_cli_http_pty_events_cancellation_and_join` | Python facade handle/event conversion is legacy-wrapper-only / retired. |
| `test_rust_notifications_integration.py` | Core `notifications::tests::emits_all_policy_kinds_once_and_preserves_threshold_rearm`, `disabled_exhaustion_still_tracks_and_disappearance_rearms_it`, `pace_cycle_tolerates_small_reset_corrections_but_rearms_on_new_cycle`; controller `cli_usage_refresh_publishes_safe_claude_warning_and_both_quotas` | Python adapter DTO projection is legacy-wrapper-only / retired. |
| `test_rust_ordering_integration.py` | Core `ordering::tests::visibility_hides_and_sorts_with_stable_unspecified_order`, `selection_prefers_depleted_and_keeps_exact_ties_stable`, `selection_uses_only_trusted_eta_then_usage_and_excludes_placeholders`, `selection_skips_error_placeholder_and_unknown_but_keeps_known_zero_indices`, `selection_returns_none_when_every_provider_or_window_is_ineligible`; backend `presentation::tests::automatic_selection_resolves_original_indices_and_validates_identity` | Python adapter result conversion is legacy-wrapper-only / retired. |
| `test_rust_pace_integration.py` | Core `pace::tests::recognizes_only_month_long_windows`, `daily_targets_count_today_and_skip_midnight_reset_day`, `formats_percent_credit_request_and_currency_units`, `currency_conversion_uses_the_converted_amount_when_available`, `monthly_window_targets_respect_quota_metadata_and_validity`, `monthly_cost_targets_require_a_known_monthly_cap` | PyO3 helper forwarding is legacy-wrapper-only / retired. |
| `test_rust_preferences_integration.py` | Core `preferences::tests::loads_only_known_keys_over_defaults`, `updates_resets_and_exports_portable_documents`, `imports_known_portable_keys_and_ignores_unknown_keys`, `refresh_interval_mapping_matches_python`; backend settings `settings_actor_import_and_reset_persistence_failures_leave_memory_and_cli_unchanged`, `reset_rebuilds_the_startup_default_cli_and_keeps_autostart_file_untouched` | Python preference facade and backend-selection adapter assertions are legacy-wrapper-only / retired. |
| `test_rust_presentation_integration.py` | Backend `presentation::tests::absent_and_empty_spend_are_distinct_and_errors_are_typed`, `known_zero_unknown_partial_and_coverage_are_preserved`, `selected_chart_range_and_full_heatmap_keep_unknown_distinct_from_zero`, `sessions_projection_exposes_sticky_scan_status_and_retained_rows`, `automatic_selection_resolves_original_indices_and_validates_identity`; GTK `dashboard::tests::loading_empty_and_retained_failure_are_distinct` | Python presentation-facade projection is legacy-wrapper-only / retired. Backend DTO coverage does not claim 1:1 GTK interaction. |
| `test_rust_provider_integration.py` | Core `providers::tests::catalog_is_sorted_and_all_ids_resolve`, `aliases_resolve_to_canonical_metadata`, `returns_expected_names_colors_and_unknown_fallbacks`, `unicode_unknown_provider_titles_use_titlecase_expansions`; GTK `icons::tests::embedded_catalog_has_python_aliases_and_provider_fallback_assets` | PyO3 adapter/provider-selection assertions are legacy-wrapper-only / retired. |
| `test_rust_settings_integration.py` | Backend settings `checked_settings_reads_reject_valid_looking_json_on_nonzero_exit`, `timeout_and_partial_read_failure_keep_successful_settings_sections`, `hooks_plugins_and_provider_actions_return_owned_typed_values`, `settings_actor_rejects_invalid_imported_cli_path_without_commit_or_swap`, `cli_reconfigure_keeps_inflight_old_config_and_uses_new_argv_timezone_after_commit`; native GTK Settings smoke and private-Weston jobs | Python facade API result conversion is legacy-wrapper-only / retired. Selected native settings behavior is covered; global UI acceptance remains open. |
| `test_tray_signals.py` | Native `tray-dbus` test `tray::tests::private_bus_exports_protocol_dispatches_actions_recovers_and_releases`; GTK panel smoke `scripts/smoke-native-panel-parity.sh` | The Python D-Bus signal wrapper tests are archived. Native protocol and panel/window semantics have separate CI coverage. |

### Readiness and known gaps

The missing-binary Rust regression is
`rust_backend::controller::tests::missing_cli_fails_first_refresh_immediately_with_typed_process_error`;
it checks the `NotFound` spawn category, sanitized `Process/cli_usage` state,
no initial polling delay, and no fabricated snapshot. GTK lifecycle
`immediate_display_readiness_does_not_sleep` verifies a ready-on-first-check
path performs one check and no sleep. The existing
`starts_immediately_publishes_tray_and_typed_events_and_records_history` test
independently checks immediate successful startup. Callback exception
handling remains Python-wrapper-only because the Rust callback is
non-fallible. No panic-catching behavior is added.

CI retains the ignored positive GTK checks for provider artwork decode,
accessibility/fallback roles, rendered dashboard warning/quota content, and the
empty-dashboard Settings action. The negative SVG-loader test has a distinct
unmet-precondition contract: run it only where `librsvg2-common` is absent; a
successful SVG decode means its negative precondition is unmet, not a pass.

The coverage peer completed both modes on clean head
`cb0d2ba6ba9812433fd16e0a6fdebfe3280a715e` atop `e7973fa`: default Python had
318 tests and 22 expected skips; `CODEXBAR_RUST_CORE=1` had 318 tests and no
skips. Its atomic extension build, Rust core/backend tests, formatting and
strict Clippy passed. This clears the two-mode prerequisite only; the peer
commit is not included here and this candidate did not run those Python modes.
It does not map every other archived file or pass UG/C gates. Native test counts
are not presented as a replacement for the larger historical Python assertion
inventory. Keep this package until root completes archive-wide coverage review.
