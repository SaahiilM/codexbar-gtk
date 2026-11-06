//! ELF linkage inspection only — does NOT prove C02 Python-free runtime.
//! C02 additionally requires the interpreter, GI typelibs and PyO3 extension
//! to be absent/inaccessible at absolute paths during a live launch; that
//! environment isolation is not implemented here and C02 is NOT proven by
//! this test. The smoke probe captures ELF/process evidence but does not
//! isolate the interpreter either.

use std::path::Path;

#[test]
fn native_binary_has_no_python_linkage() {
    let exe = Path::new(env!("CARGO_BIN_EXE_codexbar-gtk-native"));
    let output = std::process::Command::new("readelf")
        .args(["-d", exe.to_str().expect("utf8 exe path")])
        .output()
        .expect("readelf available");
    assert!(
        output.status.success(),
        "readelf must succeed for linkage inspection; stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8_lossy(&output.stdout).to_lowercase();
    assert!(
        !text.contains("libpython") && !text.contains("python3") && !text.contains("pyo3"),
        "native binary must not link Python/PyO3: {text}"
    );
    assert!(
        text.contains("libgtk-4") || text.contains("libgtk"),
        "missing GTK linkage: {text}"
    );
}
