"""Dividend/JCP/rendimento receipts — deliberately separate from the buy/
sell ledger (see app/models/asset_income.py docstring). Plain CRUD plus a
monthly aggregation for the Proventos chart; no replay/derivation math.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.models.user import User
from app.providers.market_price import MarketPriceProvider
from app.schemas.asset_income import (
    AssetIncomeByAsset,
    AssetIncomeCreate,
    AssetIncomeMonth,
    AssetIncomeMonthlySummary,
    AssetIncomeRead,
    AssetIncomeUpdate,
    DividendHistoryCandidate,
    DividendHistoryPreviewResponse,
)
from app.services.fx_rate_service import convert

_VALID_KINDS = {"dividendo", "jcp", "rendimento", "outro"}


def _get_quantity_at_date(transactions: list[AssetTransaction], target_date: date) -> Decimal:
    """Calculate the quantity held on a specific date by replaying transactions up to that date.
    
    Returns the units held on target_date (after any transaction on that date).
    Returns 0 if no transactions exist or all are after the target date.
    """
    qty = Decimal("0")
    # Sort by date and creation time to maintain order
    for tx in sorted(transactions, key=lambda t: (t.date, t.created_at or t.created_at)):
        if tx.date > target_date:
            break
        q = Decimal(str(tx.quantity or 0))
        if tx.kind == "buy":
            qty += q
        elif tx.kind == "sell":
            qty -= q
    return max(qty, Decimal("0"))  # Never negative (no shorting)


def _income_to_read(income: AssetIncome, asset: Optional[Asset] = None) -> AssetIncomeRead:
    return AssetIncomeRead(
        id=income.id,
        asset_id=income.asset_id,
        kind=income.kind,
        amount=float(income.amount),
        date=income.date,
        source=income.source,
        notes=income.notes,
        created_at=income.created_at,
        asset_name=asset.name if asset else None,
        ticker=asset.ticker if asset else None,
        currency=asset.currency if asset else None,
        logo_url=asset.logo_url if asset else None,
        asset_sold=bool(asset and (asset.sell_date is not None or asset.is_archived)),
    )


async def _load_asset(
    session: AsyncSession, asset_id: uuid.UUID, workspace_id: uuid.UUID
) -> Optional[Asset]:
    # Deliberately no sell_date/is_archived filter — a dividend can be
    # logged for a position that's since been sold or archived.
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def add_income(
    session: AsyncSession,
    asset_id: uuid.UUID,
    workspace_id: uuid.UUID,
    data: AssetIncomeCreate,
    *,
    source: str = "manual",
) -> Optional[AssetIncomeRead]:
    asset = await _load_asset(session, asset_id, workspace_id)
    if asset is None:
        return None
    income = AssetIncome(
        asset_id=asset_id,
        workspace_id=workspace_id,
        kind=data.kind if data.kind in _VALID_KINDS else "outro",
        amount=data.amount,
        date=data.date,
        source=source,
        notes=data.notes,
    )
    session.add(income)
    await session.flush()
    await session.commit()
    return _income_to_read(income, asset)


async def list_asset_income(
    session: AsyncSession, asset_id: uuid.UUID, workspace_id: uuid.UUID
) -> Optional[list[AssetIncomeRead]]:
    asset = await _load_asset(session, asset_id, workspace_id)
    if asset is None:
        return None
    result = await session.execute(
        select(AssetIncome)
        .where(AssetIncome.asset_id == asset_id)
        .order_by(AssetIncome.date.desc(), AssetIncome.created_at.desc())
    )
    return [_income_to_read(i, asset) for i in result.scalars().all()]


async def list_workspace_income(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    year: Optional[int] = None,
    limit: int = 1000,
) -> list[AssetIncomeRead]:
    query = (
        select(AssetIncome, Asset)
        .join(Asset, AssetIncome.asset_id == Asset.id)
        .where(AssetIncome.workspace_id == workspace_id)
    )
    if year is not None:
        query = query.where(extract("year", AssetIncome.date) == year)
    query = query.order_by(AssetIncome.date.desc(), AssetIncome.created_at.desc()).limit(limit)
    result = await session.execute(query)
    return [_income_to_read(i, asset) for i, asset in result.all()]


async def update_income(
    session: AsyncSession,
    income_id: uuid.UUID,
    workspace_id: uuid.UUID,
    data: AssetIncomeUpdate,
) -> Optional[AssetIncomeRead]:
    result = await session.execute(
        select(AssetIncome).where(AssetIncome.id == income_id, AssetIncome.workspace_id == workspace_id)
    )
    income = result.scalar_one_or_none()
    if income is None:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(income, key, value)
    await session.commit()
    asset = await session.get(Asset, income.asset_id)
    return _income_to_read(income, asset)


async def delete_income(session: AsyncSession, income_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(AssetIncome).where(AssetIncome.id == income_id, AssetIncome.workspace_id == workspace_id)
    )
    income = result.scalar_one_or_none()
    if income is None:
        return False
    await session.delete(income)
    await session.commit()
    return True


def get_monthly_summary(income_rows: list[AssetIncomeRead]) -> AssetIncomeMonthlySummary:
    """Pure aggregation over already-fetched rows (no DB access) — mirrors
    how ir_estimator_service/stock_checklist_service separate "fetch" from
    "compute" so the math is unit-testable without a database.

    Sums `amount_primary` (the historical-rate conversion to the user's
    primary currency, populated by the API layer) when present, falling
    back to the raw `amount` only for same-currency rows or when no rate
    was available — never mixes currencies by summing raw `amount` across
    rows, which previously showed a USD dividend as if it were that many
    BRL (confirmed by a user whose portfolio has both).
    """
    by_month: dict[str, dict[uuid.UUID, AssetIncomeByAsset]] = {}
    total = 0.0

    for row in income_rows:
        value = row.amount_primary if row.amount_primary is not None else row.amount
        month_key = row.date.strftime("%Y-%m")
        bucket = by_month.setdefault(month_key, {})
        existing = bucket.get(row.asset_id)
        if existing is None:
            bucket[row.asset_id] = AssetIncomeByAsset(
                asset_id=row.asset_id,
                asset_name=row.asset_name or "",
                ticker=row.ticker,
                total=value,
            )
        else:
            existing.total += value
        total += value

    months = [
        AssetIncomeMonth(
            month=month_key,
            total=sum(a.total for a in assets.values()),
            by_asset=sorted(assets.values(), key=lambda a: a.total, reverse=True),
        )
        for month_key, assets in sorted(by_month.items())
    ]
    return AssetIncomeMonthlySummary(months=months, total=total)


async def get_monthly_summary_for_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, *, year: Optional[int] = None
) -> AssetIncomeMonthlySummary:
    rows = await list_workspace_income(session, workspace_id, year=year, limit=10000)
    return get_monthly_summary(rows)


async def get_dividend_history_preview(
    session: AsyncSession,
    provider: MarketPriceProvider,
    asset_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Optional[DividendHistoryPreviewResponse]:
    """Fetch yfinance's dividend history for the asset's ticker and return
    only events not already logged (by exact date) — confirmed reliable for
    US and BR tickers alike (see market_price.YFinanceProvider.
    get_dividend_history). Raises 422 for assets this doesn't apply to
    (manual/growth-rule valuation, or no ticker)."""
    asset = await _load_asset(session, asset_id, workspace_id)
    if asset is None:
        return None
    if asset.valuation_method != "market_price" or not asset.ticker:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dividend history only applies to market-priced assets with a ticker",
        )

    get_history = getattr(provider, "get_dividend_history", None)
    events = await get_history(asset.ticker, since=asset.purchase_date) if get_history else []

    existing = set(
        (await session.execute(
            select(AssetIncome.date).where(AssetIncome.asset_id == asset_id)
        )).scalars().all()
    )

    # yfinance lumps dividendo/JCP into one "Dividends" action — default to
    # rendimento for funds (FIIs distribute monthly "rendimentos"),
    # dividendo otherwise. User can correct per-row before confirming.
    default_kind = "rendimento" if asset.type == "fund" else "dividendo"

    # Filter candidates based on ex-dividend date (data COM). A dividend is
    # eligible if the ex-date falls within the holding period:
    # - Must be on or after purchase_date (held the asset)
    # - If sold, must be on or before sell_date (still owned on ex-date)
    candidates = [
        DividendHistoryCandidate(date=e.date, amount=e.amount, kind=default_kind)
        for e in events
        if e.date not in existing and e.date >= asset.purchase_date and (asset.sell_date is None or e.date <= asset.sell_date)
    ]
    return DividendHistoryPreviewResponse(ticker=asset.ticker, candidates=candidates)


async def apply_dividend_history(
    session: AsyncSession,
    asset_id: uuid.UUID,
    workspace_id: uuid.UUID,
    candidates: list[DividendHistoryCandidate],
    user_id: uuid.UUID,
) -> Optional[int]:
    """Apply dividend history, multiplying by quantity held and converting to user's primary currency.
    
    For each candidate:
    1. Calculate quantity held on the dividend date (from transaction history, or fallback to asset.units)
    2. Multiply dividend amount by quantity
    3. Convert to user's primary currency if asset currency differs
    """
    asset = await _load_asset(session, asset_id, workspace_id)
    if asset is None:
        return None
    
    # Load user to get primary currency
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None
    
    primary_currency = user.primary_currency
    
    # Load all transactions for this asset to calculate quantity on each dividend date
    tx_result = await session.execute(
        select(AssetTransaction).where(AssetTransaction.asset_id == asset_id)
    )
    transactions = list(tx_result.scalars().all())
    
    applied = 0
    for candidate in candidates:
        # 1. Calculate quantity held on dividend date
        if transactions:
            # Replay transactions up to the dividend date
            qty_on_date = _get_quantity_at_date(transactions, candidate.date)
        else:
            # Fallback to current units if no transaction history (e.g., imported assets)
            qty_on_date = asset.units or Decimal("0")
        
        # 2. Multiply dividend by quantity
        dividend_amount = Decimal(str(candidate.amount)) * qty_on_date
        
        # 3. Convert to primary currency if needed
        if asset.currency != primary_currency:
            dividend_amount, _ = await convert(
                session, dividend_amount, asset.currency, primary_currency, candidate.date
            )
        
        # 4. Add income record with the calculated amount
        result = await add_income(
            session, asset_id, workspace_id,
            AssetIncomeCreate(
                kind=candidate.kind, 
                amount=dividend_amount, 
                date=candidate.date
            ),
            source="yfinance",
        )
        if result is not None:
            applied += 1
    return applied
