//! Bundled provider artwork and side-effect-free SNI pixmap rendering.
//!
//! Provider assets are embedded from the existing, licensed Python catalog at
//! build time. GTK decodes those bytes for card display; all generated SNI
//! pixels come directly from Cairo and are returned in network ARGB order.

use cairo::{Context, Format, ImageSurface};
use codexbar_backend::presentation::TraySummary;
use gtk::{gdk, prelude::*};

mod embedded {
    include!(concat!(env!("OUT_DIR"), "/provider_assets.rs"));
}

const DEFAULT_ACCENT: &str = "#10A37F";

const APP_CSS: &str = r#"
.cb-provider-artwork { min-width: 30px; min-height: 30px; }
.cb-provider-artwork-fallback {
  min-width: 30px;
  min-height: 30px;
  border-radius: 999px;
  background: alpha(currentColor, 0.08);
  color: @window_fg_color;
}
.cb-stat-flow { border: none; background: transparent; }
.cb-dashboard-meter:focus-visible, .cb-heat-cell:focus-visible {
  outline: 2px solid @accent_color;
  outline-offset: 2px;
}
"#;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RequestedSize {
    pub width: u32,
    pub height: u32,
}

/// Install only the small shared set of app classes used by the native GTK
/// renderer; color selection remains with libadwaita and the desktop theme.
pub fn install_theme() {
    let Some(display) = gdk::Display::default() else {
        return;
    };
    let provider = gtk::CssProvider::new();
    provider.load_from_data(APP_CSS);
    gtk::style_context_add_provider_for_display(
        &display,
        &provider,
        gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
    );
}

/// Render the existing presentation projection for the native tray.
///
/// This function only allocates a Cairo surface and returns its pixels. It
/// does not touch GTK state, the filesystem, D-Bus, or application lifecycle.
pub fn render_tray_summary(
    summary: &TraySummary,
    size: RequestedSize,
) -> Option<(i32, i32, Vec<u8>)> {
    let accent = summary.accent_color.as_deref().unwrap_or(DEFAULT_ACCENT);
    match summary.menu_bar_icon_style.as_str() {
        "iconPercent" => render_percent(
            summary.used_percent?,
            accent,
            summary.initial.as_deref().unwrap_or("?"),
            size,
        ),
        _ => Some(render_meter(summary.meter_level, accent, size)),
    }
}

pub fn render_meter(level: Option<u8>, accent: &str, size: RequestedSize) -> (i32, i32, Vec<u8>) {
    let width = size.width.clamp(8, 256) as i32;
    let height = size.height.clamp(8, 256) as i32;
    let surface = ImageSurface::create(Format::ARgb32, width, height).expect("valid icon surface");
    let context = Context::new(&surface).expect("valid Cairo context");
    context.set_operator(cairo::Operator::Clear);
    context.paint().expect("clear icon surface");
    context.set_operator(cairo::Operator::Over);

    let margin = f64::from(width.min(height)) * 0.11;
    let bar_height = f64::from(height) * 0.44;
    let bar_width = (f64::from(width) - margin * 2.0).max(1.0);
    let radius = bar_height.min(bar_width) / 2.0;
    let top = (f64::from(height) - bar_height) / 2.0;
    let level = level.map(|value| value.min(9));
    let color = if level.is_some_and(|value| value >= 9) {
        "#e05a5a"
    } else if level.is_some_and(|value| value >= 7) {
        "#e0a030"
    } else {
        accent
    };

    context.set_source_rgba(1.0, 1.0, 1.0, 0.16);
    rounded_rect(&context, margin, top, bar_width, bar_height, radius);
    context.fill().expect("paint meter track");

    if let Some(level) = level {
        let fraction = f64::from(level) / 9.0;
        let filled = (bar_height * 0.35).max(bar_width * fraction).min(bar_width);
        let (red, green, blue) = hex_color(color);
        context.set_source_rgb(red, green, blue);
        rounded_rect(
            &context,
            margin,
            top,
            filled,
            bar_height,
            radius.min(filled / 2.0),
        );
        context.fill().expect("paint meter fill");
    }

    context.set_source_rgba(1.0, 1.0, 1.0, 0.85);
    context.set_line_width((f64::from(width.min(height)) * 0.055).max(1.0));
    rounded_rect(&context, margin, top, bar_width, bar_height, radius);
    context.stroke().expect("stroke meter outline");

    drop(context);
    surface.flush();
    cairo_pixels(surface, width, height)
}

