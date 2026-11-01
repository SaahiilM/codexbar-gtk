//! Native Spend and Sessions pages over backend-owned presentation DTOs.

use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};

use chrono::Datelike;

use codexbar_backend::{
    controller::{ControllerError, ControllerErrorKind},
    presentation::{
        SessionsViewModel, SpendAmount, SpendCount, SpendEntryRow, SpendProviderRow, SpendViewModel,
    },
};
use codexbar_core::{
    activity::{TokenActivityValue, TokenHeatmap, DAY_COUNT, WEEK_COUNT},
    formatting::{format_currency, format_tokens},
};
use gtk::prelude::*;
use libadwaita as adw;

const RANGE_LABELS: [(&str, &str); 4] = [
    ("7 days", "7 days"),
    ("30 days", "30 days"),
    ("90 days", "90 days"),
    ("All", "All"),
];

pub struct SpendView {
    pub root: gtk::Box,
    status: gtk::Label,
    spinner: gtk::Spinner,
    error: gtk::Label,
    loading: gtk::Label,
    empty: gtk::Label,
    metrics: [gtk::Label; 4],
    metric_details: [gtk::Label; 4],
    range_buttons: [gtk::ToggleButton; 4],
    suppress_range_action: Rc<Cell<bool>>,
    heatmap: HeatmapView,
    chart: DailySpendChart,
    providers: gtk::Box,
    projects: gtk::Box,
    models: gtk::Box,
}

impl SpendView {
    pub fn new(application: &adw::Application, selected_range: &str) -> Self {
        let root = gtk::Box::new(gtk::Orientation::Vertical, 0);
        root.append(&page_header(
            application,
            "Usage & Spend",
            "Local cost and token history",
        ));

        let scroller = gtk::ScrolledWindow::new();
        scroller.set_vexpand(true);
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        let clamp = adw::Clamp::new();
        clamp.set_maximum_size(1060);
        clamp.set_tightening_threshold(700);
        clamp.set_margin_top(14);
        clamp.set_margin_bottom(20);
        clamp.set_margin_start(20);
        clamp.set_margin_end(20);
        let content = gtk::Box::new(gtk::Orientation::Vertical, 14);

        let status_row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let spinner = gtk::Spinner::new();
        status_row.append(&spinner);
        let status = text_label("Waiting for local spend data", "dim-label");
        status.set_hexpand(true);
        status.set_xalign(0.0);
        status_row.append(&status);
        status_row.append(&action_button("Refresh", "app.refresh", None));
        content.append(&status_row);

        let error = text_label("", "error");
        error.set_wrap(true);
        error.set_xalign(0.0);
        error.set_visible(false);
        content.append(&error);

        let loading = text_label(
            "The first spend scan is running in the background.",
            "dim-label",
        );
        loading.set_xalign(0.0);
        loading.set_visible(true);
        content.append(&loading);
        let empty = text_label(
            "No local cost activity was returned by the CLI.",
            "dim-label",
        );
        empty.set_xalign(0.0);
        empty.set_wrap(true);
        empty.set_visible(false);
        content.append(&empty);

        let metrics_grid = gtk::Grid::new();
        metrics_grid.set_column_spacing(10);
        metrics_grid.set_row_spacing(10);
        metrics_grid.set_column_homogeneous(true);
        let mut metrics = Vec::new();
        let mut metric_details = Vec::new();
        for (index, title) in ["Total spend", "This session", "Tokens", "Coverage"]
            .into_iter()
            .enumerate()
        {
            let card = gtk::Frame::new(None);
            card.add_css_class("card");
            let body = gtk::Box::new(gtk::Orientation::Vertical, 4);
            body.set_margin_top(10);
            body.set_margin_bottom(10);
            body.set_margin_start(14);
            body.set_margin_end(14);
            let heading = text_label(title, "caption");
            heading.set_xalign(0.0);
            body.append(&heading);
            let value = text_label("—", "title-3");
            value.add_css_class("numeric");
            value.set_xalign(0.0);
            body.append(&value);
            let detail = text_label("", "caption");
            detail.add_css_class("dim-label");
            detail.set_xalign(0.0);
            detail.set_wrap(true);
            body.append(&detail);
            card.set_child(Some(&body));
            metrics_grid.attach(&card, (index % 2) as i32, (index / 2) as i32, 1, 1);
            metrics.push(value);
            metric_details.push(detail);
        }
        content.append(&metrics_grid);

        let range_row = gtk::Box::new(gtk::Orientation::Horizontal, 6);
        let range_title = text_label("Daily spend history", "heading");
        range_title.set_hexpand(true);
        range_title.set_xalign(0.0);
        range_row.append(&range_title);
        let mut range_group: Option<gtk::ToggleButton> = None;
        let suppress_range_action = Rc::new(Cell::new(false));
        let mut range_buttons = Vec::new();
        for (label, value) in RANGE_LABELS {
            let button = gtk::ToggleButton::with_label(label);
            button.add_css_class("flat");
            if let Some(group) = &range_group {
                button.set_group(Some(group));
            } else {
                range_group = Some(button.clone());
            }
            button.set_tooltip_text(Some(&format!("Show {value} of spend history")));
            button.update_property(&[gtk::accessible::Property::Label(&format!(
                "Spend history range: {value}"
            ))]);
            if canonical_range(selected_range) == value {
                button.set_active(true);
            }
            let application = application.clone();
            let suppress = suppress_range_action.clone();
            let range = value.to_owned();
            button.connect_toggled(move |button| {
                if button.is_active() && !suppress.get() {
                    application.activate_action("spend-range", Some(&range.to_variant()));
                }
            });
            range_row.append(&button);
            range_buttons.push(button);
        }
        content.append(&range_row);

        let heatmap = HeatmapView::new();
        content.append(&heatmap.root);

        let chart_title = text_label("Daily cost", "heading");
        chart_title.set_xalign(0.0);
        content.append(&chart_title);
        let chart = DailySpendChart::new();
        content.append(&chart.area);

        let providers = section("Providers");
        let projects = section("Projects");
        let models = section("Models");
        content.append(&providers);
        content.append(&projects);
        content.append(&models);

        clamp.set_child(Some(&content));
        scroller.set_child(Some(&clamp));
        root.append(&scroller);
        Self {
            root,
            status,
            spinner,
            error,
            loading,
            empty,
            metrics: metrics.try_into().expect("four spend metrics"),
            metric_details: metric_details
                .try_into()
                .expect("four spend metric details"),
            range_buttons: range_buttons.try_into().expect("four spend range filters"),
            suppress_range_action,
            heatmap,
            chart,
            providers,
            projects,
            models,
        }
    }

