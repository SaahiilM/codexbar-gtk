"""Currency conversion for spend figures.

The CLI reports costs in the currency recorded by the provider (usually USD).
The macOS app converts those estimates into a preferred currency using daily
exchange rates with an offline fallback. This module mirrors that behaviour:
rates come from ``open.er-api.com`` (cached for 24 hours) and fall back to the
bundled approximations whenever the network is unavailable.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from . import rust_bridge

CACHE_PATH = os.path.expanduser("~/.cache/codexbar-gtk/currency-rates.json")
CACHE_TTL_SECONDS = 24 * 60 * 60
RATES_URL = "https://open.er-api.com/v6/latest/USD"

# Keep this catalog in sync with CodexBarCore/CurrencyExchange.swift.
CURRENCIES: list[tuple[str, str, float]] = [
    ("USD", "$", 1.0),
    ("GBP", "£", 0.79),
    ("EUR", "€", 0.92),
    ("CZK", "Kč", 21.0),
    ("CNY", "¥", 7.27),
    ("JPY", "¥", 154.0),
    ("KRW", "₩", 1428.90),
    ("CAD", "$", 1.38),
    ("AUD", "$", 1.55),
    ("HKD", "$", 7.80),
    ("TWD", "NT$", 32.30),
    ("SGD", "$", 1.34),
    ("INR", "₹", 84.50),
    ("CHF", "Fr.", 0.80),
    ("AED", "د.إ", 3.6725),
    ("TRY", "₺", 48.5),
    ("NZD", "$", 1.761),
    ("SEK", "kr", 9.908),
    ("NOK", "kr", 9.480),
    ("DKK", "kr", 6.554),
    ("PLN", "zł", 3.838),
    ("BRL", "R$", 5.117),
    ("MXN", "$", 17.47),
    ("ZAR", "R", 16.36),
    ("THB", "฿", 33.37),
    ("IDR", "Rp", 17836.0),
    ("VND", "₫", 25962.0),
    ("UAH", "₴", 44.86),
    ("ILS", "₪", 3.109),
]

_RUST = rust_bridge.extension()

SUPPORTED = tuple(code for code, _symbol, _rate in CURRENCIES)
_SYMBOLS = {code: symbol for code, symbol, _rate in CURRENCIES}
_OFFLINE = {code: rate for code, _symbol, rate in CURRENCIES}


def picker_label(code: str) -> str:
    """``"EUR (€)"``-style label used in the preferences picker."""
    normalized = code.upper()
    symbols = (
        {entry_code: symbol for entry_code, symbol, _rate in shared().entries()}
        if _RUST is not None
        else _SYMBOLS
    )
    symbol = symbols.get(normalized)
    return f"{normalized} ({symbol})" if symbol else normalized


def supported_codes() -> tuple[str, ...]:
    """Return codes from the selected backend's active currency catalog."""
    if _RUST is not None:
        return tuple(code for code, _symbol, _rate in shared().entries())
    return SUPPORTED


def requires_live_rates(preferred: str) -> bool:
    return shared().requires_live_rates(preferred)


