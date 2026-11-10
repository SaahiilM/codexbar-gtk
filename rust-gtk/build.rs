use std::{env, fs, path::PathBuf};

fn main() {
    let manifest = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("manifest dir"));
    let source = manifest.join("../codexbar_gtk/assets/provider_icons");
    println!("cargo:rerun-if-changed={}", source.display());
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR")).join("provider_assets.rs");
    let mut files = fs::read_dir(&source)
        .expect("provider icon catalog")
        .map(|entry| entry.expect("provider icon entry").path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.starts_with("ProviderIcon-") || name.starts_with("Brand-ProviderIcon-")
                })
                && matches!(
                    path.extension().and_then(|ext| ext.to_str()),
                    Some("svg" | "png")
                )
        })
        .collect::<Vec<_>>();
    files.sort();

    let mut generated = String::from("pub static PROVIDER_ASSETS: &[(&str, &[u8])] = &[\n");
    for file in files {
        let name = file.file_name().unwrap().to_string_lossy();
        println!("cargo:rerun-if-changed={}", file.display());
        generated.push_str(&format!(
            "    ({name:?}, include_bytes!({path:?})),\n",
            path = file.display().to_string(),
        ));
    }
    generated.push_str("];\n");
    fs::write(output, generated).expect("write provider asset index");
}