    pub fn widget(&self) -> gtk::Widget {
        self.root.clone().upcast()
    }

    pub fn render(&self, model: &SpendViewModel) {
        let selected_range = canonical_range(&model.selected_range);
        if let Some((_, button)) = RANGE_LABELS
            .iter()
            .zip(self.range_buttons.iter())
            .find(|((_, value), _)| *value == selected_range)
        {
            if !button.is_active() {
                self.suppress_range_action.set(true);
                button.set_active(true);
                self.suppress_range_action.set(false);
            }
        }
        self.status.set_text(&spend_status(model));
        let scanning = matches!(model.backend_status.as_str(), "idle" | "refreshing");
        if scanning {
            self.spinner.start();
            self.spinner.set_visible(true);
        } else {
            self.spinner.stop();
            self.spinner.set_visible(false);
        }

        let error_text = model
            .refresh_error
            .as_ref()
            .map(|error| safe_error_text(error, "usage refresh"))
            .or_else(|| {
                model
                    .cost_error
                    .as_ref()
                    .map(|error| safe_error_text(error, "spend scan"))
            });
        let has_error = error_text.is_some();
        if let Some(error) = error_text {
            self.error.set_text(&error);
            self.error.set_visible(true);
        } else {
            self.error.set_visible(false);
        }
        self.loading
            .set_visible(!model.spend_present && scanning && !has_error);
        self.empty.set_visible(
            model.spend_present
                && model.empty
                && model.providers.is_empty()
                && model.models.is_empty(),
        );

        let currency = model
            .display_currency
            .as_deref()
            .or(model.source_currency.as_deref())
            .unwrap_or("USD");
        let total = amount_text(&model.total, currency);
        let session = amount_text(&model.session, currency);
        let token_count = count_text(&model.tokens);
        let coverage = if model.coverage.has_counts {
            format!(
                "{} priced · {} unpriced",
                model.coverage.priced, model.coverage.unpriced
            )
        } else {
            "No token coverage summary".to_owned()
        };
        let values = [total, session, token_count, coverage];
        let details = [
            partial_text(model.total.partial, "All providers"),
            partial_text(model.session.partial, "Current session"),
            partial_text(model.tokens.partial, "Token count"),
            model
                .coverage
                .provenance
                .as_deref()
                .unwrap_or("History coverage is independent of token knownness")
                .to_owned(),
        ];
        for ((value_label, detail_label), (value, detail)) in self
            .metrics
            .iter()
            .zip(self.metric_details.iter())
            .zip(values.into_iter().zip(details))
        {
            value_label.set_text(&value);
            detail_label.set_text(&detail);
        }

        self.heatmap.render(&model.token_heatmap);
        self.chart.set_points(&model.daily_chart, currency);
        replace_rows(
            &self.providers,
            model
                .providers
                .iter()
                .map(|row| provider_row(row, currency)),
        );
        replace_rows(
            &self.projects,
            model.projects.iter().map(|row| entry_row(row, currency)),
        );
        replace_rows(
            &self.models,
            model.models.iter().map(|row| entry_row(row, currency)),
        );
    }

    pub fn show_backend_start_error(&self) {
        self.status.set_text("Backend worker could not start");
        self.error.set_text("The native backend could not start. Check the local CLI setup and restart the application.");
        self.error.set_visible(true);
        self.loading.set_visible(false);
        self.spinner.stop();
        self.spinner.set_visible(false);
    }
}

pub struct SessionsView {
    pub root: gtk::Box,
    status: gtk::Label,
    spinner: gtk::Spinner,
    error: gtk::Label,
    empty: gtk::Label,
    rows: gtk::Box,
}

