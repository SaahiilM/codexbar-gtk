//! GTK rendering for the native dashboard projection.

use crate::dashboard::{DashboardModel, MeterSeverity, ProviderCardModel, QuotaWindowModel};
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
    row.append(&meter);

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
    row.upcast()
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
