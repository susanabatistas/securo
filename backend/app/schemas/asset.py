import uuid
from datetime import date as _date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AssetCreate(BaseModel):
    name: str
    type: str
    currency: str = "USD"
    units: Optional[Decimal] = None
    valuation_method: str = "manual"
    purchase_date: Optional[_date] = None
    purchase_price: Optional[Decimal] = None
    sell_date: Optional[_date] = None
    sell_price: Optional[Decimal] = None
    current_value: Optional[Decimal] = None  # convenience: creates initial AssetValue
    growth_type: Optional[str] = None
    growth_rate: Optional[Decimal] = None
    growth_frequency: Optional[str] = None
    growth_start_date: Optional[_date] = None
    is_archived: bool = False
    position: int = 0
    group_id: Optional[uuid.UUID] = None
    # Market-priced assets: ticker is enough to create one. The service
    # fetches the live quote on create and seeds the first AssetValue.
    ticker: Optional[str] = None
    ticker_exchange: Optional[str] = None
    maturity_date: Optional[_date] = None
    # Per-unit price for the opening buy of a market-priced holding (preço
    # médio model, consistent with the transaction ledger). When omitted, the
    # service seeds the buy at the live quote ("bought at market now").
    unit_price: Optional[Decimal] = None
    tax_category: Optional[str] = None  # renda_fixa, fii, acoes_etfs_cripto
    # Rebalancing target — this asset's target share (%) of its own wallet
    # (group_id), not of the total portfolio. Meaningless without a group.
    target_pct: Optional[Decimal] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    currency: Optional[str] = None
    units: Optional[Decimal] = None
    valuation_method: Optional[str] = None
    purchase_date: Optional[_date] = None
    purchase_price: Optional[Decimal] = None
    sell_date: Optional[_date] = None
    sell_price: Optional[Decimal] = None
    growth_type: Optional[str] = None
    growth_rate: Optional[Decimal] = None
    growth_frequency: Optional[str] = None
    growth_start_date: Optional[_date] = None
    is_archived: Optional[bool] = None
    position: Optional[int] = None
    # Use a sentinel to differentiate "don't change group" (field omitted)
    # from "remove from group" (explicit null). Pydantic's exclude_unset
    # already handles this via model_dump.
    group_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None
    ticker_exchange: Optional[str] = None
    # Manual override of the automatic stock checklist verdict. None clears
    # the override and falls back to the computed result.
    stock_checklist_status: Optional[str] = None
    tax_category: Optional[str] = None
    target_pct: Optional[Decimal] = None


class AssetRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    type: str
    currency: str
    units: Optional[float] = None
    valuation_method: str
    purchase_date: Optional[_date] = None
    purchase_price: Optional[float] = None
    sell_date: Optional[_date] = None
    sell_price: Optional[float] = None
    growth_type: Optional[str] = None
    growth_rate: Optional[float] = None
    growth_frequency: Optional[str] = None
    growth_start_date: Optional[_date] = None
    is_archived: bool
    position: int
    current_value: Optional[float] = None
    current_value_primary: Optional[float] = None
    gain_loss: Optional[float] = None
    gain_loss_primary: Optional[float] = None
    value_count: int = 0
    source: str = "manual"
    connection_id: Optional[uuid.UUID] = None
    isin: Optional[str] = None
    maturity_date: Optional[_date] = None
    group_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = None
    ticker_exchange: Optional[str] = None
    last_price: Optional[float] = None
    last_price_at: Optional[datetime] = None
    logo_url: Optional[str] = None
    # Ledger-derived fields (issue #235). average_price = weighted-average cost
    # per unit (preço médio); total_invested = cost basis of the held units;
    # realized_gain = cumulative gain/loss from sells; transaction_count lets
    # the UI know whether a holding is ledger-backed.
    average_price: Optional[float] = None
    total_invested: Optional[float] = None
    realized_gain: Optional[float] = None
    transaction_count: int = 0
    # Sum of all proventos (dividends/JCP/rendimentos) ever received for this
    # asset, in the asset's own currency — same basis as gain_loss/
    # total_invested, so the return % shown in the holdings table can fold
    # income in alongside price appreciation. None (not 0) when no income
    # rows exist, distinguishing "never received any" from "received R$0".
    income_total: Optional[float] = None
    # Raw manual override of the stock checklist verdict, or None if unset —
    # the computed verdict itself comes from GET /assets/{id}/stock-checklist.
    stock_checklist_status: Optional[str] = None
    # Resolved IR-estimator bucket: override if set, else the default derived
    # from type+ticker, or None when the estimator doesn't apply to this
    # asset (real_estate/vehicle/valuable/other) — None here is a legitimate
    # resolved state, not "unset".
    tax_category: Optional[str] = None
    # Rebalancing target — this asset's target share (%) of its own wallet,
    # not of the total portfolio. None = no target set, or the asset has no
    # wallet (group_id) for the % to be relative to.
    target_pct: Optional[float] = None
    # Cost basis converted to the user's primary currency at the *purchase*
    # FX rate (not today's) — already computed/cached by
    # asset_service/asset_transaction_service, just not surfaced until now.
    # None when the asset's currency matches the primary currency, or when
    # no rate was available to stamp it yet.
    purchase_price_primary: Optional[float] = None
    # FX rate used for purchase_price_primary, computed on read (not
    # stored) from the historical rate on purchase_date. None when the
    # asset's currency matches the primary currency.
    fx_rate_used: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AssetTransactionCreate(BaseModel):
    kind: str  # buy | sell
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    date: _date
    notes: Optional[str] = None


class AssetTransactionUpdate(BaseModel):
    kind: Optional[str] = None
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    date: Optional[_date] = None
    notes: Optional[str] = None


class AssetBuyCreate(BaseModel):
    """Find-or-create a ticker holding (in `group_id`) and record a buy."""

    ticker: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    date: _date
    name: Optional[str] = None
    group_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class AssetTransactionRead(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    kind: str
    quantity: float
    price: float
    fee: float
    date: _date
    source: str
    notes: Optional[str] = None
    # Denormalized holding context so the global transactions tab can render
    # rows without an extra per-row asset lookup.
    asset_name: Optional[str] = None
    ticker: Optional[str] = None
    currency: Optional[str] = None
    logo_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MarketSymbolQuote(BaseModel):
    """Live quote for a ticker, used by the add-asset form to preview value."""

    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    currency: str
    price: float
    quote_type: Optional[str] = None  # EQUITY, ETF, CRYPTOCURRENCY, MUTUALFUND, ...
    # Fully-formed logo URL if the provider can derive one. Caller stores
    # this verbatim on the asset; no further processing required.
    logo_url: Optional[str] = None


class MarketSymbolMatch(BaseModel):
    """A single search result returned by /assets/market/search."""

    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    quote_type: Optional[str] = None


class AssetValueCreate(BaseModel):
    amount: Decimal
    date: _date


class AssetValueRead(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    amount: float
    date: _date
    source: str

    model_config = ConfigDict(from_attributes=True)
