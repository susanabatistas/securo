"""Banco Central do Brasil (BCB) SGS provider — CDI and USD/BRL PTAX.

Public, no-key API: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados
Series used:
  * 4390 — "Taxa de juros - CDI acumulada no mês" (monthly accumulated CDI, %).
    Trailing-N-months accumulated CDI is the compounded product of the last N
    monthly readings, not their sum.
  * 1 — "Taxa de câmbio - Livre - Dólar americano (venda) - PTAX" (daily, BRL).

Same shape as `app/providers/tesouro_direto.py`: a frozen dataclass for the
quote, a module-level in-process TTL cache, plain `requests.get()` (no SDK,
no key), and a factory function. No IA/LLM involved — this is a public,
deterministic data feed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests

BCB_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/{n}?formato=json"
# `ultimos/{n}` (above) rejects n > 20 ("A quantidade máxima de valores deve
# ser 20") — fine for get_cdi_accumulated (n=12) but useless for a multi-year
# comparison series, so that case uses this date-range variant instead, which
# has no such cap.
BCB_SGS_RANGE_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
    "?dataInicial={start}&dataFinal={end}&formato=json"
)

CDI_SERIES = 4390  # monthly accumulated CDI, %
USD_BRL_PTAX_SERIES = 1  # daily sell PTAX, BRL

# Both series (CDI accumulated, USD/BRL PTAX) are official BCB rates
# published once per business day — a 24h cache never serves a stale
# reading within the same day, and avoids re-hitting the SGS API on every
# request for a number that hasn't changed.
_CACHE_TTL_SECONDS = 24 * 60 * 60
_cache: dict[str, dict] = {}


@dataclass(frozen=True)
class BCBQuote:
    value: Decimal
    date: date


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


def _months_before(d: date, months: int) -> date:
    """`d` shifted back `months` calendar months, clamped to the last valid
    day of the resulting month (e.g. Mar 31 - 1 month -> Feb 28/29, not an
    invalid Feb 31)."""
    total = d.month - 1 - months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value}") from exc


def _parse_series(raw: list[dict]) -> list[BCBQuote]:
    quotes: list[BCBQuote] = []
    for row in raw:
        try:
            quotes.append(BCBQuote(value=_parse_decimal(row["valor"]), date=_parse_date(row["data"])))
        except (KeyError, ValueError):
            continue
    return quotes


def compound_cdi(monthly_quotes: list[BCBQuote]) -> Optional[Decimal]:
    """Compound a list of monthly accumulated-CDI readings (%) into a single
    trailing accumulated rate (%). Pure function — no I/O — so it's testable
    without hitting the network."""
    if not monthly_quotes:
        return None
    factor = Decimal("1")
    for q in monthly_quotes:
        factor *= Decimal("1") + q.value / Decimal("100")
    return (factor - Decimal("1")) * Decimal("100")


class BCBProvider:
    def __init__(self, *, base_url: str = BCB_SGS_URL) -> None:
        self.base_url = base_url

    async def get_cdi_accumulated(self, months: int = 12) -> Optional[Decimal]:
        """Compounded CDI over the trailing `months` monthly readings, as a
        percentage (e.g. Decimal("10.85") for 10.85%)."""
        import asyncio

        quotes = await asyncio.to_thread(self._fetch_series, CDI_SERIES, months)
        return compound_cdi(quotes)

    async def get_cdi_monthly_series(self, months: int = 120) -> list[BCBQuote]:
        """Raw monthly accumulated-CDI readings (%), oldest first, for the
        trailing `months` months — unlike `get_cdi_accumulated` this returns
        each month's own reading uncompounded, for building a rebased
        comparison line against another series (e.g. portfolio return).
        Uses the date-range endpoint (`ultimos/{n}` caps out at n=20)."""
        import asyncio

        end = date.today()
        start = _months_before(end, months).replace(day=1)
        return await asyncio.to_thread(self._fetch_series_range, CDI_SERIES, start, end)

    async def get_usd_brl_ptax(self) -> Optional[BCBQuote]:
        import asyncio

        quotes = await asyncio.to_thread(self._fetch_series, USD_BRL_PTAX_SERIES, 1)
        return quotes[-1] if quotes else None

    def _fetch_series(self, serie: int, n: int) -> list[BCBQuote]:
        cache_key = f"{serie}:{n}"
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < _CACHE_TTL_SECONDS:
            return cached["quotes"]

        response = requests.get(
            self.base_url.format(serie=serie, n=n),
            headers={"User-Agent": "Securo BCBProvider"},
            timeout=30,
        )
        response.raise_for_status()
        quotes = _parse_series(response.json())
        _cache[cache_key] = {"ts": now, "quotes": quotes}
        return quotes

    def _fetch_series_range(self, serie: int, start: date, end: date) -> list[BCBQuote]:
        # Keyed by year-month, not the exact `end` date — `end` is always
        # "today" for the caller, which would otherwise change the cache key
        # (and force a re-fetch of months of already-published, unchanging
        # history) every single day. Same 24h TTL as `_fetch_series`: at most
        # one re-fetch per day, which is all a same-month cache hit needs to
        # pick up a same-day-published reading.
        cache_key = f"{serie}:{start.strftime('%Y-%m')}:{end.strftime('%Y-%m')}"
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < _CACHE_TTL_SECONDS:
            return cached["quotes"]

        response = requests.get(
            BCB_SGS_RANGE_URL.format(
                serie=serie, start=start.strftime("%d/%m/%Y"), end=end.strftime("%d/%m/%Y")
            ),
            headers={"User-Agent": "Securo BCBProvider"},
            timeout=30,
        )
        response.raise_for_status()
        quotes = _parse_series(response.json())
        _cache[cache_key] = {"ts": now, "quotes": quotes}
        return quotes


def get_bcb_provider() -> BCBProvider:
    return BCBProvider()