class CurrencyConverter:
    """Thread-safe USD-pivoted converter with a daily rate cache."""

    def __init__(self, cache_path: str = CACHE_PATH) -> None:
        self._rust = _RUST.CurrencyConverter(cache_path) if _RUST is not None else None
        self._facade = None
        self._lock = threading.Lock()
        self._cache_path = cache_path
        self._rates = dict(_OFFLINE)
        self._fetched_at = 0.0
        self._loading = False
        if self._rust is None:
            self._load_cache()

    # -- rates ------------------------------------------------------------

    def entries(self) -> list[tuple[str, str, float]]:
        """Return the current catalog through the bound facade when present."""
        facade = self._facade
        if facade is not None:
            return facade.catalog_async()
        if self._rust is not None:
            return self._rust.entries()
        return list(CURRENCIES)

    def requires_live_rates(self, preferred: str) -> bool:
        code = (preferred or "").strip().upper()
        if code in ("", "AUTO", "USD"):
            return False
        return self.rate(code) is not None

    def _load_cache(self) -> None:
        if self._rust is not None:
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            rates = payload.get("rates") or {}
            fetched = float(payload.get("fetchedAt") or 0)
            cleaned = {
                str(code).upper(): float(rate)
                for code, rate in rates.items()
                if str(code).upper() in _OFFLINE and float(rate) > 0
            }
            if cleaned:
                with self._lock:
                    self._rates.update(cleaned)
                    self._fetched_at = fetched
        except (OSError, ValueError, TypeError):
            pass

    def _write_cache(self) -> None:
        if self._rust is not None:
            return
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            with self._lock:
                payload = {"fetchedAt": self._fetched_at, "rates": dict(self._rates)}
            with open(self._cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except OSError:
            pass

    def ensure_rates(self, preferred: str):
        """Fetch fresh rates in the background when the preferred code needs them."""
        facade = self._facade
        if facade is not None:
            return facade.ensure_rates(preferred)
        if self._rust is not None:
            self._rust.ensure_rates(preferred)
            return
        if not requires_live_rates(preferred):
            return
        with self._lock:
            fresh = (time.time() - self._fetched_at) < CACHE_TTL_SECONDS
            if fresh or self._loading:
                return
            self._loading = True

        def worker() -> None:
            rates: dict[str, float] = {}
            try:
                with urllib.request.urlopen(RATES_URL, timeout=15) as response:
                    payload = json.load(response)
                raw = payload.get("rates") or {}
                rates = {
                    str(code).upper(): float(rate)
                    for code, rate in raw.items()
                    if str(code).upper() in _OFFLINE and float(rate) > 0
                }
            except Exception:
                rates = {}
            with self._lock:
                self._loading = False
                if rates:
                    self._rates.update(rates)
                    # USD is the pivot, so its rate is always exactly 1.
                    self._rates["USD"] = 1.0
                    self._fetched_at = time.time()
            if rates:
                self._write_cache()

        threading.Thread(target=worker, name="codexbar-rates", daemon=True).start()

    def rate(self, code: str) -> float | None:
        facade = self._facade
        if facade is not None:
            return facade.rate_async(code)
        if self._rust is not None:
            return self._rust.rate(code)
        code = (code or "").strip().upper()
        if not code:
            return 1.0
        with self._lock:
            return self._rates.get(code)

    # -- conversion -------------------------------------------------------

    def convert(self, amount: float, source: str, target: str) -> float | None:
        """Convert ``amount`` between supported codes, pivoting through USD."""
        facade = self._facade
        if facade is not None:
            return facade.convert_async(amount, source, target)
        if self._rust is not None:
            return self._rust.convert(amount, source, target)
        src = (source or "").strip().upper()
        dst = (target or "").strip().upper()
        if not src or not dst or src == dst:
            return amount
        src_rate = 1.0 if src == "USD" else self.rate(src)
        dst_rate = 1.0 if dst == "USD" else self.rate(dst)
        if not src_rate or not dst_rate or src_rate <= 0:
            return None
        return amount / src_rate * dst_rate

    def status_async(self) -> dict | None:
        """Return current fetched time/source/failure through the facade."""
        facade = self._facade
        if facade is not None:
            return facade.status_async()
        if self._rust is None:
            return None
        fetched_at, source, failed = self._rust.status()
        return {
            "fetched_at": fetched_at,
            "source": source,
            "last_refresh_failed": failed,
        }

    def status(self):
        """Preserve the legacy Python tuple shape for parity callers."""
        status = self.status_async()
        if status is None:
            return None
        return (
            status["fetched_at"],
            status["source"],
            status["last_refresh_failed"],
        )


_SHARED: CurrencyConverter | None = None


def shared() -> CurrencyConverter:
    global _SHARED
    if _SHARED is None:
        _SHARED = CurrencyConverter()
    return _SHARED


def bind_facade(facade) -> None:
    """Route the shared adapter through the active central controller facade."""
    shared()._facade = facade


def unbind_facade(facade) -> None:
    """Clear only the facade instance that was previously bound."""
    converter = shared()
    if converter._facade is facade:
        converter._facade = None


def convert(amount: float, source: str, target: str) -> float | None:
    return shared().convert(amount, source, target)
