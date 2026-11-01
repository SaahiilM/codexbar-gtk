use gtk::prelude::*;

#[test]
#[ignore = "requires an X11/Wayland display; run from the native UI smoke job"]
fn provider_artwork_decodes_and_keeps_text_as_the_accessible_name() {
    gtk::init().expect("GTK display for provider artwork smoke");

    let brand = codexbar_gtk_native::icons::provider_mark("codex", "Codex", "#10A37F", 38);
    assert_eq!(brand.type_().name(), "GtkImage");
    assert_eq!(brand.accessible_role(), gtk::AccessibleRole::Presentation);
    assert_eq!(brand.width_request(), 38);

    let monochrome =
        codexbar_gtk_native::icons::provider_mark("deepseek", "DeepSeek", "#4D6BFE", 30);
    assert_eq!(monochrome.type_().name(), "GtkImage");
    assert_eq!(
        monochrome.accessible_role(),
        gtk::AccessibleRole::Presentation
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
}
