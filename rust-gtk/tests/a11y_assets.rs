use gtk::prelude::*;

#[test]
#[ignore = "requires an X11/Wayland display; run from the native UI smoke job"]
fn provider_artwork_decodes_outside_repository_cwd_and_keeps_textual_fallback() {
    gtk::init().expect("GTK display for provider artwork smoke");
    let original_dir = std::env::current_dir().expect("test working directory");
    std::env::set_current_dir(std::env::temp_dir()).expect("switch to unrelated working directory");

    let codex_brand =
        include_bytes!("../../codexbar_gtk/assets/provider_icons/Brand-ProviderIcon-codex.png");
    let codex_texture = gtk::gdk::Texture::from_bytes(&gtk::glib::Bytes::from_static(codex_brand))
        .unwrap_or_else(|error| panic!("GDK failed to decode bundled Codex brand PNG: {error}"));
    assert_eq!(codex_texture.width(), 104);

    let claude_brand =
        include_bytes!("../../codexbar_gtk/assets/provider_icons/Brand-ProviderIcon-claude.svg");
    let claude_texture = gtk::gdk::Texture::from_bytes(&gtk::glib::Bytes::from_static(
        claude_brand,
    ))
    .unwrap_or_else(|error| {
        panic!("GDK failed to decode bundled Claude brand SVG; check librsvg loader: {error}")
    });
    assert!(claude_texture.width() > 0);

    let brand = codexbar_gtk_native::icons::provider_mark("codex", "Codex", "#10A37F", 38);
    assert_eq!(brand.type_().name(), "GtkImage");
    assert_eq!(brand.accessible_role(), gtk::AccessibleRole::Presentation);
    assert_eq!(brand.width_request(), 38);
    let brand_texture = brand
        .downcast::<gtk::Image>()
        .expect("preferred Codex brand image")
        .paintable()
        .expect("preferred Codex brand texture")
        .downcast::<gtk::gdk::Texture>()
        .expect("preferred Codex brand texture type");
    assert_eq!(
        brand_texture.width(),
        104,
        "Codex should decode its 104px bundled brand PNG instead of silently using the SVG fallback"
    );

    let monochrome =
        codexbar_gtk_native::icons::provider_mark("deepseek", "DeepSeek", "#4D6BFE", 30);
    assert_eq!(monochrome.type_().name(), "GtkImage");
    assert_eq!(
        monochrome.accessible_role(),
        gtk::AccessibleRole::Presentation
    );

    let svg_brand = codexbar_gtk_native::icons::provider_mark("claude", "Claude", "#D97757", 30);
    assert_eq!(
        svg_brand.type_().name(),
        "GtkImage",
        "bundled brand SVG requires the GDK SVG loader"
    );

    let fallback = codexbar_gtk_native::icons::provider_mark(
        "not-in-the-catalog",
        "Unknown provider",
        "#123456",
        30,
    );
    assert_eq!(fallback.type_().name(), "GtkLabel");
    assert!(fallback
        .css_classes()
        .contains(&"cb-provider-artwork-fallback".into()));
    let fallback = fallback
        .downcast::<gtk::Label>()
        .expect("unknown provider initial label");
    assert_eq!(fallback.text(), "U");
    assert_eq!(
        fallback.accessible_role(),
        gtk::AccessibleRole::Presentation
    );
    std::env::set_current_dir(original_dir).expect("restore test working directory");
}
