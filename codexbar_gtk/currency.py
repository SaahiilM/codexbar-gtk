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
_RUST_CATALOG = _RUST.CurrencyConverter(CACHE_PATH) if _RUST is not None else None
if _RUST_CATALOG is not None:
    CURRENCIES = _RUST_CATALOG.entries()

SUPPORTED = tuple(code for code, _symbol, _rate in CURRENCIES)
_SYMBOLS = {code: symbol for code, symbol, _rate in CURRENCIES}
_OFFLINE = {code: rate for code, _symbol, rate in CURRENCIES}


def picker_label(code: str) -> str:
    """``"EUR (€)"``-style label used in the preferences picker."""
    symbol = _SYMBOLS.get(code.upper())
    return f"{code.upper()} ({symbol})" if symbol else code.upper()


def requires_live_rates(preferred: str) -> bool:
    if _RUST_CATALOG is not None:
        return _RUST_CATALOG.requires_live_rates(preferred)
    code = (preferred or "").strip().upper()
    return code not in ("", "AUTO", "USD") and code in _OFFLINE


class CurrencyConverter:
    """Thread-safe USD-pivoted converter with a daily rate cache."""

    def __init__(self, cache_path: str = CACHE_PATH) -> None:
        self._rust = _RUST.CurrencyConverter(cache_path) if _RUST is not None else None
        self._lock = threading.Lock()
        self._cache_path = cache_path
        self._rates = dict(_OFFLINE)
        self._fetched_at = 0.0
        self._loading = False
        if self._rust is None:
            self._load_cache()

    # -- rates ------------------------------------------------------------

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

    def ensure_rates(self, preferred: str) -> None:
        """Fetch fresh rates in the background when the preferred code needs them."""
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

    def status(self):
        """Return Rust cache source metadata when opt-in mode is active."""
        return self._rust.status() if self._rust is not None else None


_SHARED: CurrencyConverter | None = None


def shared() -> CurrencyConverter:
    global _SHARED
    if _SHARED is None:
        if _RUST_CATALOG is None:
            _SHARED = CurrencyConverter()
        else:
            _SHARED = object.__new__(CurrencyConverter)
            _SHARED._rust = _RUST_CATALOG
            _SHARED._lock = threading.Lock()
            _SHARED._cache_path = CACHE_PATH
            _SHARED._rates = dict(_OFFLINE)
            _SHARED._fetched_at = 0.0
            _SHARED._loading = False
    return _SHARED


def convert(amount: float, source: str, target: str) -> float | None:
    return shared().convert(amount, source, target)
