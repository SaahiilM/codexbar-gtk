"""Small, read-only check for the latest GTK client version on GitHub."""

from __future__ import annotations

from dataclasses import dataclass
import math
from urllib.error import URLError
from urllib.request import Request, urlopen

VERSION_URL = "https://raw.githubusercontent.com/SaahiilM/codexbar-gtk/main/VERSION"
PROJECT_URL = "https://github.com/SaahiilM/codexbar-gtk"
MAX_BYTES = 4096


@dataclass(frozen=True)
class UpdateCheckRequest:
    """Current client metadata and injectable source for one read-only check."""

    current_version: str
    current_build: int
    timeout: float = 5.0
    url: str = VERSION_URL


@dataclass(frozen=True)
class UpdateCheckResult:
    """Typed, read-only result for the update dialog to render."""

    relation: str
    latest_version: str
    latest_build: int
    current_version: str | None = None
    current_build: int | None = None


class UpdateCheckError(Exception):
    """Stable and sanitized failure returned by the update service adapter."""

    def __init__(self, kind: str):
        self.kind = kind
        messages = {
            "invalid_marker": "The public version marker is invalid.",
            "oversized": "The public version marker exceeds 4096 bytes.",
            "timeout": "The public version check timed out.",
            "network": "The public version check failed.",
        }
        super().__init__(messages.get(kind, messages["network"]))


def parse_version_file(contents: str) -> tuple[str, int]:
    """Parse the client's ``VERSION`` file into marketing version and build."""
    values: dict[str, str] = {}
    for line in contents.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    marketing = values.get("MARKETING_VERSION", "")
    build_text = values.get("CURRENT_PROJECT_VERSION", "")
    if not marketing or not build_text.isdigit():
        raise ValueError("the remote VERSION file is incomplete")
    parts = marketing.split(".")
    if not all(part.isdigit() for part in parts):
        raise ValueError("the remote marketing version is invalid")
    return marketing, int(build_text)


def version_key(version: str, build: int) -> tuple[tuple[int, ...], int]:
    """Return a numeric ordering key for GTK client releases."""
    parts = tuple(int(part) for part in version.split("."))
    return parts, build


def check_latest_version(timeout: float = 5.0) -> tuple[str, int]:
    """Fetch the public client version marker; this never downloads or installs code."""
    request = Request(
        VERSION_URL,
        headers={"User-Agent": "CodexBar-GTK-update-check", "Accept": "text/plain"},
    )
    with urlopen(request, timeout=timeout) as response:
        contents = response.read(4096).decode("utf-8")
    return parse_version_file(contents)


def check_for_update(request: UpdateCheckRequest) -> UpdateCheckResult:
    """Fetch and compare the public marker; callers only render this result.

    ``url`` is injectable for loopback fixtures. The Rust opt-in UI calls the
    B12 service through the central controller facade; this function remains
    the Python parity implementation and never dispatches to a module-level
    Rust service.
    """
    if not math.isfinite(request.timeout) or request.timeout <= 0:
        raise UpdateCheckError("timeout")
    http_request = Request(
        request.url,
        headers={"User-Agent": "CodexBar-GTK-update-check", "Accept": "text/plain"},
    )
    try:
        with urlopen(http_request, timeout=min(request.timeout, 300.0)) as response:
            contents = response.read(MAX_BYTES + 1)
    except TimeoutError:
        raise UpdateCheckError("timeout") from None
    except (OSError, URLError):
        raise UpdateCheckError("network") from None
    if len(contents) > MAX_BYTES:
        raise UpdateCheckError("oversized")
    try:
        latest_version, latest_build = parse_version_file(contents.decode("utf-8"))
        relation = compare_versions(
            (request.current_version, int(request.current_build)),
            (latest_version, latest_build),
        )
    except (UnicodeDecodeError, ValueError):
        raise UpdateCheckError("invalid_marker") from None
    return UpdateCheckResult(
        relation,
        latest_version,
        latest_build,
        request.current_version,
        request.current_build,
    )


def compare_versions(current: tuple[str, int], latest: tuple[str, int]) -> str:
    """Apply the update relation policy shared by the UI and Rust service."""
    current_key = version_key(*current)
    latest_key = version_key(*latest)
    if latest_key > current_key:
        return "available"
    if latest_key < current_key:
        return "ahead"
    return "current"
