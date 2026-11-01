//! Compact native panel rendering over the dashboard's shared projection.

use crate::{
    dashboard::{DashboardModel, ProviderCardModel, QuotaWindowModel},
    dashboard_widget,
};
use gtk::prelude::*;

pub struct PanelView {
    root: gtk::Box,
    status: gtk::Label,
    error: gtk::Label,
    loading: gtk::Label,
    empty: gtk::Label,
    providers: gtk::Box,
}

impl PanelView {
    pub fn new() -> Self {
        let root = gtk::Box::new(gtk::Orientation::Vertical, 0);
        root.add_css_class("cb-panel");

        let header = gtk::Box::new(gtk::Orientation::Horizontal, 6);
        header.set_margin_top(8);
        header.set_margin_bottom(8);
        header.set_margin_start(10);
        header.set_margin_end(10);
        let title = gtk::Label::new(Some("CodexBar"));
        title.add_css_class("title-3");
        title.set_xalign(0.0);
        title.set_hexpand(true);
        header.append(&title);
        header.append(&action_button("Refresh", "app.refresh"));
        header.append(&action_button("Dashboard", "app.dashboard"));
        header.append(&action_button("Settings", "app.settings"));
        header.append(&action_button("Close", "app.panel"));
        root.append(&header);

        let status = gtk::Label::new(Some("Loading provider data…"));
        status.set_xalign(0.0);
        status.add_css_class("dim-label");
        status.set_margin_start(12);
        status.set_margin_end(12);
        status.set_margin_bottom(6);
        root.append(&status);

        let error = gtk::Label::new(None);
        error.add_css_class("error");
        error.set_xalign(0.0);
        error.set_wrap(true);
        error.set_margin_start(12);
        error.set_margin_end(12);
        error.set_margin_bottom(8);
        error.set_visible(false);
        root.append(&error);

        let scroller = gtk::ScrolledWindow::new();
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        scroller.set_vexpand(true);
        scroller.set_propagate_natural_height(true);
        scroller.set_max_content_height(520);
        let content = gtk::Box::new(gtk::Orientation::Vertical, 8);
        content.set_margin_start(10);
        content.set_margin_end(10);
        content.set_margin_bottom(10);

        let loading = gtk::Label::new(Some("Waiting for the first provider refresh…"));
        loading.set_xalign(0.0);
        loading.set_wrap(true);
        loading.set_margin_top(14);
        content.append(&loading);

        let empty = gtk::Label::new(Some("No providers are enabled"));
        empty.set_xalign(0.0);
        empty.set_margin_top(14);
        empty.set_visible(false);
        content.append(&empty);

        let providers = gtk::Box::new(gtk::Orientation::Vertical, 8);
        content.append(&providers);
        scroller.set_child(Some(&content));
        root.append(&scroller);

        let footer = gtk::Box::new(gtk::Orientation::Horizontal, 6);
        footer.set_margin_top(6);
        footer.set_margin_bottom(8);
        footer.set_margin_start(10);
        footer.set_margin_end(10);
        footer.append(&action_button("About", "app.about"));
        let spacer = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        spacer.set_hexpand(true);
        footer.append(&spacer);
        footer.append(&action_button("Quit", "app.quit"));
        root.append(&footer);

        Self {
            root,
            status,
            error,
            loading,
            empty,
            providers,
        }
    }

    pub fn widget(&self) -> gtk::Widget {
        self.root.clone().upcast()
    }

    pub fn render(&self, model: &DashboardModel) {
        self.status.set_text(&model.status);
        if let Some(error) = &model.refresh_error {
            self.error.set_text(error);
            self.error.set_visible(true);
        } else {
            self.error.set_visible(false);
        }
        self.loading.set_visible(model.provider_count == "—");
        self.empty.set_visible(model.empty);
        dashboard_widget::clear_box(&self.providers);
        for provider in &model.providers {
            self.providers.append(&compact_provider_card(provider));
        }
    }

    pub fn show_backend_start_error(&self) {
        self.status.set_text("Backend worker could not start");
        self.error.set_text(
            "The native backend could not start. Check the local CLI setup and try again.",
        );
        self.error.set_visible(true);
        self.loading.set_visible(false);
    }
}

impl Default for PanelView {
    fn default() -> Self {
        Self::new()
    }
}

fn action_button(label: &str, action: &str) -> gtk::Button {
    let button = gtk::Button::with_label(label);
    button.add_css_class("flat");
    button.set_action_name(Some(action));
    button
}

fn compact_provider_card(model: &ProviderCardModel) -> gtk::Widget {
    let frame = gtk::Frame::new(None);
    frame.add_css_class("card");
    frame.set_accessible_role(gtk::AccessibleRole::Group);
    frame.update_property(&[
        gtk::accessible::Property::Label(&model.name),
        gtk::accessible::Property::Description(&model.subtitle),
    ]);
    let body = gtk::Box::new(gtk::Orientation::Vertical, 6);
    body.set_margin_top(9);
    body.set_margin_bottom(9);
    body.set_margin_start(11);
    body.set_margin_end(11);

    let header = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    header.append(&crate::icons::provider_mark(
        &model.provider_id,
        &model.name,
        &model.accent,
        30,
    ));
    let name = gtk::Label::new(Some(&model.name));
    name.add_css_class("heading");
    name.set_xalign(0.0);
    name.set_hexpand(true);
    name.set_ellipsize(gtk::pango::EllipsizeMode::End);
    header.append(&name);
    if let Some(badge) = &model.badge {
        let badge = gtk::Label::new(Some(badge));
        badge.add_css_class("dim-label");
        badge.set_tooltip_text(model.badge_help.as_deref());
        badge.set_ellipsize(gtk::pango::EllipsizeMode::End);
        header.append(&badge);
    }
    body.append(&header);

    if !model.subtitle.is_empty() {
        let subtitle = gtk::Label::new(Some(&model.subtitle));
        subtitle.add_css_class("dim-label");
        subtitle.set_xalign(0.0);
        subtitle.set_ellipsize(gtk::pango::EllipsizeMode::End);
        body.append(&subtitle);
    }

    for window in &model.windows {
        body.append(&compact_quota_row(window));
    }

    let details = [
        model.credits.as_deref().map(|value| ("Credits", value)),
        model.spend.as_deref().map(|value| ("Spend", value)),
        model.balance.as_deref().map(|value| ("Balance", value)),
    ]
    .into_iter()
    .flatten()
    .collect::<Vec<_>>();
    if !details.is_empty() {
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 12);
        for (title, value) in details {
            let block = gtk::Box::new(gtk::Orientation::Vertical, 1);
            let title = gtk::Label::new(Some(title));
            title.add_css_class("caption");
            title.add_css_class("dim-label");
            title.set_xalign(0.0);
            let value = gtk::Label::new(Some(value));
            value.add_css_class("numeric");
            value.set_xalign(0.0);
            block.append(&title);
            block.append(&value);
            row.append(&block);
        }
        body.append(&row);
    }

    if let Some(error) = &model.error {
        let error = gtk::Label::new(Some(error));
        error.add_css_class("error");
        error.set_xalign(0.0);
        error.set_wrap(true);
        body.append(&error);
    }
    frame.set_child(Some(&body));
    frame.upcast()
}

fn compact_quota_row(model: &QuotaWindowModel) -> gtk::Widget {
    // Share the dashboard meter renderer, omitting dashboard-only trends and targets.
    dashboard_widget::quota_row(model, true)
}
