from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.providers.bcb import BCBQuote


@pytest.mark.asyncio
async def test_cdi_12m_success(client: AsyncClient, auth_headers, test_user):
    fake = AsyncMock()
    fake.get_cdi_accumulated = AsyncMock(return_value=Decimal("10.85"))
    with patch("app.api.market_indices.get_bcb_provider", return_value=fake):
        resp = await client.get("/api/market-indices/cdi-12m", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cdi_12m_pct": 10.85}


@pytest.mark.asyncio
async def test_cdi_12m_upstream_failure_502(client: AsyncClient, auth_headers, test_user):
    fake = AsyncMock()
    fake.get_cdi_accumulated = AsyncMock(return_value=None)
    with patch("app.api.market_indices.get_bcb_provider", return_value=fake):
        resp = await client.get("/api/market-indices/cdi-12m", headers=auth_headers)
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_usd_brl_success(client: AsyncClient, auth_headers, test_user):
    fake = AsyncMock()
    fake.get_usd_brl_ptax = AsyncMock(return_value=BCBQuote(value=Decimal("5.42"), date=date(2026, 8, 8)))
    with patch("app.api.market_indices.get_bcb_provider", return_value=fake):
        resp = await client.get("/api/market-indices/usd-brl", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rate": 5.42, "as_of": "2026-08-08", "source": "bcb_ptax"}


@pytest.mark.asyncio
async def test_market_indices_require_auth(client: AsyncClient):
    resp = await client.get("/api/market-indices/cdi-12m")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cdi_12m_disabled_returns_404(client: AsyncClient, auth_headers, test_user):
    with patch("app.api.market_indices.get_settings") as mock_settings:
        mock_settings.return_value.bcb_enabled = False
        resp = await client.get("/api/market-indices/cdi-12m", headers=auth_headers)
    assert resp.status_code == 404