impl SessionsView {
    pub fn new(application: &adw::Application) -> Self {
        let root = gtk::Box::new(gtk::Orientation::Vertical, 0);
        root.append(&page_header(
            application,
            "Sessions",
            "Coding agent activity",
        ));
        let scroller = gtk::ScrolledWindow::new();
        scroller.set_vexpand(true);
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        let clamp = adw::Clamp::new();
        clamp.set_maximum_size(900);
        clamp.set_tightening_threshold(620);
        clamp.set_margin_top(16);
        clamp.set_margin_bottom(20);
        clamp.set_margin_start(20);
        clamp.set_margin_end(20);
        let content = gtk::Box::new(gtk::Orientation::Vertical, 12);

        let status_row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let spinner = gtk::Spinner::new();
        status_row.append(&spinner);
        let status = text_label("Checking agent sessions…", "dim-label");
        status.set_xalign(0.0);
        status.set_hexpand(true);
        status_row.append(&status);
        status_row.append(&action_button("Refresh", "app.refresh", None));
        content.append(&status_row);

        let error = text_label("", "error");
        error.set_wrap(true);
        error.set_xalign(0.0);
        error.set_visible(false);
        content.append(&error);
        let empty = text_label("No agent sessions detected", "title-3");
        empty.set_xalign(0.0);
        empty.set_wrap(true);
        empty.set_visible(false);
        content.append(&empty);
        let rows = gtk::Box::new(gtk::Orientation::Vertical, 10);
        content.append(&rows);
        clamp.set_child(Some(&content));
        scroller.set_child(Some(&clamp));
        root.append(&scroller);
        Self {
            root,
            status,
            spinner,
            error,
            empty,
            rows,
        }
    }

    pub fn widget(&self) -> gtk::Widget {
        self.root.clone().upcast()
    }

    pub fn render(&self, model: &SessionsViewModel) {
        let status = model.scan_status.as_ref();
        let scanning = matches!(model.backend_status.as_str(), "idle" | "refreshing");
        let running = model
            .sessions
            .iter()
            .filter(|session| session.is_running())
            .count();
        let known = model.sessions.len();
        let status_text = match status {
            Some(status) if scanning && status.has_successful_scan => format!(
                "Refreshing · showing the last successful result · {running} running of {known} known sessions"
            ),
            Some(status) if scanning && status.last_error.is_some() => {
                "Retrying the session scan · showing the last available result".into()
            }
            Some(status) if status.last_error.is_some() && status.has_successful_scan => format!(
                "Session scan failed · showing the last successful result · {running} running of {known} known sessions"
            ),
            Some(status) if status.last_error.is_some() => "The first session scan failed".into(),
            Some(status) if status.has_successful_scan => {
                format!("{running} running of {known} known sessions")
            }
            Some(_) => "Session scan has not completed successfully".into(),
            None if scanning => "Checking agent sessions…".into(),
            None => "Session scan has not completed yet".into(),
        };
        self.status.set_text(&status_text);
        if scanning {
            self.spinner.start();
            self.spinner.set_visible(true);
        } else {
            self.spinner.stop();
            self.spinner.set_visible(false);
        }
        let error_text = sessions_error_text(status, model.backend_error.as_ref());
        if let Some(error_text) = error_text {
            self.error.set_text(&error_text);
            self.error.set_visible(true);
        } else {
            self.error.set_visible(false);
        }

        self.empty.set_text(sessions_empty_message(status));
        self.empty
            .set_visible(sessions_empty_visible(known, scanning, status.is_some()));
        replace_rows(&self.rows, model.sessions.iter().take(24).map(session_row));
    }