fn render_percent(
    percent: f64,
    accent: &str,
    initial: &str,
    size: RequestedSize,
) -> Option<(i32, i32, Vec<u8>)> {
    if !percent.is_finite() {
        return None;
    }
    let width = size.width.clamp(8, 256) as i32;
    let height = size.height.clamp(8, 256) as i32;
    let surface = ImageSurface::create(Format::ARgb32, width, height).ok()?;
    let context = Context::new(&surface).ok()?;
    context.set_operator(cairo::Operator::Clear);
    context.paint().ok()?;
    context.set_operator(cairo::Operator::Over);
    let (red, green, blue) = hex_color(accent);

    context.set_source_rgb(red, green, blue);
    context.select_font_face("Sans", cairo::FontSlant::Normal, cairo::FontWeight::Bold);
    context.set_font_size(f64::from(height) * 0.52);
    let initial = initial.chars().next().unwrap_or('?').to_string();
    let initial_extents = context.text_extents(&initial).ok()?;
    let initial_x =
        (f64::from(width) - initial_extents.width()) / 2.0 - initial_extents.x_bearing();
    let initial_y =
        (f64::from(height) - initial_extents.height()) / 2.0 - initial_extents.y_bearing() + 1.0;
    context.move_to(initial_x, initial_y);
    context.show_text(&initial).ok()?;

    context.set_font_size(f64::from(height) * 0.30);
    let label = format!("{percent:.0}%");
    let extents = context.text_extents(&label).ok()?;
    let x = (f64::from(width) - extents.width()) / 2.0 - extents.x_bearing();
    context.set_source_rgba(1.0, 1.0, 1.0, 0.95);
    context.move_to(x, f64::from(height) - 1.0);
    context.show_text(&label).ok()?;

    drop(context);
    surface.flush();
    Some(cairo_pixels(surface, width, height))
}

fn rounded_rect(context: &Context, x: f64, y: f64, width: f64, height: f64, radius: f64) {
    let radius = radius.min(width / 2.0).min(height / 2.0).max(0.0);
    context.new_sub_path();
    context.arc(
        x + width - radius,
        y + radius,
        radius,
        -std::f64::consts::FRAC_PI_2,
        0.0,
    );
    context.arc(
        x + width - radius,
        y + height - radius,
        radius,
        0.0,
        std::f64::consts::FRAC_PI_2,
    );
    context.arc(
        x + radius,
        y + height - radius,
        radius,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::PI,
    );
    context.arc(
        x + radius,
        y + radius,
        radius,
        std::f64::consts::PI,
        3.0 * std::f64::consts::FRAC_PI_2,
    );
    context.close_path();
}

fn cairo_pixels(mut surface: ImageSurface, width: i32, height: i32) -> (i32, i32, Vec<u8>) {
    let stride = surface.stride() as usize;
    let data = surface.data().expect("unshared icon surface");
    let mut output = Vec::with_capacity((width * height * 4) as usize);
    for y in 0..height as usize {
        let row = &data[y * stride..y * stride + width as usize * 4];
        for pixel in row.as_chunks::<4>().0 {
            // Cairo ARGB32 is native-endian premultiplied BGRA on our GTK targets;
            // SNI requires network byte order ARGB, matching the Python reference.
            output.extend_from_slice(&[pixel[3], pixel[2], pixel[1], pixel[0]]);
        }
    }
    (width, height, output)
}

