//! SVG loader negative test — separate from desktop-file validation.
//! Documents the failure mode when librsvg2-common is absent: GDK
//! `Texture::from_bytes` fails for SVG bytes and `provider_mark` falls back
//! to a text label. Only meaningful when the loader is absent.
//! Ignored in CI where librsvg2-common is installed. Must FAIL (not pass as
//! positive decode) when the SVG loader decodes the bytes, because the
//! precondition (loader absent) is then unmet.

use gtk::prelude::*;

#[test]
#[ignore = "requires librsvg2-common ABSENT (negative precondition); run manually without loader"]
fn bundled_svg_fails_gracefully_without_loader() {
    gtk::init().expect("GTK display for SVG negative test");
    let claude_brand = include_bytes!("../../assets/provider_icons/Brand-ProviderIcon-claude.svg");
    let decoded = gtk::gdk::Texture::from_bytes(&gtk::glib::Bytes::from_static(claude_brand));
    // Negative precondition: SVG must fail to decode without the loader.
    assert!(
        decoded.is_err(),
        "precondition failed: SVG decoded; librsvg loader is present, negative path not exercised"
    );
    let fallback = codexbar_gtk_native::icons::provider_mark("claude", "Claude", "#D97757", 30);
    assert_eq!(fallback.type_().name(), "GtkLabel");
}
