import json
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_active_user
from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.models.user import User
from app.providers.market_price import (
    MarketPriceRateLimitedError,
    get_market_price_provider,
)
from app.schemas.asset_import import (
    AssetImportPreview,
    AssetImportRequest,
    AssetImportResult,
)
from app.schemas.asset import (
    AssetBuyCreate,
    AssetCreate,
    AssetRead,
    AssetTransactionCreate,
    AssetTransactionRead,
    AssetTransactionUpdate,
    AssetUpdate,
    AssetValueCreate,
    AssetValueRead,
    MarketSymbolMatch,
    MarketSymbolQuote,
)
from app.schemas.asset_income import (
    AssetIncomeCreate,
    AssetIncomeMonthlySummary,
    AssetIncomeRead,
    AssetIncomeUpdate,
    DividendHistoryApplyRequest,
    DividendHistoryPreviewResponse,
)
from app.schemas.b3_import import (
    B3ImportApplyRequest,
    B3ImportApplyResponse,
    B3ImportPreviewResponse,
    B3IncomeRowSchema,
    B3RowSchema,
    B3TickerPreview,
)
from app.schemas.ir_estimate import IREstimateResponse
from app.schemas.stock_checklist import StockChecklistResult
from app.services import (
    asset_import_service,
    asset_income_service,
    asset_service,
    asset_transaction_service,
    b3_import_service,
    ir_estimator_service,
    stock_checklist_service,
)
from app.services.fx_rate_service import convert, get_rate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])


# ----------------------------------------------------------------------------
# Market price lookup (Yahoo Finance via yfinance)
# ----------------------------------------------------------------------------
#
# Lives under /api/assets/market/... rather than a top-level /market so the
# RBAC and auth middleware inherited by this router applies automatically —
# ticker lookups are gated behind an authenticated session just like other
# asset endpoints.


@router.get("/market/search", response_model=list[MarketSymbolMatch])
async def market_search(
    q: str = Query(..., min_length=1, max_length=64, description="Ticker or company name"),
    # Upper bound is generous so the Tesouro Direto dropdown can list every
    # open bond (~60 and growing); ticker autocomplete still requests ~15.
    limit: int = Query(15, ge=1, le=300),
    _: User = Depends(current_active_user),
) -> list[MarketSymbolMatch]:
    """Autocomplete ticker symbols for the Add-Asset form.

    Intentionally thin — just proxies to the configured market-price
    provider. Upstream errors turn into an empty list so the UI degrades
    gracefully (a user typing a query shouldn't ever see a 500).
    """
    provider = get_market_price_provider()
    try:
        return await provider.search(q, limit=limit)
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )
    except Exception:
        logger.exception("Market search failed for %r", q)
        return []


@router.get("/market/quote", response_model=MarketSymbolQuote)
async def market_quote(
    symbol: str = Query(..., min_length=1, max_length=32),
    _: User = Depends(current_active_user),
) -> MarketSymbolQuote:
    """Fetch a single live quote — used to preview value before saving an asset."""
    provider = get_market_price_provider()
    try:
        quote = await provider.get_quote(symbol)
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )
    if quote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quote found for {symbol}",
        )
    return quote