fn hex_color(value: &str) -> (f64, f64, f64) {
    let text = value.trim().strip_prefix('#').unwrap_or(value.trim());
    if text.len() == 6 && text.is_ascii() {
        if let (Ok(red), Ok(green), Ok(blue)) = (
            u8::from_str_radix(&text[0..2], 16),
            u8::from_str_radix(&text[2..4], 16),
            u8::from_str_radix(&text[4..6], 16),
        ) {
            return (
                f64::from(red) / 255.0,
                f64::from(green) / 255.0,
                f64::from(blue) / 255.0,
            );
        }
    }
    (16.0 / 255.0, 163.0 / 255.0, 127.0 / 255.0)
}

fn asset(name: &str) -> Option<&'static [u8]> {
    embedded::PROVIDER_ASSETS
        .iter()
        .find_map(|(candidate, bytes)| (*candidate == name).then_some(*bytes))
}

fn icon_id(provider_id: &str) -> String {
    match provider_id.trim().to_ascii_lowercase().as_str() {
        "alibabatokenplan" => "alibaba".to_owned(),
        "azureopenai" => "codex".to_owned(),
        "moonshot" => "kimi".to_owned(),
        "openai" => "codex".to_owned(),
        other => codexbar_core::providers::canonical_id(other).to_owned(),
    }
}

/// Build a square provider mark. Missing or undecodable artwork falls back to
/// the provider's initial, preserving Python's visible fallback behavior.
pub fn provider_mark(
    provider_id: &str,
    display_name: &str,
    accent: &str,
    size: i32,
) -> gtk::Widget {
    let id = icon_id(provider_id);
    let brand = ["svg", "png"]
        .into_iter()
        .find_map(|extension| asset(&format!("Brand-ProviderIcon-{id}.{extension}")));
    let mono = asset(&format!("ProviderIcon-{id}.svg"));
    let loaded = brand
        .map(|bytes| load_texture(bytes, None))
        .or_else(|| mono.map(|bytes| load_texture(bytes, Some(accent))))
        .flatten();
    if let Some(texture) = loaded {
        let image = gtk::Image::from_paintable(Some(&texture));
        image.set_pixel_size(size);
        image.set_size_request(size, size);
        image.set_halign(gtk::Align::Center);
        image.set_valign(gtk::Align::Center);
        image.add_css_class("cb-provider-artwork");
        image.set_tooltip_text(Some(display_name));
        image.set_accessible_role(gtk::AccessibleRole::Presentation);
        return image.upcast();
    }
    let letter = display_name
        .chars()
        .next()
        .unwrap_or('?')
        .to_uppercase()
        .to_string();
    let fallback = gtk::Label::new(Some(&letter));
    fallback.add_css_class("cb-provider-artwork-fallback");
    fallback.add_css_class("title-3");
    fallback.set_size_request(size, size);
    fallback.set_halign(gtk::Align::Center);
    fallback.set_valign(gtk::Align::Center);
    fallback.set_accessible_role(gtk::AccessibleRole::Presentation);
    fallback.upcast()
}