    pub fn show_backend_start_error(&self) {
        self.status.set_text("Backend worker could not start");
        self.error.set_text("The native backend could not start. Check the local CLI setup and restart the application.");
        self.error.set_visible(true);
        self.spinner.stop();
        self.spinner.set_visible(false);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HeatmapMode {
    Daily,
    Weekly,
    Cumulative,
}

struct HeatmapState {
    model: Option<TokenHeatmap>,
    mode: HeatmapMode,
    grid: gtk::Grid,
    info: gtk::Label,
    summary: gtk::Label,
    months: gtk::Label,
}

struct HeatmapView {
    root: gtk::Box,
    state: Rc<RefCell<HeatmapState>>,
}

impl HeatmapView {
    fn new() -> Self {
        let root = gtk::Box::new(gtk::Orientation::Vertical, 8);
        let title_row = gtk::Box::new(gtk::Orientation::Vertical, 2);
        let title = text_label("Token activity", "heading");
        title.set_xalign(0.0);
        title_row.append(&title);
        let summary = text_label("Unknown is separate from known zero", "caption");
        summary.add_css_class("dim-label");
        summary.set_xalign(0.0);
        title_row.append(&summary);
        root.append(&title_row);

        let mode_row = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        mode_row.add_css_class("linked");
        let grid = gtk::Grid::new();
        grid.set_column_spacing(2);
        grid.set_row_spacing(2);
        grid.set_column_homogeneous(true);
        grid.set_halign(gtk::Align::Start);
        grid.set_hexpand(false);
        grid.update_property(&[
            gtk::accessible::Property::Label("Token activity heatmap"),
            gtk::accessible::Property::Description(
                "Fifty-three Sunday-aligned weeks. Use arrow keys to move between dates or weeks; focus and pointer labels are identical.",
            ),
        ]);
        let info = text_label("", "caption");
        info.set_xalign(0.0);
        info.set_wrap(true);
        let legend = text_label(
            "Solid neutral: known zero · dashed: unknown · shade: more tokens · dotted outline: partial",
            "caption",
        );
        legend.add_css_class("dim-label");
        legend.set_xalign(0.0);
        legend.set_wrap(true);
        let months = text_label("", "caption");
        months.add_css_class("dim-label");
        months.set_xalign(0.0);
        let state = Rc::new(RefCell::new(HeatmapState {
            model: None,
            mode: HeatmapMode::Daily,
            grid: grid.clone(),
            info: info.clone(),
            summary: summary.clone(),
            months: months.clone(),
        }));
        let mut group: Option<gtk::ToggleButton> = None;
        for (label, mode) in [
            ("Daily", HeatmapMode::Daily),
            ("Weekly", HeatmapMode::Weekly),
            ("Cumulative", HeatmapMode::Cumulative),
        ] {
            let button = gtk::ToggleButton::with_label(label);
            button.add_css_class("flat");
            if let Some(group) = &group {
                button.set_group(Some(group));
            } else {
                group = Some(button.clone());
                button.set_active(true);
            }
            let state = state.clone();
            button.connect_toggled(move |button| {
                if button.is_active() {
                    state.borrow_mut().mode = mode;
                    render_heatmap_grid(&state);
                }
            });
            mode_row.append(&button);
        }
        mode_row.set_halign(gtk::Align::Start);
        root.append(&mode_row);
        root.append(&months);
        root.append(&grid);
        root.append(&legend);
        root.append(&info);

        let styles = gtk::CssProvider::new();
        styles.load_from_data(
            "button.cb-heat-cell { min-width: 11px; min-height: 11px; padding: 0; border-radius: 3px; }\
             button.cb-heat-level-0 { background-color: rgba(110, 120, 130, 0.16); }\
             button.cb-heat-level-1 { background-color: rgba(31, 162, 117, 0.28); }\
             button.cb-heat-level-2 { background-color: rgba(31, 162, 117, 0.48); }\
             button.cb-heat-level-3 { background-color: rgba(31, 162, 117, 0.70); }\
             button.cb-heat-level-4 { background-color: rgba(31, 162, 117, 0.94); }\
             button.cb-heat-unknown { background-color: rgba(110, 120, 130, 0.05); border: 1px dashed rgba(110, 120, 130, 0.75); }\
             button.cb-heat-partial { border: 1px dotted rgba(20, 20, 20, 0.9); }",
        );
        if let Some(display) = gtk::gdk::Display::default() {
            gtk::style_context_add_provider_for_display(
                &display,
                &styles,
                gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
            );
        }
        Self { root, state }
    }

    fn render(&self, model: &TokenHeatmap) {
        self.state.borrow_mut().model = Some(model.clone());
        render_heatmap_grid(&self.state);
    }
}

fn render_heatmap_grid(state: &Rc<RefCell<HeatmapState>>) {
    let (model, mode, grid, info, summary, months) = {
        let state = state.borrow();
        (
            state.model.clone(),
            state.mode,
            state.grid.clone(),
            state.info.clone(),
            state.summary.clone(),
            state.months.clone(),
        )
    };
    let Some(model) = model else {
        return;
    };
    let mut known_total = 0_i64;
    let mut has_known = false;
    let mut total_partial = false;
    for day in model.days.iter().filter(|day| day.visible) {
        total_partial |= day.value.partial || day.value.tokens.is_none();
        if let Some(tokens) = day.value.tokens {
            has_known = true;
            if let Some(total) = known_total.checked_add(tokens) {
                known_total = total;
            } else {
                total_partial = true;
            }
        }
    }
    let summary_text = if !has_known {
        "No daily token counts are known in the last 365 days".to_owned()
    } else {
        let total = format!(
            "Known subtotal: {} tokens in the last 365 days",
            format_tokens(Some(i128::from(known_total)))
        );
        if total_partial {
            format!("{total} · partial known coverage")
        } else {
            total
        }
    };
    summary.set_text(&summary_text);
    while let Some(child) = grid.first_child() {
        grid.remove(&child);
    }
    info.set_text(heatmap_mode_hint(mode));

    let mut last_month = None;
    let month_names = (0..WEEK_COUNT)
        .filter_map(|week| {
            let date = model.start + chrono::Duration::days((week * DAY_COUNT) as i64);
            let month = date.month();
            let changed = last_month != Some(month);
            last_month = Some(month);
            changed.then(|| date.format("%b").to_string())
        })
        .collect::<Vec<_>>();
    months.set_text(&month_names.join("  "));

    let mut navigation = Vec::<Option<gtk::Button>>::new();
    match mode {
        HeatmapMode::Daily => {
            navigation.reserve(model.days.len());
            for (index, day) in model.days.iter().enumerate() {
                let column = (index / DAY_COUNT) as i32;
                let row = (index % DAY_COUNT) as i32 + 1;
                if !day.visible {
                    let placeholder = gtk::Box::new(gtk::Orientation::Horizontal, 0);
                    placeholder.set_size_request(11, 11);
                    grid.attach(&placeholder, column, row, 1, 1);
                    navigation.push(None);
                    continue;
                }
                let label = daily_label(day.date, day.value);
                let button = heatmap_button(&label, model.daily_levels[index], day.value);
                add_heatmap_pointer_and_focus(&button, &label, &info);
                grid.attach(&button, column, row, 1, 1);
                navigation.push(Some(button));
            }
        }
        HeatmapMode::Weekly | HeatmapMode::Cumulative => {
            navigation.reserve(WEEK_COUNT);
            for week in 0..WEEK_COUNT {
                let week_start = model.start + chrono::Duration::days((week * DAY_COUNT) as i64);
                let value = if mode == HeatmapMode::Weekly {
                    model.weeks[week]
                } else {
                    model.cumulative[week]
                };
                let has_visible_day = model.days[week * DAY_COUNT..(week + 1) * DAY_COUNT]
                    .iter()
                    .any(|day| day.visible);
                if !has_visible_day {
                    let placeholder = gtk::Box::new(gtk::Orientation::Horizontal, 0);
                    placeholder.set_size_request(11, 84);
                    grid.attach(&placeholder, week as i32, 1, 1, DAY_COUNT as i32);
                    navigation.push(None);
                    continue;
                }
                let label = aggregate_label(mode, week_start, value);
                let level = if mode == HeatmapMode::Weekly {
                    model.weekly_levels[week]
                } else {
                    model.cumulative_levels[week]
                };
                let button = heatmap_button(&label, level, value);
                button.set_size_request(12, 84);
                add_heatmap_pointer_and_focus(&button, &label, &info);
                grid.attach(&button, week as i32, 1, 1, DAY_COUNT as i32);
                navigation.push(Some(button));
            }
        }
    }

    attach_heatmap_keyboard(&navigation, mode);
}

fn attach_heatmap_keyboard(buttons: &[Option<gtk::Button>], mode: HeatmapMode) {
    let weak_buttons = buttons
        .iter()
        .map(|button| button.as_ref().map(|button| button.downgrade()))
        .collect::<Vec<_>>();
    for (index, button) in buttons.iter().enumerate() {
        let Some(button) = button else { continue };
        let targets = weak_buttons.clone();
        let keys = gtk::EventControllerKey::new();
        keys.connect_key_pressed(move |_, key, _, _| {
            let target = match (mode, key) {
                (HeatmapMode::Daily, gtk::gdk::Key::Left) => index.checked_sub(DAY_COUNT),
                (HeatmapMode::Daily, gtk::gdk::Key::Right) => index
                    .checked_add(DAY_COUNT)
                    .filter(|target| *target < targets.len()),
                (HeatmapMode::Daily, gtk::gdk::Key::Up) => index.checked_sub(1),
                (HeatmapMode::Daily, gtk::gdk::Key::Down) => index
                    .checked_add(1)
                    .filter(|target| *target < targets.len()),
                (HeatmapMode::Weekly | HeatmapMode::Cumulative, gtk::gdk::Key::Left) => {
                    index.checked_sub(1)
                }
                (HeatmapMode::Weekly | HeatmapMode::Cumulative, gtk::gdk::Key::Right) => index
                    .checked_add(1)
                    .filter(|target| *target < targets.len()),
                _ => None,
            };
            if let Some(button) = target
                .and_then(|target| targets.get(target))
                .and_then(Option::as_ref)
                .and_then(glib::WeakRef::upgrade)
            {
                button.grab_focus();
                glib::Propagation::Stop
            } else {
                glib::Propagation::Proceed
            }
        });
        button.add_controller(keys);
    }
}

fn add_heatmap_pointer_and_focus(button: &gtk::Button, text: &str, info: &gtk::Label) {
    button.set_tooltip_text(Some(text));
    button.update_property(&[
        gtk::accessible::Property::Label(text),
        gtk::accessible::Property::Description(text),
    ]);
    let clicked_info = info.clone();
    let text_owned = text.to_owned();
    button.connect_clicked(move |_| clicked_info.set_text(&text_owned));

    let enter_info = info.clone();
    let text_owned = text.to_owned();
    let motion = gtk::EventControllerMotion::new();
    motion.connect_enter(move |_, _, _| enter_info.set_text(&text_owned));
    let leave_info = info.clone();
    motion.connect_leave(move |_| leave_info.set_text(""));
    button.add_controller(motion);

    let focus_info = info.clone();
    let text_owned = text.to_owned();
    let focus = gtk::EventControllerFocus::new();
    focus.connect_enter(move |_| focus_info.set_text(&text_owned));
    let focus_leave_info = info.clone();
    focus.connect_leave(move |_| focus_leave_info.set_text(""));
    button.add_controller(focus);
}

fn heatmap_button(
    accessible_text: &str,
    level: Option<u8>,
    value: TokenActivityValue,
) -> gtk::Button {
    let button = gtk::Button::new();
    button.add_css_class("flat");
    button.add_css_class("cb-heat-cell");
    button.add_css_class(&format!("cb-heat-level-{}", level.unwrap_or(0)));
    if level.is_none() {
        button.remove_css_class("cb-heat-level-0");
        button.add_css_class("cb-heat-unknown");
    }
    if value.partial {
        button.add_css_class("cb-heat-partial");
    }
    button.set_focusable(true);
    button.set_size_request(11, 11);
    button.set_tooltip_text(Some(accessible_text));
    button.update_property(&[
        gtk::accessible::Property::Label(accessible_text),
        gtk::accessible::Property::Description(accessible_text),
    ]);
    button
}

fn daily_label(date: chrono::NaiveDate, value: TokenActivityValue) -> String {
    format!(
        "{} · {}",
        date.format("%a %-d %b %Y"),
        token_value_text(value)
    )
}

fn aggregate_label(
    mode: HeatmapMode,
    week_start: chrono::NaiveDate,
    value: TokenActivityValue,
) -> String {
    let prefix = match mode {
        HeatmapMode::Weekly => "Week of",
        HeatmapMode::Cumulative => "Through",
        HeatmapMode::Daily => "",
    };
    format!(
        "{prefix} {} · {}",
        week_start.format("%-d %b %Y"),
        token_value_text(value)
    )
}

fn token_value_text(value: TokenActivityValue) -> String {
    let count = value
        .tokens
        .map(|count| format!("{} tokens", format_tokens(Some(i128::from(count)))))
        .unwrap_or_else(|| "Unknown token count".to_owned());
    if value.partial {
        format!("{count} · partial")
    } else {
        count
    }
}

fn heatmap_mode_hint(mode: HeatmapMode) -> &'static str {
    match mode {
        HeatmapMode::Daily => "Daily view · arrows move between adjacent dates.",
        HeatmapMode::Weekly => "Weekly view · arrows move between Sunday-aligned weeks.",
        HeatmapMode::Cumulative => "Cumulative view · arrows move between week-end totals.",
    }
}

struct DailySpendChart {
    area: gtk::DrawingArea,
    values: Rc<RefCell<Vec<Option<f64>>>>,
}

impl DailySpendChart {
    fn new() -> Self {
        let area = gtk::DrawingArea::new();
        area.set_content_height(150);
        area.set_hexpand(true);
        area.update_property(&[
            gtk::accessible::Property::Label("Daily spend chart"),
            gtk::accessible::Property::Description(
                "Bars show priced daily spend for the selected range. Missing or unpriced days are not shown as zero.",
            ),
        ]);
        let values = Rc::new(RefCell::new(Vec::<Option<f64>>::new()));
        let draw_values = values.clone();
        area.set_draw_func(move |_, context, width, height| {
            if width < 2 || height < 2 {
                return;
            }
            let values = draw_values.borrow();
            if values.is_empty() {
                return;
            }
            let max_value = values
                .iter()
                .filter_map(|value| *value)
                .filter(|value| value.is_finite() && *value >= 0.0)
                .fold(0.0_f64, f64::max);
            let left = 4.0;
            let top = 4.0;
            let chart_width = f64::from(width) - 8.0;
            let chart_height = f64::from(height) - 20.0;
            let gap = 3.0;
            let slot = chart_width / values.len() as f64;
            let bar_width = (slot - gap).clamp(1.0, 18.0);
            context.set_source_rgba(0.35, 0.40, 0.47, 0.18);
            context.rectangle(left, top + chart_height, chart_width, 1.0);
            let _ = context.fill();
            for (index, value) in values.iter().enumerate() {
                let x = left + index as f64 * slot + (slot - bar_width) / 2.0;
                if let Some(value) = value.filter(|value| value.is_finite() && *value >= 0.0) {
                    let fraction = if max_value > 0.0 {
                        value / max_value
                    } else {
                        0.0
                    };
                    let bar_height =
                        (fraction * (chart_height - 2.0)).max(if value > 0.0 { 2.0 } else { 1.0 });
                    context.set_source_rgba(0.16, 0.57, 0.43, 0.85);
                    context.rectangle(x, top + chart_height - bar_height, bar_width, bar_height);
                    let _ = context.fill();
                } else {
                    context.set_source_rgba(0.42, 0.46, 0.51, 0.6);
                    context.set_line_width(1.0);
                    context.move_to(x, top + chart_height - 4.0);
                    context.line_to(x + bar_width, top + chart_height - 4.0);
                    let _ = context.stroke();
                }
            }
        });
        Self { area, values }
    }