@router.post("/{asset_id}/refresh-price", response_model=AssetRead)
async def refresh_asset_price(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
) -> AssetRead:
    """Trigger an immediate price refresh for a single market-priced asset.

    Mirrors what the scheduled daily task does for one asset — re-quotes
    the ticker, updates ``last_price`` + ``last_price_at``, and upserts
    today's ``AssetValue``. Returns the refreshed asset with the same
    shape as the list endpoint (including ``current_value_primary``).
    """
    from app.models.asset import Asset as AssetModel
    from sqlalchemy import select as sa_select

    result = await session.execute(
        sa_select(AssetModel).where(
            AssetModel.id == asset_id, AssetModel.workspace_id == ctx.workspace.id
        )
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.valuation_method != "market_price":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only externally priced assets can be refreshed via this endpoint",
        )

    try:
        ok = await asset_service.refresh_market_price_asset(session, asset)
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not refresh price for this asset",
        )
    await session.commit()

    refreshed = await asset_service.get_asset(session, asset_id, ctx.workspace.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    # Stamp the primary-currency fields so the refresh response has the same
    # shape as the list endpoint — the React Query cache update needs them
    # to keep the row rendering consistent (BRL rollup, gain/loss).
    primary_currency = ctx.user.primary_currency
    if refreshed.currency != primary_currency and refreshed.current_value is not None:
        converted, _ = await convert(
            session, Decimal(str(refreshed.current_value)), refreshed.currency, primary_currency,
        )
        refreshed.current_value_primary = float(converted)
        if refreshed.gain_loss is not None:
            gl_converted, _ = await convert(
                session, Decimal(str(refreshed.gain_loss)), refreshed.currency, primary_currency,
            )
            refreshed.gain_loss_primary = float(gl_converted)
    return refreshed


@router.get("/{asset_id}/stock-checklist", response_model=StockChecklistResult)
async def get_stock_checklist(
    asset_id: uuid.UUID,
    roe_min: float = Query(stock_checklist_service.DEFAULT_ROE_MIN_PCT),
    revenue_cagr_min: float = Query(stock_checklist_service.DEFAULT_REVENUE_CAGR_MIN_PCT),
    profit_cagr_min: float = Query(stock_checklist_service.DEFAULT_PROFIT_CAGR_MIN_PCT),
    net_debt_ebitda_max: float = Query(stock_checklist_service.DEFAULT_NET_DEBT_EBITDA_MAX),
    years: int = Query(stock_checklist_service.DEFAULT_YEARS, ge=2, le=10),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Deterministic checklist (ROE, CAGR de receita/lucro, dívida líquida/
    EBITDA) for an individual stock. Sector/industry are informational only,
    never a pass/fail criterion. No AI — just thresholds over fundamentals
    already fetched from the ticker provider."""
    from app.models.asset import Asset as AssetModel
    from sqlalchemy import select as sa_select

    result = await session.execute(
        sa_select(AssetModel).where(
            AssetModel.id == asset_id, AssetModel.workspace_id == ctx.workspace.id
        )
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.type != "stock" or not asset.ticker:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stock checklist only applies to individual stocks with a ticker",
        )

    try:
        return await stock_checklist_service.evaluate(
            get_market_price_provider(),
            asset.ticker,
            manual_override=asset.stock_checklist_status,
            roe_min=roe_min,
            revenue_cagr_min=revenue_cagr_min,
            profit_cagr_min=profit_cagr_min,
            net_debt_ebitda_max=net_debt_ebitda_max,
            years=years,
        )
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )


async def _stamp_fx_rate_used(session: AsyncSession, asset: AssetRead, primary_currency: str) -> None:
    """Historical FX rate for `purchase_price_primary` (item 4, Seção 2).

    Computed on read, not stored — `asset.purchase_date` already anchors
    `purchase_price_primary` (see asset_service/asset_transaction_service),
    so this just surfaces the rate that produced it. `allow_fetch=False`
    because a list/detail read shouldn't trigger an on-demand provider call
    per asset; a missing historical rate just means this stays None.
    """
    if asset.currency == primary_currency or asset.purchase_price_primary is None:
        return
    rate = await get_rate(
        session, asset.currency, primary_currency, asset.purchase_date, allow_fetch=False,
    )
    asset.fx_rate_used = float(rate)


async def _populate_primary_amounts(
    session: AsyncSession, assets: list[AssetRead], primary_currency: str
) -> None:
    """Fill current_value_primary/gain_loss_primary/fx_rate_used in place.

    Extracted from list_assets so the IR estimator (which needs the same
    primary-currency gain figures to compute tax) doesn't duplicate this
    conversion loop.
    """
    for asset in assets:
        if asset.currency != primary_currency and asset.current_value is not None:
            converted, _ = await convert(
                session, Decimal(str(asset.current_value)), asset.currency, primary_currency,
            )
            asset.current_value_primary = float(converted)
            if asset.gain_loss is not None:
                gl_converted, _ = await convert(
                    session, Decimal(str(asset.gain_loss)), asset.currency, primary_currency,
                )
                asset.gain_loss_primary = float(gl_converted)
        await _stamp_fx_rate_used(session, asset, primary_currency)


@router.get("", response_model=list[AssetRead])
async def list_assets(
    include_archived: bool = False,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    assets = await asset_service.get_assets(session, ctx.workspace.id, include_archived=include_archived)
    await _populate_primary_amounts(session, assets, ctx.user.primary_currency)
    return assets


@router.get("/ir-estimate", response_model=IREstimateResponse)
async def get_ir_estimate(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Estimated IR (income tax) if every current holding with a gain were
    sold today. Deterministic — no AI — see IREstimateResponse.disclaimer.

    Brazilian tax rules only make sense applied to a BRL gain, so this is a
    no-op (applicable=False, nothing computed) when the user's primary
    currency isn't BRL — computing against gain_loss_primary in another
    currency would silently apply BR tax rates to the wrong numbers."""
    if ctx.user.primary_currency != "BRL":
        return IREstimateResponse(assets=[], total_estimated_tax=0, applicable=False)
    assets = await asset_service.get_assets(session, ctx.workspace.id)
    active = [a for a in assets if a.sell_date is None]
    await _populate_primary_amounts(session, active, ctx.user.primary_currency)
    return ir_estimator_service.estimate_portfolio(active)


@router.post("/import/b3-preview", response_model=B3ImportPreviewResponse)
async def preview_b3_import(
    file: UploadFile = File(...),
    _: User = Depends(current_active_user),
):
    """Parse a B3 "Movimentação" export in CSV format (Compra/Venda only) and return a
    preview — individual rows (sent back to /import/b3-apply verbatim) plus
    an aggregated-by-ticker summary for display. Raises 422 with a clear message when the 
    file isn't recognized as this format."""
    content = await file.read()
    try:
        result = b3_import_service.parse_b3_csv(content)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return B3ImportPreviewResponse(
        rows=[
            B3RowSchema(ticker=r.ticker, kind=r.kind, quantity=float(r.quantity), price=float(r.price), date=r.date)
            for r in result.rows
        ],
        income_rows=[
            B3IncomeRowSchema(ticker=r.ticker, kind=r.kind, amount=float(r.amount), date=r.date)
            for r in result.income_rows
        ],
        tickers=[
            B3TickerPreview(
                ticker=p.ticker,
                buy_quantity=float(p.buy_quantity),
                buy_average_price=float(p.buy_average_price),
                sell_quantity=float(p.sell_quantity),
                sell_average_price=float(p.sell_average_price),
                first_date=p.first_date,
                last_date=p.last_date,
                row_count=p.row_count,
            )
            for p in b3_import_service.aggregate_for_preview(result.rows)
        ],
        skipped_count=result.skipped_count,
        skipped_kinds=result.skipped_kinds,
    )


@router.post("/import/b3-apply", response_model=B3ImportApplyResponse, status_code=status.HTTP_201_CREATED)
async def apply_b3_import(
    data: B3ImportApplyRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    rows = [
        b3_import_service.B3Row(
            ticker=r.ticker, product=r.ticker, kind=r.kind,
            quantity=Decimal(str(r.quantity)), price=Decimal(str(r.price)), date=r.date,
        )
        for r in data.rows
    ]
    income_rows = [
        b3_import_service.B3IncomeRow(
            ticker=r.ticker, product=r.ticker, kind=r.kind,
            amount=Decimal(str(r.amount)), date=r.date,
        )
        for r in data.income_rows
    ]
    result = await b3_import_service.apply_b3_rows(
        session, ctx.workspace.id, ctx.user_id, rows,
        income_rows=income_rows, group_id=data.group_id,
    )
    return B3ImportApplyResponse(
        applied_count=result.applied_count,
        income_applied_count=result.income_applied_count,
        errors=[
            {"ticker": e.ticker, "kind": e.kind, "date": e.date, "reason": e.reason} for e in result.errors
        ],
    )


@router.get("/portfolio-trend")
async def portfolio_trend(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await asset_service.get_portfolio_trend(session, ctx.workspace.id, ctx.user_id)


# ----------------------------------------------------------------------------
# Transaction ledger (issue #235)
# ----------------------------------------------------------------------------
#
# These specific routes are declared before the `/{asset_id}` catch-all so a
# path like `/transactions` is never swallowed by the UUID param.


@router.get("/transactions", response_model=list[AssetTransactionRead])
async def list_workspace_transactions(
    ticker: str | None = Query(None, max_length=32),
    kind: str | None = Query(None, pattern="^(buy|sell)$"),
    limit: int = Query(500, ge=1, le=2000),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """All buy/sell transactions in the workspace — powers the Transactions tab."""
    return await asset_transaction_service.list_workspace_transactions(
        session, ctx.workspace.id, ticker=ticker, kind=kind, limit=limit
    )


@router.get("/import/template")
async def asset_import_template(
    ctx: WorkspaceContext = Depends(current_workspace),
):
    """A starter CSV, so the first upload is a fill-in rather than a guess."""
    return Response(
        content=asset_import_service.csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="securo-asset-orders.csv"'},
    )


@router.post("/import/preview", response_model=AssetImportPreview)
async def preview_asset_import(
    file: UploadFile = File(...),
    column_mapping: str | None = Form(None),
    date_format: str | None = Form(None),
    group_id: uuid.UUID | None = Form(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Read the file and say what importing it would do. Writes nothing.

    Read-gated on purpose, like the transaction preview: a viewer may look at
    a file without being able to commit it.
    """
    content = await file.read()
    mapping = None
    if column_mapping:
        try:
            mapping = json.loads(column_mapping)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="column_mapping must be valid JSON")

    try:
        orders, errors, columns = asset_import_service.parse_orders_csv(
            content, column_mapping=mapping, date_format=date_format
        )
    except ValueError as exc:
        # Soft failure: hand back the headers so the UI can offer the mapping
        # dropdowns instead of a dead end.
        return AssetImportPreview(
            orders=[],
            errors=[],
            csv_columns=asset_import_service.detect_columns(content),
            parse_error=str(exc),
        )

    try:
        summary = await asset_import_service.import_orders(
            session, ctx.workspace.id, ctx.user_id, orders, group_id=group_id, dry_run=True
        )
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )

    # The dry run rejects rows the parser could not know about — an unknown
    # ticker, a sell with nothing to sell. Drop those from the list too, so the
    # table, the count and the button all describe the same import.
    rejected = {e.row for e in summary["errors"]}
    return AssetImportPreview(
        orders=[o for o in orders if o.row not in rejected],
        errors=errors + summary["errors"],
        warnings=summary["warnings"],
        csv_columns=columns,
        holdings_created=summary["holdings_created"],
        holdings_matched=summary["holdings_matched"],
        skipped=summary["skipped"],
    )


@router.post("/import", response_model=AssetImportResult)
async def import_asset_orders(
    data: AssetImportRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Apply the previewed orders to the workspace's holdings."""
    try:
        summary = await asset_import_service.import_orders(
            session, ctx.workspace.id, ctx.user_id, data.orders, group_id=data.group_id
        )
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )
    return AssetImportResult(**summary)


@router.post("/buy", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def buy_into_holding(
    data: AssetBuyCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Record a buy, consolidating onto the existing ticker holding (in the
    chosen wallet) or creating a new market-priced one."""
    try:
        return await asset_transaction_service.buy_into_holding(
            session, ctx.workspace.id, ctx.user_id, data
        )
    except MarketPriceRateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Market data provider is currently rate-limiting. Try again in a minute.",
        )


@router.get("/{asset_id}/transactions", response_model=list[AssetTransactionRead])
async def list_asset_transactions(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    txs = await asset_transaction_service.list_asset_transactions(
        session, asset_id, ctx.workspace.id
    )
    if txs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return txs


@router.post(
    "/{asset_id}/transactions", response_model=AssetRead, status_code=status.HTTP_201_CREATED
)
async def add_asset_transaction(
    asset_id: uuid.UUID,
    data: AssetTransactionCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    asset = await asset_transaction_service.add_transaction(
        session, asset_id, ctx.workspace.id, data
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.patch("/transactions/{tx_id}", response_model=AssetRead)
async def update_asset_transaction(
    tx_id: uuid.UUID,
    data: AssetTransactionUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    asset = await asset_transaction_service.update_transaction(
        session, tx_id, ctx.workspace.id, data
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return asset


@router.delete("/transactions/{tx_id}", response_model=AssetRead)
async def delete_asset_transaction(
    tx_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    asset = await asset_transaction_service.delete_transaction(
        session, tx_id, ctx.workspace.id
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return asset


# ----------------------------------------------------------------------------
# Proventos (dividend/JCP/rendimento receipts) — deliberately separate from
# the buy/sell ledger above (see app/models/asset_income.py). Declared before
# the `/{asset_id}` catch-all for the same reason as the ledger routes.
# ----------------------------------------------------------------------------


async def _populate_income_primary_amounts(
    session: AsyncSession, rows: list[AssetIncomeRead], primary_currency: str
) -> None:
    """Fill amount_primary in place, at the historical rate on each row's
    own date — never today's, and never assumes same-currency. Aggregating
    `amount` directly across rows in different currencies previously showed
    a USD dividend as if it were that many BRL (confirmed by a real user's
    portfolio mixing BR and international holdings)."""
    for row in rows:
        if row.currency is None or row.currency == primary_currency:
            row.amount_primary = row.amount
            continue
        converted, _ = await convert(
            session, Decimal(str(row.amount)), row.currency, primary_currency, row.date,
        )
        row.amount_primary = float(converted)


@router.get("/income", response_model=list[AssetIncomeRead])
async def list_workspace_income(
    year: int | None = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    rows = await asset_income_service.list_workspace_income(session, ctx.workspace.id, year=year)
    await _populate_income_primary_amounts(session, rows, ctx.user.primary_currency)
    return rows


@router.get("/income/summary", response_model=AssetIncomeMonthlySummary)
async def get_income_summary(
    year: int | None = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    rows = await asset_income_service.list_workspace_income(session, ctx.workspace.id, year=year, limit=10000)
    await _populate_income_primary_amounts(session, rows, ctx.user.primary_currency)
    return asset_income_service.get_monthly_summary(rows)


@router.patch("/income/{income_id}", response_model=AssetIncomeRead)
async def update_asset_income(
    income_id: uuid.UUID,
    data: AssetIncomeUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    income = await asset_income_service.update_income(session, income_id, ctx.workspace.id, data)
    if income is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income not found")
    return income


@router.delete("/income/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_income(
    income_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    deleted = await asset_income_service.delete_income(session, income_id, ctx.workspace.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income not found")


@router.get("/{asset_id}/income", response_model=list[AssetIncomeRead])
async def list_asset_income(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    # Deliberately not scoped to active holdings — a sold/archived asset can
    # still have income logged against it (see asset_income_service).
    income = await asset_income_service.list_asset_income(session, asset_id, ctx.workspace.id)
    if income is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    await _populate_income_primary_amounts(session, income, ctx.user.primary_currency)
    return income


@router.post("/{asset_id}/income", response_model=AssetIncomeRead, status_code=status.HTTP_201_CREATED)
async def add_asset_income(
    asset_id: uuid.UUID,
    data: AssetIncomeCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    income = await asset_income_service.add_income(session, asset_id, ctx.workspace.id, data)
    if income is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return income


@router.get("/{asset_id}/income/fetch-preview", response_model=DividendHistoryPreviewResponse)
async def preview_dividend_history(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Historical dividend/JCP/rendimento payouts from yfinance for this
    asset's ticker, excluding dates already logged. 422 for assets this
    doesn't apply to (manual/growth-rule, or no ticker)."""
    preview = await asset_income_service.get_dividend_history_preview(
        session, get_market_price_provider(), asset_id, ctx.workspace.id,
    )
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return preview


@router.post("/{asset_id}/income/fetch-apply", response_model=list[AssetIncomeRead], status_code=status.HTTP_201_CREATED)
async def apply_dividend_history(
    asset_id: uuid.UUID,
    data: DividendHistoryApplyRequest,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    applied = await asset_income_service.apply_dividend_history(
        session, asset_id, ctx.workspace.id, data.candidates, ctx.user_id,
    )
    if applied is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return await asset_income_service.list_asset_income(session, asset_id, ctx.workspace.id)


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    asset = await asset_service.get_asset(session, asset_id, ctx.workspace.id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    await _stamp_fx_rate_used(session, asset, ctx.user.primary_currency)
    return asset


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(
    data: AssetCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await asset_service.create_asset(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(
    asset_id: uuid.UUID,
    data: AssetUpdate,
    regenerate_growth: bool = Query(False),
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    asset = await asset_service.update_asset(
        session, asset_id, ctx.workspace.id, ctx.user_id, data, regenerate_growth=regenerate_growth
    )
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    deleted = await asset_service.delete_asset(session, asset_id, ctx.workspace.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")


@router.get("/{asset_id}/values", response_model=list[AssetValueRead])
async def list_asset_values(
    asset_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    values = await asset_service.get_asset_values(session, asset_id, ctx.workspace.id)
    if values is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return values


@router.get("/{asset_id}/value-trend")
async def get_asset_value_trend(
    asset_id: uuid.UUID,
    months: int = Query(12, ge=1, le=120),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    trend = await asset_service.get_asset_value_trend(session, asset_id, ctx.workspace.id, months=months)
    if trend is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return trend


@router.post("/{asset_id}/values", response_model=AssetValueRead, status_code=status.HTTP_201_CREATED)
async def add_asset_value(
    asset_id: uuid.UUID,
    data: AssetValueCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    value = await asset_service.add_asset_value(session, asset_id, ctx.workspace.id, data)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return value


@router.delete("/values/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_value(
    value_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    deleted = await asset_service.delete_asset_value(session, value_id, ctx.workspace.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Value not found")
