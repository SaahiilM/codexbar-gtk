"""Application CSS.

Built on top of libadwaita's own style classes so the app looks native on
GNOME and still reads well on KDE Plasma.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

CSS = b"""
/* ---------- popover ---------- */
.cb-popup {
  background: alpha(@window_bg_color, 0.98);
  border: 1px solid alpha(currentColor, 0.14);
  border-radius: 14px;
}

.cb-popup-header {
  padding: 12px 14px 8px 14px;
  border-bottom: 1px solid alpha(currentColor, 0.08);
}

.cb-popup-title {
  font-weight: 700;
  font-size: 0.95rem;
}

.cb-popup-scroll {
  padding: 10px 10px 4px 10px;
}

/* ---------- cards ---------- */
.cb-card {
  background: alpha(currentColor, 0.05);
  border: 1px solid alpha(currentColor, 0.10);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 10px;
}

.cb-card:last-child {
  margin-bottom: 0;
}

.cb-card-header {
  margin-bottom: 0;
}

.cb-provider-name {
  font-weight: 700;
  font-size: 1rem;
}

.cb-provider-subtitle {
  font-size: 0.76rem;
  color: alpha(currentColor, 0.55);
}

.cb-plan-badge {
  font-size: 0.70rem;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 999px;
  background: alpha(currentColor, 0.12);
}

/* ---------- meters ---------- */
.cb-metric-title {
  font-size: 0.80rem;
  font-weight: 600;
  color: alpha(currentColor, 0.85);
}

.cb-metric-percent {
  font-size: 0.92rem;
  font-weight: 700;
  font-feature-settings: "tnum";
}

.cb-chip {
  background: alpha(currentColor, 0.09);
  border-radius: 999px;
  padding: 2px 9px 2px 7px;
}

.cb-chip-label {
  font-size: 0.70rem;
  color: alpha(currentColor, 0.75);
}

.cb-chip-warn {
  background: alpha(#e0a030, 0.18);
}

.cb-chip-warn .cb-chip-label {
  color: #e0a030;
}

.cb-chip-crit {
  background: alpha(#e05252, 0.18);
}

.cb-chip-crit .cb-chip-label {
  color: #e05252;
}

.cb-meter {
  min-height: 12px;
  border-radius: 6px;
}

.cb-meter trough {
  min-height: 12px;
  border-radius: 6px;
  background: alpha(currentColor, 0.12);
}

.cb-meter progress {
  min-height: 12px;
  border-radius: 6px;
}

/* ---------- key/value rows ---------- */
.cb-kv-key {
  font-size: 0.78rem;
  color: alpha(currentColor, 0.55);
}

.cb-kv-value {
  font-size: 0.78rem;
  font-weight: 600;
}

/* ---------- dashboard ---------- */
.cb-dash-grid {
  padding: 14px 16px 20px 16px;
}

.cb-tile {
  background: alpha(currentColor, 0.05);
  border: 1px solid alpha(currentColor, 0.10);
  border-radius: 14px;
  padding: 12px 14px;
}

.cb-tile-value {
  font-size: 1.5rem;
  font-weight: 700;
  font-feature-settings: "tnum";
}

.cb-tile-label {
  font-size: 0.74rem;
  font-weight: 600;
  color: alpha(currentColor, 0.60);
}

.cb-tile-caption {
  font-size: 0.70rem;
  color: alpha(currentColor, 0.45);
}

.cb-tile-icon {
  color: alpha(currentColor, 0.55);
}

.cb-section-label {
  font-size: 0.70rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: alpha(currentColor, 0.50);
}

.cb-chart-bar {
  background: #10A37F;
  border-radius: 6px 6px 3px 3px;
  min-height: 4px;
  margin: 0 2px;
}

.cb-chart-value {
  font-size: 0.66rem;
  color: alpha(currentColor, 0.55);
  font-feature-settings: "tnum";
}

.cb-chart-label {
  font-size: 0.66rem;
  color: alpha(currentColor, 0.45);
}

.cb-empty {
  color: alpha(currentColor, 0.5);
  padding: 18px 8px;
}

.cb-trend-label {
  font-size: 0.66rem;
  color: alpha(currentColor, 0.4);
}

.cb-error {
  color: #e05252;
  font-size: 0.76rem;
}

/* ---------- overview banner ---------- */
.cb-overview {
  background: alpha(@accent_color, 0.10);
  border: 1px solid alpha(@accent_color, 0.22);
  border-radius: 14px;
  padding: 12px 16px;
  margin-bottom: 14px;
}

.cb-overview-title {
  font-size: 0.95rem;
  font-weight: 700;
}

.cb-overview-sub {
  font-size: 0.76rem;
  color: alpha(currentColor, 0.62);
}

/* ---------- sessions ---------- */
.cb-session {
  padding: 10px 12px;
  border-radius: 10px;
  background: alpha(currentColor, 0.04);
  margin-bottom: 8px;
}

.cb-session-title {
  font-size: 0.86rem;
  font-weight: 600;
}

.cb-session-path {
  font-size: 0.72rem;
  color: alpha(currentColor, 0.5);
  font-family: monospace;
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