    fn set_points(
        &self,
        points: &[codexbar_backend::presentation::SpendDailyPoint],
        _currency: &str,
    ) {
        *self.values.borrow_mut() = points.iter().map(|point| point.display_amount).collect();
        let description = if points.is_empty() {
            "No daily spend points are available for this range."
        } else {
            "Bars show priced daily spend for the selected range. Missing or unpriced days are not shown as zero."
        };
        self.area
            .update_property(&[gtk::accessible::Property::Description(description)]);
        self.area.queue_draw();
    }
}

fn page_header(_application: &adw::Application, title: &str, subtitle: &str) -> adw::HeaderBar {
    let header = adw::HeaderBar::new();
    header.set_title_widget(Some(&adw::WindowTitle::new(title, subtitle)));
    for (text, action, target) in [
        ("Dashboard", "app.dashboard", None),
        ("Usage", "app.page", Some("usage")),
        ("Sessions", "app.page", Some("sessions")),
        ("Spend", "app.page", Some("spend")),
        ("Settings", "app.settings", None),
    ] {
        let button = gtk::Button::with_label(text);
        button.set_action_name(Some(action));
        if let Some(target) = target {
            button.set_action_target_value(Some(&target.to_variant()));
        }
        header.pack_end(&button);
    }
    let refresh = gtk::Button::with_label("Refresh");
    refresh.set_action_name(Some("app.refresh"));
    header.pack_end(&refresh);
    header
}

fn action_button(label: &str, action: &str, target: Option<&str>) -> gtk::Button {
    let button = gtk::Button::with_label(label);
    button.set_action_name(Some(action));
    if let Some(target) = target {
        button.set_action_target_value(Some(&target.to_variant()));
    }
    button
}

fn section(title: &str) -> gtk::Box {
    let section = gtk::Box::new(gtk::Orientation::Vertical, 6);
    let heading = text_label(title, "heading");
    heading.set_xalign(0.0);
    section.append(&heading);
    section
}

fn provider_row(row: &SpendProviderRow, currency: &str) -> gtk::Widget {
    data_row(
        &row.provider,
        amount_text_from_parts(row.display_cost, row.cost_known, row.cost_partial, currency),
        count_text(&row.tokens),
    )
}

fn entry_row(row: &SpendEntryRow, currency: &str) -> gtk::Widget {
    data_row(
        &row.name,
        amount_text_from_parts(row.display_cost, row.cost_known, row.cost_partial, currency),
        count_text(&row.tokens),
    )
}

fn data_row(name: &str, amount: String, tokens: String) -> gtk::Widget {
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    row.set_margin_top(4);
    row.set_margin_bottom(4);
    let accessible_name = name.to_owned();
    let accessible_description = format!("{tokens} · {amount}");
    let name_label = text_label(name, "body");
    name_label.set_xalign(0.0);
    name_label.set_hexpand(true);
    name_label.set_ellipsize(gtk::pango::EllipsizeMode::End);
    row.append(&name_label);
    let token_label = text_label(&tokens, "caption");
    token_label.add_css_class("dim-label");
    row.append(&token_label);
    let amount_label = text_label(&amount, "numeric");
    amount_label.set_xalign(1.0);
    row.append(&amount_label);
    row.set_accessible_role(gtk::AccessibleRole::Group);
    row.update_property(&[
        gtk::accessible::Property::Label(&accessible_name),
        gtk::accessible::Property::Description(&accessible_description),
    ]);
    row.upcast()
}

fn session_row(session: &codexbar_core::domain::AgentSession) -> gtk::Widget {
    let frame = gtk::Frame::new(None);
    frame.add_css_class("card");
    let body = gtk::Box::new(gtk::Orientation::Vertical, 6);
    body.set_margin_top(10);
    body.set_margin_bottom(10);
    body.set_margin_start(14);
    body.set_margin_end(14);
    let heading = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let provider = if session.provider.is_empty() {
        "Agent session"
    } else {
        &session.provider
    };
    let title = text_label(provider, "title-3");
    title.set_xalign(0.0);
    title.set_hexpand(true);
    heading.append(&title);
    let state = if session.is_running() {
        "Running"
    } else if session.state.is_empty() {
        "Recent"
    } else {
        &session.state
    };
    let state_label = text_label(state, "caption");
    state_label.add_css_class(if session.is_running() {
        "success"
    } else {
        "dim-label"
    });
    heading.append(&state_label);
    body.append(&heading);

    let project = if !session.project_name.is_empty() {
        session.project_name.as_str()
    } else if !session.cwd.is_empty() {
        session.cwd.as_str()
    } else {
        "Project unknown"
    };
    let project_label = text_label(project, "heading");
    project_label.set_xalign(0.0);
    project_label.set_ellipsize(gtk::pango::EllipsizeMode::Middle);
    body.append(&project_label);
    if !session.cwd.is_empty() && session.cwd != project {
        let cwd = text_label(&session.cwd, "caption");
        cwd.add_css_class("dim-label");
        cwd.set_xalign(0.0);
        cwd.set_ellipsize(gtk::pango::EllipsizeMode::Middle);
        body.append(&cwd);
    }
    let mut metadata = Vec::new();
    if session.pid > 0 {
        metadata.push(format!("PID {}", session.pid));
    }
    if !session.host.is_empty() {
        metadata.push(format!("Host {}", session.host));
    }
    if let Some(activity) = session.last_activity_at {
        metadata.push(format!("Active {}", activity.format("%Y-%m-%d %H:%M UTC")));
    }
    if let Some(started) = session.started_at {
        metadata.push(format!("Started {}", started.format("%Y-%m-%d %H:%M UTC")));
    }
    if !metadata.is_empty() {
        let details = text_label(&metadata.join(" · "), "caption");
        details.add_css_class("dim-label");
        details.set_xalign(0.0);
        details.set_wrap(true);
        body.append(&details);
    }
    frame.set_child(Some(&body));
    frame.set_accessible_role(gtk::AccessibleRole::Group);
    frame.update_property(&[
        gtk::accessible::Property::Label(provider),
        gtk::accessible::Property::Description(&format!("{state} · {project}")),
    ]);
    frame.upcast()
}

fn replace_rows<I>(container: &gtk::Box, rows: I)
where
    I: IntoIterator<Item = gtk::Widget>,
{
    while let Some(child) = container.first_child() {
        container.remove(&child);
    }
    for row in rows {
        container.append(&row);
    }
}

fn text_label(text: &str, css_class: &str) -> gtk::Label {
    let label = gtk::Label::new(Some(text));
    label.add_css_class(css_class);
    label
}

fn amount_text(amount: &SpendAmount, currency: &str) -> String {
    amount_text_from_parts(
        amount.display_amount,
        amount.known,
        amount.partial,
        currency,
    )
}

fn amount_text_from_parts(
    value: Option<f64>,
    known: bool,
    partial: bool,
    currency: &str,
) -> String {
    let text = if known {
        format_currency(value, currency, false)
    } else {
        "Unknown".to_owned()
    };
    if partial {
        format!("{text} · partial")
    } else {
        text
    }
}

fn count_text(count: &SpendCount) -> String {
    let text = count
        .value
        .map(|value| format!("{} tokens", format_tokens(Some(i128::from(value)))))
        .unwrap_or_else(|| "Unknown tokens".to_owned());
    if count.partial {
        format!("{text} · partial")
    } else {
        text
    }
}

fn partial_text(partial: bool, otherwise: &str) -> String {
    if partial {
        format!("{otherwise} · partial data")
    } else {
        otherwise.to_owned()
    }
}

fn canonical_range(value: &str) -> &str {
    match value {
        "7d" => "7 days",
        "30d" => "30 days",
        "90d" => "90 days",
        "7 days" | "30 days" | "90 days" | "All" => value,
        _ => "30 days",
    }
}

fn spend_status(model: &SpendViewModel) -> String {
    match model.backend_status.as_str() {
        "idle" => "Backend is starting…".to_owned(),
        "refreshing" if model.spend_present => {
            "Refreshing · last spend result remains visible".to_owned()
        }
        "refreshing" => "Scanning local spend history…".to_owned(),
        "failed" => "Refresh failed · showing the last available result".to_owned(),
        "stopped" => "Backend stopped".to_owned(),
        _ if model.spend_present => format!("Spend data · {}", model.selected_range),
        _ => "Spend data is not available yet".to_owned(),
    }
}

fn safe_error_text(error: &ControllerError, action: &str) -> String {
    let kind = match &error.kind {
        ControllerErrorKind::Cancelled => "was cancelled",
        ControllerErrorKind::Configuration => "could not use the current configuration",
        ControllerErrorKind::Network => "could not reach the service",
        ControllerErrorKind::Protocol => "returned unreadable data",
        ControllerErrorKind::Process => "could not run the local CLI",
        ControllerErrorKind::Storage => "could not read local data",
        ControllerErrorKind::Timeout => "timed out",
        ControllerErrorKind::Internal => "could not complete",
    };
    format!("The {action} {kind}. Existing rows remain available when present.")
}

fn sessions_error_text(
    status: Option<&codexbar_backend::controller::SessionScanStatus>,
    backend_error: Option<&ControllerError>,
) -> Option<String> {
    if let Some(error) = status.and_then(|status| status.last_error.as_ref()) {
        Some(safe_error_text(error, "session scan"))
    } else if status.is_none() {
        backend_error.map(|error| safe_error_text(error, "backend refresh"))
    } else {
        None
    }
}

fn sessions_empty_message(
    status: Option<&codexbar_backend::controller::SessionScanStatus>,
) -> &'static str {
    if status.is_some_and(|status| status.has_successful_scan) {
        "The last successful scan found no agent sessions."
    } else if status.is_some_and(|status| status.last_error.is_some()) {
        "No successful session scan is available yet."
    } else {
        "No agent sessions have been reported yet."
    }
}

