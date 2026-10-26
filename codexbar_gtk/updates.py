"""Small, read-only check for the latest GTK client version on GitHub."""

from __future__ import annotations

from urllib.request import Request, urlopen

VERSION_URL = "https://raw.githubusercontent.com/SaahiilM/codexbar-gtk/main/VERSION"
PROJECT_URL = "https://github.com/SaahiilM/codexbar-gtk"


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
