"""Load the optional PyO3 extension when Rust-backed logic is explicitly enabled."""

from __future__ import annotations

import os
from types import ModuleType

_USE_RUST_CORE = os.environ.get("CODEXBAR_RUST_CORE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_RUST_CORE: ModuleType | None = None
if _USE_RUST_CORE:
    try:
        from . import _rust_core as _RUST_CORE
    except ImportError as exc:
        raise RuntimeError(
            "CODEXBAR_RUST_CORE is enabled, but the Rust extension is unavailable; "
            "run scripts/build-rust-core.sh first"
        ) from exc


def extension() -> ModuleType | None:
    """Return the Rust extension, or `None` when Python mode is active."""
    return _RUST_CORE


def backend_name() -> str:
    """Return the business-logic backend selected for this Python process."""
    return "rust" if _RUST_CORE is not None else "python"


def reject_unsupported(
    core: ModuleType | None, operation: str, detail: str | None = None
) -> None:
    """Fail closed when a Rust-mode adapter cannot represent an input."""
    if core is not None:
        requirement = detail or "input type or value range is outside the supported representation"
        raise TypeError(f"{operation} cannot use this input in Rust opt-in: {requirement}")
