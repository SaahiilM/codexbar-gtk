"""Provider artwork copied from the upstream CodexBar resource catalog."""

from __future__ import annotations

from pathlib import Path

from .providers import canonical_id

ASSET_DIR = Path(__file__).with_name("assets") / "provider_icons"

# These provider descriptors intentionally reuse another provider's upstream icon.
ICON_ALIASES = {
    "alibabatokenplan": "alibaba",
    "azureopenai": "codex",
    "moonshot": "kimi",
    "openai": "codex",
}


def provider_icon_path(provider_id: str, *, prefer_brand: bool = True) -> Path | None:
    """Return the best bundled upstream icon for a provider, if one exists."""
    provider_id = canonical_id(provider_id.strip().lower())
    icon_id = ICON_ALIASES.get(provider_id, provider_id)

    if prefer_brand:
        for extension in ("svg", "png"):
            brand = ASSET_DIR / f"Brand-ProviderIcon-{icon_id}.{extension}"
            if brand.is_file():
                return brand

    monochrome = ASSET_DIR / f"ProviderIcon-{icon_id}.svg"
    return monochrome if monochrome.is_file() else None
