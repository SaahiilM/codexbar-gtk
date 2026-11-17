"""Preference store.

Mirrors the macOS app's portable preference document (see
``Sources/CodexBarCore/Config/PreferencesDocument.swift`` in the upstream repo) so
settings can be exported/imported and shared with the Swift app.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from . import rust_bridge

CONFIG_DIR = os.path.expanduser("~/.config/codexbar-gtk")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

REFRESH_INTERVALS: dict[str, int] = {
    "manual": 0,
    "1m": 60,
    "2m": 120,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "adaptive": 300,
}

DEFAULTS: dict[str, Any] = {
    # General
    "refreshFrequency": "adaptive",
    "refreshAllProvidersOnMenuOpen": True,
    "launchAtLogin": False,
    "preferredCurrencyCode": "auto",
    "costUsageBucketTimeZone": "",
    "cliPath": "",
    # Display
    "usageBarsShowUsed": True,
    "menuBarIconStyle": "meter",
    "unifiedIconSource": "highest",
    "menuBarColorPace": True,
    "switcherRowsOption": "progress",
    "workdayTickAppearance": "subtle",
    "quotaBurndownEnabled": True,
    "resetTimesOption": "countdown",
    "paceVisible": True,
    "quotaWarningMarkersVisible": True,
    "quotaWarningSessionEnabled": True,
    "quotaWarningWeeklyEnabled": True,
    "quotaWarningThresholds": [50, 20],
    "quotaWarningSessionThresholds": [50, 20],
    "quotaWarningWeeklyThresholds": [50, 20],
    "weeklyProgressWorkDays": 5,
    "showOptionalCreditsAndExtraUsage": True,
    "mergeIcons": True,
    "menuBarColorByProvider": True,
    "hidePersonalInfo": False,
    "providerOrder": [],
    "hiddenProviders": [],
    # Notifications
    "sessionQuotaNotificationsEnabled": True,
    "quotaWarningNotificationsEnabled": True,
    "limitResetNotificationsEnabled": True,
    "predictivePaceNotificationsEnabled": True,
    # Kept for portable preference round-trips; the GTK UI does not expose
    # status polling until the CLI provides a supported control for it.
    "statusChecksEnabled": True,
    # Spend
    "costUsageEnabled": True,
    "costSummaryDisplayStyle": "both",
    "costReportingPeriod": "month-to-date",
    # Preserved for compatibility with the shared preferences document.
    "costComparisonPeriodsEnabled": True,
    "spendTimeRange": "30d",
    # Advanced
    "showTray": True,
    "showPopupOnStart": False,
    "debugMenuEnabled": False,
}


class Preferences:
    """Thread-safe JSON-backed preference store."""

    def __init__(self, path: str = SETTINGS_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._values: dict[str, Any] | None = None
        core = rust_bridge.extension()
        self._rust = core.PreferencesStore(path) if core is not None else None
        if self._rust is None:
            self._values = dict(DEFAULTS)
            self.load()

    def _use_python_reference(self) -> None:
        """Keep unsupported Python-only values on the parity implementation."""
        if self._rust is not None:
            self._values = json.loads(self._rust.as_json())
            self._rust = None

    # -- persistence ------------------------------------------------------

    def load(self) -> None:
        if self._rust is not None:
            self._rust.load()
            return
        with self._lock:
            values = dict(DEFAULTS)
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict):
                    for key, value in stored.items():
                        if key in DEFAULTS:
                            values[key] = value
            except (OSError, json.JSONDecodeError):
                pass
            self._values = values

    def save(self) -> None:
        if self._rust is not None:
            self._rust.save()
            return
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)

    # -- access -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        if self._rust is not None:
            if not isinstance(key, str):
                self._use_python_reference()
            else:
                serialized = self._rust.get_json(key)
                return json.loads(serialized) if serialized is not None else DEFAULTS.get(key, default)
        with self._lock:
            return self._values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        if self._rust is not None:
            if not isinstance(key, str):
                self._use_python_reference()
            else:
                try:
                    value_json = json.dumps(value, allow_nan=False)
                except (TypeError, ValueError):
                    self._use_python_reference()
                else:
                    try:
                        self._rust.set_json(key, value_json, persist)
                    except ValueError:
                        self._use_python_reference()
                    else:
                        return
        with self._lock:
            self._values[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any]) -> None:
        if self._rust is not None:
            if not isinstance(values, dict):
                self._use_python_reference()
            else:
                try:
                    values_json = json.dumps(values, allow_nan=False)
                except (TypeError, ValueError):
                    self._use_python_reference()
                else:
                    try:
                        self._rust.update_json(values_json)
                    except ValueError:
                        self._use_python_reference()
                    else:
                        return
        with self._lock:
            self._values.update(values)
        self.save()

    def reset(self) -> None:
        if self._rust is not None:
            self._rust.reset()
            return
        with self._lock:
            self._values = dict(DEFAULTS)
        self.save()

    def as_dict(self) -> dict[str, Any]:
        if self._rust is not None:
            return json.loads(self._rust.as_json())
        with self._lock:
            return dict(self._values or {})

    # -- derived ----------------------------------------------------------

    @property
    def refresh_seconds(self) -> int:
        if self._rust is not None:
            return self._rust.refresh_seconds()
        key = str(self.get("refreshFrequency", "adaptive"))
        if key == "adaptive":
            return REFRESH_INTERVALS["adaptive"]
        return REFRESH_INTERVALS.get(key, 300)

    @property
    def refresh_is_manual(self) -> bool:
        if self._rust is not None:
            return self._rust.refresh_is_manual()
        return self.get("refreshFrequency") == "manual"

    def export_document(self) -> dict[str, Any]:
        """Export in the upstream portable preference format."""
        if self._rust is not None:
            return json.loads(self._rust.export_json())
        return {"version": 1, "preferences": self.as_dict()}

    def import_document(self, document: dict[str, Any]) -> None:
        if self._rust is not None:
            try:
                document_json = json.dumps(document, allow_nan=False)
            except (TypeError, ValueError):
                self._use_python_reference()
            else:
                try:
                    self._rust.import_json(document_json)
                except ValueError:
                    self._use_python_reference()
                else:
                    return
        prefs = document.get("preferences") if isinstance(document, dict) else None
        if isinstance(prefs, dict):
            self.update({k: v for k, v in prefs.items() if k in DEFAULTS})