fn load_texture(bytes: &'static [u8], tint: Option<&str>) -> Option<gdk::Texture> {
    let encoded = glib::Bytes::from_static(bytes);
    let texture = gdk::Texture::from_bytes(&encoded).ok()?;
    let Some(tint) = tint else {
        return Some(texture);
    };
    let width = texture.width();
    let height = texture.height();
    let stride = width as usize * 4;
    let mut pixels = vec![0; stride * height as usize];
    texture.download(&mut pixels, stride);
    let (red, green, blue) = hex_color(tint);
    for pixel in pixels.as_chunks_mut::<4>().0 {
        let alpha = f64::from(pixel[3]) / 255.0;
        pixel[0] = (blue * alpha * 255.0).round() as u8;
        pixel[1] = (green * alpha * 255.0).round() as u8;
        pixel[2] = (red * alpha * 255.0).round() as u8;
    }
    let bytes = glib::Bytes::from_owned(pixels);
    Some(
        gdk::MemoryTexture::new(
            width,
            height,
            gdk::MemoryFormat::B8g8r8a8Premultiplied,
            &bytes,
            stride,
        )
        .upcast(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use codexbar_backend::presentation::TraySummary;

    fn summary(style: &str) -> TraySummary {
        TraySummary {
            backend_sequence: 0,
            backend_status: "ready".into(),
            backend_error: None,
            available: true,
            unified_icon_source: "highest".into(),
            menu_bar_icon_style: style.into(),
            switcher_rows_option: "progress".into(),
            title: "CodexBar · Codex".into(),
            tooltip_rows: vec![],
            overflow_count: 0,
            selected_provider_id: Some("codex".into()),
            selected_window_key: Some("primary".into()),
            used_percent: Some(42.0),
            meter_level: Some(4),
            accent_color: Some("#10A37F".into()),
            initial: Some("C".into()),
            switcher_rows: vec![],
        }
    }

    #[test]
    fn tray_renderer_honors_style_and_requested_dimensions() {
        let mut rendered = Vec::new();
        for (style, requested) in [
            (
                "meter",
                RequestedSize {
                    width: 16,
                    height: 24,
                },
            ),
            (
                "iconPercent",
                RequestedSize {
                    width: 32,
                    height: 32,
                },
            ),
            (
                "iconPercent",
                RequestedSize {
                    width: 64,
                    height: 64,
                },
            ),
        ] {
            let pixmap = render_tray_summary(&summary(style), requested).unwrap();
            assert_eq!(
                (pixmap.0, pixmap.1),
                (requested.width as i32, requested.height as i32)
            );
            assert_eq!(pixmap.2.len(), pixmap.0 as usize * pixmap.1 as usize * 4);
            assert_eq!(&pixmap.2[..4], &[0, 0, 0, 0]);
            rendered.push(pixmap);
        }
        assert_ne!(
            rendered[0].2, rendered[1].2,
            "meter and percentage styles differ"
        );
        assert_ne!(
            rendered[1].2, rendered[2].2,
            "requested 1x/2x rasters differ"
        );
    }

    #[test]
    fn percentage_style_keeps_unknown_usage_without_fabricating_pixels() {
        let mut state = summary("iconPercent");
        state.used_percent = None;
        assert!(render_tray_summary(
            &state,
            RequestedSize {
                width: 32,
                height: 32
            }
        )
        .is_none());
    }

    #[test]
    fn unknown_meter_has_no_accent_fill() {
        let (_, _, pixels) = render_meter(
            None,
            "#10A37F",
            RequestedSize {
                width: 32,
                height: 32,
            },
        );
        assert!(!pixels
            .as_chunks::<4>()
            .0
            .iter()
            .any(|pixel| pixel[1..] == [16, 163, 127]));
        assert!(pixels.as_chunks::<4>().0.iter().any(|pixel| pixel[0] > 0));
    }

    #[test]
    fn embedded_catalog_has_python_aliases_and_provider_fallback_assets() {
        assert!(asset("Brand-ProviderIcon-codex.png").is_some());
        assert!(asset("ProviderIcon-kimi.svg").is_some());
        assert!(asset("ProviderIcon-deepseek.svg").is_some());
        assert!(asset("Brand-ProviderIcon-deepseek.svg").is_none());
        assert_eq!(icon_id("azureopenai"), "codex");
        assert_eq!(icon_id("moonshot"), "kimi");
        assert_eq!(icon_id("alibabatokenplan"), "alibaba");
        assert!(embedded::PROVIDER_ASSETS.len() >= 107);
        assert_eq!(icon_id("not-in-the-catalog"), "not-in-the-catalog");
    }
}
