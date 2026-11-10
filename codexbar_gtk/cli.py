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

from . import rust_bridge


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

    rust = rust_bridge.extension()
    if rust is not None:
        package_dir = os.path.dirname(os.path.abspath(__file__))
        for name in ("codexbar", "CodexBarCLI"):
            try:
                return str(rust.discover_cli_executable(name, None, package_dir))
            except RuntimeError:
                pass
        return "codexbar"

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

    def __init__(
        self,
        executable: str | None = None,
        timeout: int = 180,
        timezone: str | None = None,
    ) -> None:
        self.executable = executable or default_cli_path()
        self.timeout = timeout
        # ``TZ`` shifts the CLI's day buckets, matching the macOS statistics
        # time zone preference. An empty value means "use the system zone".
        self.timezone = timezone or None
        self._rust_service = None
        self._rust_config: tuple[str, str | None] | None = None

    def _rust(self):
        extension = rust_bridge.extension()
        if extension is None:
            return None
        config = (self.executable, self.timezone)
        if self._rust_service is None or config != self._rust_config:
            self._rust_service = extension.CliService(self.executable, self.timezone)
            self._rust_config = config
        return self._rust_service

    @staticmethod
    def _rust_error(error: Exception) -> CLIError:
        return CLIError(str(error))

    # -- plumbing ---------------------------------------------------------

    def run(self, args: list[str], timeout: int | None = None) -> CLIResult:
        rust = self._rust()
        if rust is not None:
            try:
                return CLIResult(*rust.run(args, timeout or self.timeout))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
        cmd = [self.executable, *args]
        env = None
        if self.timezone:
            env = os.environ.copy()
            env["TZ"] = self.timezone
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
                env=env,
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
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.run_json(args, timeout or self.timeout, "cli_command"))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
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
        rust = self._rust()
        if rust is not None:
            try:
                return rust.version(20)
            except RuntimeError:
                return "unknown"
        try:
            result = self.run(["--version"], timeout=20)
        except CLIError:
            return "unknown"
        return result.stdout.strip() or "unknown"

    def usage(
        self,
        provider: str | None = None,
        timeout: int | None = None,
        account_index: int | None = None,
        all_accounts: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch usage.

        Without ``provider`` the CLI returns exactly the enabled providers, which is
        what the GUI wants to display.
        """
        rust = self._rust()
        if rust is not None:
            try:
                index = account_index if account_index is not None and account_index >= 0 else None
                return json.loads(
                    rust.usage_json(provider, index, all_accounts, timeout or self.timeout)
                )
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
        args = ["usage", "--format", "json"]
        if provider:
            args += ["--provider", provider]
        if all_accounts:
            args += ["--all-accounts"]
        if account_index is not None and account_index >= 0:
            args += ["--account-index", str(account_index)]
        payload = self.run_json(args, timeout=timeout)
        if isinstance(payload, dict):
            return [payload]
        return list(payload or [])

    def dashboard(self, timeout: int | None = None) -> dict[str, Any]:
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.dashboard_json(timeout or self.timeout))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
        payload = self.run_json(["dashboard"], timeout=timeout)
        return payload if isinstance(payload, dict) else {}

    def cost(
        self,
        provider: str | None = None,
        days: int | None = None,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.cost_json(provider, days, timeout or self.timeout))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
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
        rust = self._rust()
        if rust is not None:
            try:
                entries = json.loads(rust.config_providers_json(60))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
            return [ProviderStatusEntry(**entry) for entry in entries]
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
        rust = self._rust()
        if rust is not None:
            try:
                return CLIResult(*rust.set_api_key(provider, key, 180))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
        return self.run(["config", "set-api-key", "--provider", provider, "--api-key", key])

    def enable_provider(self, provider: str) -> CLIResult:
        rust = self._provider_action("enable", provider)
        if rust is not None:
            return rust
        return self.run(["config", "enable", "--provider", provider])

    def disable_provider(self, provider: str) -> CLIResult:
        rust = self._provider_action("disable", provider)
        if rust is not None:
            return rust
        return self.run(["config", "disable", "--provider", provider])

    def set_source(self, provider: str, source: str) -> CLIResult:
        rust = self._provider_action("set-source", provider, source)
        if rust is not None:
            return rust
        return self.run(["config", "set-source", "--provider", provider, "--source", source])

    def _provider_action(self, action: str, provider: str, source: str | None = None) -> CLIResult | None:
        rust = self._rust()
        if rust is None:
            return None
        try:
            return CLIResult(*rust.provider_action(action, provider, source, 180))
        except RuntimeError as exc:
            raise self._rust_error(exc) from exc

    def hooks(self) -> dict[str, Any]:
        """The hook rules from the shared CodexBar config."""
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.hooks_json(30))
            except RuntimeError:
                return {"enabled": False, "events": []}
        try:
            payload = self.run_json(["hooks", "list", "--format", "json"], timeout=30)
        except CLIError:
            return {"enabled": False, "events": []}
        return payload if isinstance(payload, dict) else {"enabled": False, "events": []}

    def set_hooks_enabled(self, enabled: bool) -> CLIResult:
        rust = self._rust()
        if rust is not None:
            try:
                return CLIResult(*rust.set_hooks_enabled(enabled, 30))
            except RuntimeError as exc:
                raise self._rust_error(exc) from exc
        return self.run(["hooks", "enable" if enabled else "disable"], timeout=30)

    def plugins(self) -> list[dict[str, Any]]:
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.plugins_json(60))
            except RuntimeError:
                return []
        try:
            payload = self.run_json(["plugins", "list"], timeout=60)
        except CLIError:
            return []
        if isinstance(payload, dict):
            return [payload]
        return list(payload or [])

    def sessions(self) -> list[dict[str, Any]]:
        rust = self._rust()
        if rust is not None:
            try:
                return json.loads(rust.sessions_json(60))
            except RuntimeError:
                return []
        try:
            payload = self.run_json(["sessions", "--json-v2"], timeout=60)
        except CLIError:
            return []
        return list(payload or [])