fn sessions_empty_visible(session_count: usize, scanning: bool, scan_status_present: bool) -> bool {
    session_count == 0 && (scan_status_present || !scanning)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    #[test]
    fn heatmap_accessible_labels_preserve_unknown_zero_and_partial() {
        let date = NaiveDate::from_ymd_opt(2026, 10, 24).unwrap();
        let unknown = daily_label(
            date,
            TokenActivityValue {
                tokens: None,
                partial: true,
            },
        );
        let zero = daily_label(
            date,
            TokenActivityValue {
                tokens: Some(0),
                partial: false,
            },
        );
        assert!(unknown.contains("Unknown token count"));
        assert!(unknown.contains("partial"));
        assert!(zero.contains("0 tokens"));
        assert!(!zero.contains("Unknown"));
        assert_eq!(
            aggregate_label(
                HeatmapMode::Weekly,
                date,
                TokenActivityValue {
                    tokens: Some(1_250),
                    partial: true,
                }
            ),
            "Week of 24 Oct 2026 · 1.2K tokens · partial"
        );
    }

    #[test]
    fn sessions_loading_and_success_errors_stay_separate() {
        use codexbar_backend::controller::SessionScanStatus;

        let loading = SessionScanStatus::default();
        let unrelated_error = ControllerError {
            kind: ControllerErrorKind::Process,
            operation: "cli_cost".into(),
        };
        assert!(!sessions_empty_visible(0, true, false));
        assert!(sessions_empty_visible(0, false, false));
        assert!(sessions_empty_visible(0, false, true));
        assert!(sessions_error_text(None, Some(&unrelated_error)).is_some());

        let successful = SessionScanStatus {
            has_successful_scan: true,
            last_error: None,
        };
        assert!(sessions_error_text(Some(&successful), Some(&unrelated_error)).is_none());
        assert_eq!(
            sessions_empty_message(Some(&successful)),
            "The last successful scan found no agent sessions."
        );
        assert_eq!(
            sessions_empty_message(Some(&loading)),
            "No agent sessions have been reported yet."
        );
    }
}
