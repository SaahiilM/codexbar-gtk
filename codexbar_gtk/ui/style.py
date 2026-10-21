"""Application CSS.

Kept deliberately small and explicit so the popover, dashboard and settings share
one visual language.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

CSS = b"""
/* ---------- popover ---------- */
.cb-popup {
  background: alpha(@window_bg_color, 0.98);
  border: 1px solid alpha(currentColor, 0.12);
  border-radius: 14px;
}

.cb-popup-header {
  padding: 10px 14px 6px 14px;
}

.cb-popup-title {
  font-weight: 700;
  font-size: 0.95rem;
}

.cb-popup-scroll {
  padding: 0 6px 6px 6px;
}

/* ---------- cards ---------- */
.cb-card {
  background: alpha(currentColor, 0.045);
  border: 1px solid alpha(currentColor, 0.09);
  border-radius: 12px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.cb-card:last-child {
  margin-bottom: 2px;
}

.cb-card-header {
  margin-bottom: 8px;
}

.cb-provider-name {
  font-weight: 700;
  font-size: 0.92rem;
}

.cb-provider-subtitle {
  font-size: 0.74rem;
  color: alpha(currentColor, 0.6);
}

.cb-plan-badge {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: alpha(currentColor, 0.10);
}

.cb-metric-title {
  font-size: 0.78rem;
  font-weight: 600;
}

.cb-metric-percent {
  font-size: 0.78rem;
  font-weight: 700;
  font-feature-settings: "tnum";
}

.cb-metric-detail {
  font-size: 0.70rem;
  color: alpha(currentColor, 0.65);
}

.cb-metric-detail-warn {
  color: #e0a030;
}

.cb-metric-detail-crit {
  color: #e05a5a;
}

.cb-meter {
  min-height: 8px;
  border-radius: 6px;
}

.cb-meter trough {
  min-height: 8px;
  border-radius: 6px;
  background: alpha(currentColor, 0.12);
}

.cb-meter progress {
  min-height: 8px;
  border-radius: 6px;
  background: @accent_color;
}

.cb-meter.warning progress {
  background: #e0a030;
}

.cb-meter.critical progress {
  background: #e05a5a;
}

.cb-section-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: alpha(currentColor, 0.55);
}

.cb-error {
  color: #e05a5a;
  font-size: 0.75rem;
}

.cb-status-dot {
  border-radius: 999px;
  min-width: 8px;
  min-height: 8px;
}

.cb-kv {
  font-size: 0.74rem;
}

.cb-kv-key {
  color: alpha(currentColor, 0.6);
}

.cb-kv-value {
  font-weight: 600;
}

/* ---------- dashboard ---------- */
.cb-dash-grid {
  padding: 12px;
}

.cb-tile {
  background: alpha(currentColor, 0.045);
  border: 1px solid alpha(currentColor, 0.09);
  border-radius: 14px;
  padding: 14px 16px;
}

.cb-tile-value {
  font-size: 1.6rem;
  font-weight: 700;
  font-feature-settings: "tnum";
}

.cb-tile-label {
  font-size: 0.75rem;
  color: alpha(currentColor, 0.65);
}

.cb-chart-bar {
  background: alpha(@accent_color, 0.75);
  border-radius: 4px 4px 0 0;
  min-height: 4px;
}

.cb-empty {
  color: alpha(currentColor, 0.55);
  padding: 24px;
}

.cb-mono {
  font-family: monospace;
  font-feature-settings: "tnum";
}
"""


def apply_theme() -> None:
    """Install the application stylesheet and follow the system colour scheme."""
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)

    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        _apply_color_scheme()


def _apply_color_scheme() -> None:
    """Mirror the desktop's dark/light preference into libadwaita."""
    try:
        from gi.repository import Adw, Gio

        settings = Gio.Settings.new("org.gnome.desktop.interface")
        dark = settings.get_string("color-scheme") == "prefer-dark"
        manager = Adw.StyleManager.get_default()
        manager.set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.DEFAULT
        )
        # libadwaita warns when the GTK setting is set; it is redundant here.
        gtk_settings = Gtk.Settings.get_default()
        gtk_settings.set_property("gtk-application-prefer-dark-theme", False)
    except Exception:
        pass
