//! GTK rendering for the native dashboard projection.

use crate::dashboard::{
    BarChartModel, DashboardModel, MeterSeverity, ProviderCardModel, QuotaWindowModel, TrendModel,
};
use gtk::prelude::*;
use libadwaita as adw;

pub struct DashboardView {
    pub root: gtk::Box,
    status: gtk::Label,
    error: gtk::Label,
    overview_title: gtk::Label,
    overview_detail: gtk::Label,
    stats: [gtk::Label; 4],
    stat_captions: [gtk::Label; 4],
    empty: gtk::Box,
    loading: gtk::Box,
    providers: gtk::Box,
    spinner: gtk::Spinner,
    meter_styles: gtk::CssProvider,
}

impl DashboardView {
    pub fn new() -> Self {
        let root = gtk::Box::new(gtk::Orientation::Vertical, 0);
        let meter_styles = gtk::CssProvider::new();
        if let Some(display) = gtk::gdk::Display::default() {
            gtk::style_context_add_provider_for_display(
                &display,
                &meter_styles,
                gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
            );
        }
        let header = adw::HeaderBar::new();
        let title = adw::WindowTitle::new("CodexBar", "Usage dashboard");
        header.set_title_widget(Some(&title));
        for (text, action) in [
            ("Quit", "app.quit"),
            ("About", "app.about"),
            ("Settings", "app.settings"),
            ("Refresh", "app.refresh"),
        ] {
            let button = gtk::Button::with_label(text);
            button.set_action_name(Some(action));
            header.pack_end(&button);
        }
        root.append(&header);

        let scroller = gtk::ScrolledWindow::new();
        scroller.set_vexpand(true);
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        let clamp = adw::Clamp::new();
        clamp.set_maximum_size(920);
        clamp.set_tightening_threshold(620);
        clamp.set_margin_top(16);
        clamp.set_margin_bottom(16);
        clamp.set_margin_start(20);
        clamp.set_margin_end(20);

        let content = gtk::Box::new(gtk::Orientation::Vertical, 12);
        let status_row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let spinner = gtk::Spinner::new();
        spinner.set_visible(false);
        status_row.append(&spinner);
        let status = label("Loading provider data…", "dim-label");
        status.set_hexpand(true);
        status.set_xalign(0.0);
        status_row.append(&status);
        content.append(&status_row);

        let error = label("", "error");
        error.set_wrap(true);
        error.set_xalign(0.0);
        error.set_visible(false);
        content.append(&error);

        let overview_card = gtk::Frame::new(None);
        overview_card.add_css_class("card");
        let overview_content = gtk::Box::new(gtk::Orientation::Vertical, 6);
        overview_content.set_margin_top(12);
        overview_content.set_margin_bottom(12);
        overview_content.set_margin_start(18);
        overview_content.set_margin_end(18);
        let overview_title = label("Your usage dashboard is getting ready", "title-3");
        overview_title.set_xalign(0.0);
        overview_content.append(&overview_title);
        let overview_detail = label(
            "Provider status and quota details will appear here.",
            "dim-label",
        );
        overview_detail.set_xalign(0.0);
        overview_detail.set_wrap(true);
        overview_content.append(&overview_detail);
        overview_card.set_child(Some(&overview_content));
        content.append(&overview_card);

        let stat_row = gtk::Box::new(gtk::Orientation::Horizontal, 10);
        stat_row.set_homogeneous(true);
        let mut stats_vec = Vec::new();
        let mut captions_vec = Vec::new();
        for (title, initial) in [
            ("Providers", "—"),
            ("Highest usage", "—"),
            ("Credits", "—"),
            ("Local spend", "—"),
        ] {
            let tile = gtk::Frame::new(None);
            tile.add_css_class("card");
            let body = gtk::Box::new(gtk::Orientation::Vertical, 5);
            body.set_margin_top(10);
            body.set_margin_bottom(10);
            body.set_margin_start(12);
            body.set_margin_end(12);
            let name = label(title, "caption");
            name.set_xalign(0.0);
            body.append(&name);
            let value = label(initial, "title-3");
            value.add_css_class("numeric");
            value.set_xalign(0.0);
            body.append(&value);
            let caption = label("", "caption");
            caption.add_css_class("dim-label");
            caption.set_xalign(0.0);
            caption.set_visible(false);
            body.append(&caption);
            tile.set_child(Some(&body));
            stat_row.append(&tile);
            stats_vec.push(value);
            captions_vec.push(caption);
        }
        let stats: [gtk::Label; 4] = stats_vec.try_into().expect("four dashboard tiles");
        let stat_captions: [gtk::Label; 4] =
            captions_vec.try_into().expect("four dashboard captions");
        content.append(&stat_row);

        let loading = gtk::Box::new(gtk::Orientation::Vertical, 8);
        loading.set_margin_top(12);
        let loading_title = label("Waiting for provider data", "title-3");
        loading_title.set_xalign(0.0);
        loading.append(&loading_title);
        let loading_detail = label("The first refresh runs in the background.", "dim-label");
        loading_detail.set_xalign(0.0);
        loading.append(&loading_detail);
        content.append(&loading);

        let empty = gtk::Box::new(gtk::Orientation::Vertical, 8);
        empty.set_margin_top(12);
        let empty_title = label("No providers are enabled yet", "title-3");
        empty_title.set_xalign(0.0);
        empty.append(&empty_title);
        let empty_detail = label(
            "Enable a provider in Settings → Providers to start tracking quota.",
            "dim-label",
        );
        empty_detail.set_xalign(0.0);
        empty_detail.set_wrap(true);
        empty.append(&empty_detail);
        content.append(&empty);

        let providers = gtk::Box::new(gtk::Orientation::Vertical, 10);
        content.append(&providers);

        clamp.set_child(Some(&content));
        scroller.set_child(Some(&clamp));
        scroller.set_vexpand(true);
        root.append(&scroller);
        Self {
            root,
            status,
            error,
            overview_title,
            overview_detail,
            stats,
            stat_captions,
            empty,
            loading,
            providers,
            spinner,
            meter_styles,
        }
    }

