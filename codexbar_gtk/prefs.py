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
    "statusChecksEnabled": True,
    # Spend
    "costUsageEnabled": True,
    "costSummaryDisplayStyle": "both",
    "costReportingPeriod": "month-to-date",
    "costComparisonPeriodsEnabled": True,
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
        self._values: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # -- persistence ------------------------------------------------------

    def load(self) -> None:
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
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)

    # -- access -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self._values[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._values.update(values)
        self.save()

    def reset(self) -> None:
        with self._lock:
            self._values = dict(DEFAULTS)
        self.save()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    # -- derived ----------------------------------------------------------

    @property
    def refresh_seconds(self) -> int:
        key = str(self.get("refreshFrequency", "adaptive"))
        if key == "adaptive":
            return REFRESH_INTERVALS["adaptive"]
        return REFRESH_INTERVALS.get(key, 300)

    @property
    def refresh_is_manual(self) -> bool:
        return self.get("refreshFrequency") == "manual"

    def export_document(self) -> dict[str, Any]:
        """Export in the upstream portable preference format."""
        return {"version": 1, "preferences": self.as_dict()}

    def import_document(self, document: dict[str, Any]) -> None:
        prefs = document.get("preferences") if isinstance(document, dict) else None
        if isinstance(prefs, dict):
            self.update({k: v for k, v in prefs.items() if k in DEFAULTS})
