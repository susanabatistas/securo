import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.asset import Asset

B3_CSV = """Movimentação;Data;Produto;Quantidade;Preço unitário;Valor da Operação
Compra;01/03/2026;PETR4 - PETROBRAS PN N2;100;28,50;2850,00
Compra;15/03/2026;PETR4 - PETROBRAS PN N2;50;30,00;1500,00
Dividendo;10/03/2026;PETR4 - PETROBRAS PN N2;100;;45,00
"""


@pytest.mark.asyncio
async def test_b3_preview_returns_rows_and_ticker_summary(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/assets/import/b3-preview",
        headers=auth_headers,
        files={"file": ("movimentacao.csv", B3_CSV.encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["rows"]) == 2
    # Dividendo is now an income row, not skipped.
    assert data["skipped_count"] == 0
    assert len(data["income_rows"]) == 1
    assert data["income_rows"][0]["kind"] == "dividendo"
    assert data["income_rows"][0]["amount"] == 45.0
    assert len(data["tickers"]) == 1
    assert data["tickers"][0]["ticker"] == "PETR4.SA"
    assert data["tickers"][0]["buy_quantity"] == 150


@pytest.mark.asyncio
async def test_b3_preview_rejects_unrecognized_format(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/assets/import/b3-preview",
        headers=auth_headers,
        files={"file": ("garbage.csv", b"col_a,col_b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_b3_apply_creates_holding_from_previewed_rows(
    client: AsyncClient, auth_headers, monkeypatch, session
):
    from app.providers.market_price import MarketSymbolQuote
    from unittest.mock import AsyncMock, patch

    preview_resp = await client.post(
        "/api/assets/import/b3-preview",
        headers=auth_headers,
        files={"file": ("movimentacao.csv", B3_CSV.encode("utf-8"), "text/csv")},
    )
    preview = preview_resp.json()
    rows = preview["rows"]
    income_rows = preview["income_rows"]
    assert len(income_rows) == 1

    fake = AsyncMock()
    fake.get_quote = AsyncMock(
        return_value=MarketSymbolQuote(symbol="PETR4.SA", currency="BRL", price=29.0, quote_type="EQUITY")
    )
    with patch("app.services.asset_transaction_service.get_market_price_provider", return_value=fake):
        apply_resp = await client.post(
            "/api/assets/import/b3-apply",
            headers=auth_headers,
            json={"rows": rows, "income_rows": income_rows},
        )
    assert apply_resp.status_code == 201, apply_resp.text
    data = apply_resp.json()
    assert data["applied_count"] == 2
    assert data["income_applied_count"] == 1
    assert data["errors"] == []

    asset = (await session.execute(select(Asset).where(Asset.ticker == "PETR4.SA"))).scalar_one()
    assert asset.units == 150

    income_resp = await client.get(f"/api/assets/{asset.id}/income", headers=auth_headers)
    assert len(income_resp.json()) == 1
    assert income_resp.json()[0]["amount"] == 45.0
    assert income_resp.json()[0]["source"] == "import"


@pytest.mark.asyncio
async def test_b3_apply_reports_unresolved_sell(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/assets/import/b3-apply",
        headers=auth_headers,
        json={"rows": [{"ticker": "NOPOS4", "kind": "sell", "quantity": 10, "price": 20, "date": "2026-03-01"}]},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["applied_count"] == 0
    assert len(data["errors"]) == 1
    assert data["errors"][0]["reason"] == "venda sem posição encontrada"


@pytest.mark.asyncio
async def test_b3_apply_reports_unresolved_income(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/assets/import/b3-apply",
        headers=auth_headers,
        json={"rows": [], "income_rows": [{"ticker": "NOPOS4", "kind": "dividendo", "amount": 10, "date": "2026-03-01"}]},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["income_applied_count"] == 0
    assert len(data["errors"]) == 1
    assert data["errors"][0]["reason"] == "provento sem posição encontrada"