    pub fn widget(&self) -> gtk::Widget {
        self.root.clone().upcast()
    }

    pub fn render(&self, model: &DashboardModel) {
        let css = model
            .providers
            .iter()
            .flat_map(|provider| provider.windows.iter())
            .map(|window| {
                let color = window.fill_color.trim_start_matches('#');
                format!(
                    "progressbar.cb-dashboard-meter.cb-meter-{color} progress {{ background-color: #{}; }}",
                    color
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        self.meter_styles.load_from_data(&css);
        self.status.set_text(&model.status);
        if model.status.starts_with("Refreshing") || model.status.starts_with("Loading") {
            self.spinner.start();
            self.spinner.set_visible(true);
        } else {
            self.spinner.stop();
            self.spinner.set_visible(false);
        }
        if let Some(error) = &model.refresh_error {
            self.error.set_text(error);
            self.error.set_visible(true);
        } else {
            self.error.set_visible(false);
        }
        self.overview_title.set_text(&model.overview_title);
        self.overview_detail.set_text(&model.overview_detail);
        for (label, value) in self.stats.iter().zip([
            &model.provider_count,
            &model.highest_usage,
            &model.credits,
            &model.spend,
        ]) {
            label.set_text(value);
        }
        let captions: [Option<&str>; 4] = [None, None, None, model.spend_caption.as_deref()];
        for (label, value) in self.stat_captions.iter().zip(captions) {
            label.set_text(value.unwrap_or_default());
            label.set_visible(value.is_some_and(|value| !value.is_empty()));
        }
        self.loading
            .set_visible(model.provider_count == "—" && model.refresh_error.is_none());
        self.empty.set_visible(model.empty);
        clear_box(&self.providers);
        for provider in &model.providers {
            self.providers.append(&provider_card(provider));
        }
    }

    pub fn show_backend_start_error(&self) {
        self.status.set_text("Backend worker could not start");
        self.error.set_text("The native backend could not start. Restart the application or check the local CLI setup.");
        self.error.set_visible(true);
        self.spinner.stop();
        self.spinner.set_visible(false);
        self.loading.set_visible(false);
    }
}

impl Default for DashboardView {
    fn default() -> Self {
        Self::new()
    }
}

fn provider_card(model: &ProviderCardModel) -> gtk::Widget {
    let frame = gtk::Frame::new(None);
    frame.add_css_class("card");
    let body = gtk::Box::new(gtk::Orientation::Vertical, 12);
    body.set_margin_top(12);
    body.set_margin_bottom(12);
    body.set_margin_start(18);
    body.set_margin_end(18);

    let header = gtk::Box::new(gtk::Orientation::Horizontal, 10);
    let name = label(&model.name, "title-3");
    name.set_xalign(0.0);
    name.set_hexpand(true);
    header.append(&name);
    if let Some(text) = &model.badge {
        let badge = label(text, "caption");
        badge.add_css_class("dim-label");
        badge.set_tooltip_text(model.badge_help.as_deref());
        header.append(&badge);
    }
    if let Some(text) = &model.account_count {
        let badge = label(text, "caption");
        badge.add_css_class("dim-label");
        header.append(&badge);
    }
    body.append(&header);

    if !model.subtitle.is_empty() {
        let subtitle = label(&model.subtitle, "dim-label");
        subtitle.set_xalign(0.0);
        subtitle.set_ellipsize(gtk::pango::EllipsizeMode::End);
        body.append(&subtitle);
    }

    for window in &model.windows {
        body.append(&quota_row(window));
    }

    if let Some(burndown) = &model.burndown {
        let text = if burndown.will_run_out {
            format!(
                "projected {:.0}% at reset — will run out",
                burndown.projected_percent
            )
        } else {
            format!("projected {:.0}% at reset", burndown.projected_percent)
        };
        let chip = label(&text, "caption");
        chip.set_xalign(0.0);
        chip.set_tooltip_text(Some(
            "Projection from recorded quota history over the last 24 hours.",
        ));
        chip.update_property(&[
            gtk::accessible::Property::Label("Quota burndown"),
            gtk::accessible::Property::Description(&text),
        ]);
        body.append(&chip);
    }

    for chart in &model.detail_charts {
        body.append(&bar_chart(chart, &model.accent));
    }
    if let Some(chart) = &model.credit_chart {
        body.append(&bar_chart(chart, &model.accent));
    }

    if let Some(target) = &model.cost_target {
        let target = label(target, "caption");
        target.add_css_class("dim-label");
        target.set_xalign(0.0);
        target.set_wrap(true);
        body.append(&target);
    }

    let details = [
        model.credits.as_deref().map(|text| ("Credits", text)),
        model.spend.as_deref().map(|text| ("Spend", text)),
        model.balance.as_deref().map(|text| ("Balance", text)),
    ]
    .into_iter()
    .flatten()
    .collect::<Vec<_>>();
    if !details.is_empty() {
        let detail_row = gtk::Box::new(gtk::Orientation::Horizontal, 16);
        for (title, value) in details {
            let block = gtk::Box::new(gtk::Orientation::Vertical, 3);
            let title = label(title, "caption");
            title.set_xalign(0.0);
            let value = label(value, "body");
            value.add_css_class("numeric");
            value.set_xalign(0.0);
            block.append(&title);
            block.append(&value);
            detail_row.append(&block);
        }
        body.append(&detail_row);
    }
    if let Some(error) = &model.error {
        let error = label(error, "error");
        error.set_xalign(0.0);
        error.set_wrap(true);
        body.append(&error);
    }
    frame.set_child(Some(&body));
    frame.upcast()
}

fn quota_row(model: &QuotaWindowModel) -> gtk::Widget {
    let row = gtk::Box::new(gtk::Orientation::Vertical, 5);
    let heading = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let title = label(&model.title, "heading");
    title.set_xalign(0.0);
    title.set_hexpand(true);
    let amount = label(&model.usage, "numeric");
    amount.add_css_class("heading");
    heading.append(&title);
    heading.append(&amount);
    row.append(&heading);

    let meter = gtk::ProgressBar::new();
    meter.set_show_text(false);
    meter.set_fraction(model.fraction.unwrap_or(0.0));
    meter.add_css_class("cb-dashboard-meter");
    meter.add_css_class(&format!(
        "cb-meter-{}",
        model.fill_color.trim_start_matches('#')
    ));
    if !model.usage_known {
        meter.set_opacity(0.38);
    }
    meter.set_accessible_role(if model.usage_known {
        gtk::AccessibleRole::ProgressBar
    } else {
        gtk::AccessibleRole::Group
    });
    if let Some(usage) = model.fraction {
        meter.update_property(&[
            gtk::accessible::Property::Label(&model.title),
            gtk::accessible::Property::Description(&model.usage),
            gtk::accessible::Property::ValueMin(0.0),
            gtk::accessible::Property::ValueMax(100.0),
            gtk::accessible::Property::ValueNow(usage * 100.0),
            gtk::accessible::Property::ValueText(&model.usage),
        ]);
    } else {
        meter.update_property(&[
            gtk::accessible::Property::Label(&model.title),
            gtk::accessible::Property::Description(&model.usage),
        ]);
    }

    let meter_overlay = gtk::Overlay::new();
    meter_overlay.set_child(Some(&meter));
    let markers = gtk::DrawingArea::new();
    markers.set_hexpand(true);
    markers.set_vexpand(true);
    markers.set_halign(gtk::Align::Fill);
    markers.set_valign(gtk::Align::Fill);
    markers.set_can_target(false);
    let warning_markers = model.warning_markers.clone();
    let workday_tick = model.workday_tick;
    let tick_appearance = model.tick_appearance.clone();
    markers.set_draw_func(move |_, context, width, height| {
        if width <= 1 || height <= 1 {
            return;
        }
        context.set_line_width(1.0);
        context.set_source_rgba(1.0, 1.0, 1.0, 0.48);
        for threshold in &warning_markers {
            let x = f64::from(width) * threshold.clamp(0.0, 100.0) / 100.0;
            if x > 0.0 && x < f64::from(width) {
                context.move_to(x, 1.0);
                context.line_to(x, f64::from(height - 1));
                let _ = context.stroke();
            }
        }
        if let Some(progress) = workday_tick {
            let opacity = match tick_appearance.as_str() {
                "highContrast" => 0.95,
                "hidden" => 0.0,
                _ => 0.48,
            };
            if opacity > 0.0 {
                let x = f64::from(width) * progress.clamp(0.0, 100.0) / 100.0;
                context.set_source_rgba(1.0, 1.0, 1.0, opacity);
                context.move_to(x, 0.0);
                context.line_to(x, f64::from(height));
                let _ = context.stroke();
            }
        }
    });
    if !model.warning_markers.is_empty() || model.workday_tick.is_some() {
        markers.update_property(&[
            gtk::accessible::Property::Label("Quota meter markers"),
            gtk::accessible::Property::Description(&meter_marker_description(model)),
        ]);
        meter_overlay.add_overlay(&markers);
    }
    row.append(&meter_overlay);

    if let Some(trend) = &model.trend {
        row.append(&trend_chart(trend, &model.fill_color));
    }

    let chips = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    if let Some(reset) = &model.reset {
        let label = label(reset, "caption");
        label.add_css_class("dim-label");
        chips.append(&label);
    }
    if let Some(pace) = &model.pace {
        let label = label(pace, "caption");
        match model.pace_severity {
            MeterSeverity::Normal => label.add_css_class("dim-label"),
            MeterSeverity::Warning => label.add_css_class("warning"),
            MeterSeverity::Critical => label.add_css_class("error"),
        }
        chips.append(&label);
    }
    if chips.first_child().is_some() {
        row.append(&chips);
    }
    if let Some(target) = &model.daily_target {
        let target_label = label(target, "caption");
        target_label.add_css_class("dim-label");
        target_label.set_xalign(0.0);
        target_label.set_wrap(true);
        target_label.update_property(&[
            gtk::accessible::Property::Label("Daily target"),
            gtk::accessible::Property::Description(target),
        ]);
        row.append(&target_label);
    }
    row.upcast()
}

fn meter_marker_description(model: &QuotaWindowModel) -> String {
    let warning = model
        .warning_markers
        .iter()
        .map(|threshold| format!("{threshold:.0}% warning threshold"))
        .collect::<Vec<_>>();
    let workday = model
        .workday_tick
        .map(|value| format!("working-day progress {value:.0}%"));
    warning
        .into_iter()
        .chain(workday)
        .collect::<Vec<_>>()
        .join(", ")
}

fn trend_chart(model: &TrendModel, color: &str) -> gtk::Widget {
    let chart = gtk::DrawingArea::new();
    chart.set_content_height(28);
    chart.set_hexpand(true);
    chart.set_tooltip_text(Some(&model.accessible_description));
    chart.set_accessible_role(gtk::AccessibleRole::Group);
    chart.update_property(&[
        gtk::accessible::Property::Label("Quota history chart"),
        gtk::accessible::Property::Description(&model.accessible_description),
    ]);
    let points = model.points.clone();
    let color = color_components(color);
    chart.set_draw_func(move |_, context, width, height| {
        if width <= 1 || height <= 4 || points.len() < 2 {
            return;
        }
        let coordinates = codexbar_core::charts::sparkline_coordinates(
            &points,
            f64::from(width),
            f64::from(height),
        );
        if coordinates.len() < 2 {
            return;
        }
        context.set_source_rgba(color.0, color.1, color.2, 0.14);
        context.move_to(coordinates[0].0, f64::from(height));
        for (x, y) in &coordinates {
            context.line_to(*x, *y);
        }
        context.line_to(
            coordinates.last().expect("nonempty coordinates").0,
            f64::from(height),
        );
        context.close_path();
        let _ = context.fill();
        context.set_source_rgba(color.0, color.1, color.2, 0.92);
        context.set_line_width(1.7);
        context.move_to(coordinates[0].0, coordinates[0].1);
        for (x, y) in coordinates.iter().skip(1) {
            context.line_to(*x, *y);
        }
        let _ = context.stroke();
        let (x, y) = coordinates[coordinates.len() - 1];
        context.set_source_rgba(color.0, color.1, color.2, 1.0);
        context.arc(x, y, 2.2, 0.0, std::f64::consts::TAU);
        let _ = context.fill();
    });
    chart.upcast()
}

fn bar_chart(model: &BarChartModel, color: &str) -> gtk::Widget {
    let block = gtk::Box::new(gtk::Orientation::Vertical, 4);
    block.add_css_class("cb-chart-block");
    let title = label(&model.title, "caption");
    title.add_css_class("heading");
    title.set_xalign(0.0);
    block.append(&title);

    let plot = gtk::DrawingArea::new();
    plot.set_content_height(76);
    plot.set_hexpand(true);
    plot.set_tooltip_text(Some(&model.accessible_description));
    plot.set_accessible_role(gtk::AccessibleRole::Group);
    plot.update_property(&[
        gtk::accessible::Property::Label(&model.title),
        gtk::accessible::Property::Description(&model.accessible_description),
    ]);
    let points = model.points.clone();
    let color = color_components(color);
    plot.set_draw_func(move |_, context, width, height| {
        if width <= 1 || height <= 1 || points.is_empty() {
            return;
        }
        let plot_height = f64::from(height);
        let max_value = points
            .iter()
            .map(|(_, value)| value.max(0.0))
            .reduce(f64::max)
            .unwrap_or(0.0);
        let scale = if max_value > 0.0 { max_value } else { 1.0 };
        let column_width = f64::from(width) / points.len() as f64;
        for (index, (_, value)) in points.iter().enumerate() {
            let bar_height = (plot_height * 0.88 * value.max(0.0) / scale)
                .max(4.0)
                .min(plot_height);
            let x = index as f64 * column_width + column_width * 0.16;
            let y = plot_height - bar_height;
            context.set_source_rgba(color.0, color.1, color.2, 0.9);
            context.rectangle(x, y, (column_width * 0.68).max(1.0), bar_height);
            let _ = context.fill();
        }
    });
    block.append(&plot);

    let labels = gtk::Box::new(gtk::Orientation::Horizontal, 4);
    labels.set_hexpand(true);
    for (name, value) in &model.points {
        let point_label = label(name, "caption");
        point_label.add_css_class("dim-label");
        point_label.set_hexpand(true);
        point_label.set_halign(gtk::Align::Center);
        point_label.set_ellipsize(gtk::pango::EllipsizeMode::End);
        point_label.set_tooltip_text(Some(&match model.unit.as_deref() {
            Some(unit) => format!("{name}: {value:.2} {unit}"),
            None => format!("{name}: {value:.2}"),
        }));
        labels.append(&point_label);
    }
    block.append(&labels);
    block.upcast()
}

fn color_components(color: &str) -> (f64, f64, f64) {
    let value = color.trim_start_matches('#');
    if value.len() == 6 && value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        let channel = |range| u8::from_str_radix(&value[range], 16).unwrap_or(99) as f64 / 255.0;
        (channel(0..2), channel(2..4), channel(4..6))
    } else {
        (0.39, 0.40, 0.96)
    }
}

fn label(text: &str, class: &str) -> gtk::Label {
    let label = gtk::Label::new(Some(text));
    label.add_css_class(class);
    label
}

fn clear_box(container: &gtk::Box) {
    while let Some(child) = container.first_child() {
        container.remove(&child);
    }
}
