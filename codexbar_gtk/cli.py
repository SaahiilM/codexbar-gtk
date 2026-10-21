"""Thin wrapper around the bundled ``codexbar`` CLI.

The CLI owns all provider fetching, authentication and cost scanning. This module
only speaks JSON to it and never duplicates provider logic.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


class CLIError(RuntimeError):
    """Raised when the codexbar CLI cannot be run or returns invalid output."""


@dataclass
class CLIResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ProviderStatusEntry:
    provider_id: str
    enabled: bool
    display_name: str
    is_default: bool = False


def default_cli_path() -> str:
    """Locate the codexbar binary, preferring the one shipped next to the desktop app."""
    env = os.environ.get("CODEXBAR_CLI")
    if env:
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "bin", "codexbar"),
        os.path.join(here, "..", "..", "bin", "codexbar"),
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    for candidate in ("codexbar", "CodexBarCLI"):
        found = shutil.which(candidate)
        if found:
            return found

    # Common install location used by the upstream Linux installer.
    fallback = os.path.expanduser("~/.local/lib/codexbar-cli/codexbar")
    if os.path.isfile(fallback):
        return fallback
    fallback = os.path.expanduser("~/.local/lib/codexbar-cli/CodexBarCLI")
    if os.path.isfile(fallback):
        return fallback

    return "codexbar"


class CodexBarCLI:
    """Runs codexbar subcommands and parses their JSON payloads."""

    def __init__(self, executable: str | None = None, timeout: int = 180) -> None:
        self.executable = executable or default_cli_path()
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------

    def run(self, args: list[str], timeout: int | None = None) -> CLIResult:
        cmd = [self.executable, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CLIError(
                f"codexbar CLI not found at {self.executable!r}. "
                "Install it or set CODEXBAR_CLI to its absolute path."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CLIError(f"codexbar {args[0] if args else ''} timed out") from exc
        return CLIResult(proc.returncode, proc.stdout, proc.stderr)

    def run_json(self, args: list[str], timeout: int | None = None) -> Any:
        result = self.run(args, timeout=timeout)
        text = result.stdout.strip()
        if not text:
            raise CLIError(
                f"codexbar {' '.join(args)} produced no output"
                + (f": {result.stderr.strip()}" if result.stderr.strip() else "")
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CLIError(f"codexbar {' '.join(args)} returned invalid JSON: {exc}") from exc

    # -- commands ---------------------------------------------------------

    def version(self) -> str:
        try:
            result = self.run(["--version"], timeout=20)
        except CLIError:
            return "unknown"
        return result.stdout.strip() or "unknown"

    def usage(self, provider: str | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        """Fetch usage.

        Without ``provider`` the CLI returns exactly the enabled providers, which is
        what the GUI wants to display.
        """
        args = ["usage", "--format", "json"]
        if provider:
            args += ["--provider", provider]
        payload = self.run_json(args, timeout=timeout)
        if isinstance(payload, dict):
            return [payload]
        return list(payload or [])

    def dashboard(self, timeout: int | None = None) -> dict[str, Any]:
        payload = self.run_json(["dashboard"], timeout=timeout)
        return payload if isinstance(payload, dict) else {}

    def cost(
        self,
        provider: str | None = None,
        days: int | None = None,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        args = ["cost", "--format", "json"]
        if provider:
            args += ["--provider", provider]
        if days:
            args += ["--days", str(days)]
        payload = self.run_json(args, timeout=timeout)
        if isinstance(payload, dict):
            return [payload]
        return list(payload or [])

    def config_providers(self) -> list[ProviderStatusEntry]:
        result = self.run(["config", "providers"], timeout=60)
        entries: list[ProviderStatusEntry] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            provider_id, _, rest = line.partition(":")
            provider_id = provider_id.strip()
            rest = rest.strip()
            enabled = False
            is_default = False
            name = ""
            if rest.startswith("enabled"):
                enabled = True
                is_default = "default" in rest
            elif rest.startswith("disabled"):
                enabled = False
            if "(" in rest and ")" in rest:
                name = rest[rest.rindex("(") + 1 : rest.rindex(")")].strip()
            entries.append(
                ProviderStatusEntry(
                    provider_id=provider_id,
                    enabled=enabled,
                    display_name=name,
                    is_default=is_default,
                )
            )
        return entries

    def set_api_key(self, provider: str, key: str) -> CLIResult:
        return self.run(["config", "set-api-key", "--provider", provider, "--api-key", key])

    def enable_provider(self, provider: str) -> CLIResult:
        return self.run(["config", "enable", "--provider", provider])

    def disable_provider(self, provider: str) -> CLIResult:
        return self.run(["config", "disable", "--provider", provider])

    def set_source(self, provider: str, source: str) -> CLIResult:
        return self.run(["config", "set-source", "--provider", provider, "--source", source])

    def sessions(self) -> list[dict[str, Any]]:
        try:
            payload = self.run_json(["sessions", "--json-v2"], timeout=60)
        except CLIError:
            return []
        return list(payload or [])
