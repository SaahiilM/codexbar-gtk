use codexbar_core::providers;
use pyo3::prelude::*;

#[pyfunction]
fn canonical_id(provider_id: &str) -> String {
    providers::canonical_id(provider_id).to_owned()
}

#[pyfunction]
fn display_name(provider_id: &str) -> String {
    providers::display_name(provider_id)
}

#[pyfunction]
fn short_name(provider_id: &str) -> String {
    providers::short_name(provider_id)
}

#[pyfunction]
fn accent_color(provider_id: &str) -> String {
    providers::accent_color(provider_id).to_owned()
}

#[pyfunction]
fn all_provider_ids() -> Vec<String> {
    providers::all_provider_ids()
        .into_iter()
        .map(str::to_owned)
        .collect()
}

#[pymodule]
fn _rust_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(canonical_id, module)?)?;
    module.add_function(wrap_pyfunction!(display_name, module)?)?;
    module.add_function(wrap_pyfunction!(short_name, module)?)?;
    module.add_function(wrap_pyfunction!(accent_color, module)?)?;
    module.add_function(wrap_pyfunction!(all_provider_ids, module)?)?;
    module.add_function(wrap_pyfunction!(backend_name, module)?)?;
    Ok(())
}

#[pyfunction]
fn backend_name() -> &'static str {
    "rust"
}
