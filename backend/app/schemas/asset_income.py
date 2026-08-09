import uuid
from datetime import date as _date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AssetIncomeCreate(BaseModel):
    kind: str  # dividendo, jcp, rendimento, outro
    amount: Decimal
    date: _date
    notes: Optional[str] = None


class AssetIncomeUpdate(BaseModel):
    kind: Optional[str] = None
    amount: Optional[Decimal] = None
    date: Optional[_date] = None
    notes: Optional[str] = None


class AssetIncomeRead(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    kind: str
    amount: float
    date: _date
    source: str
    notes: Optional[str] = None
    created_at: datetime
    # Denormalized holding context, same convention as AssetTransactionRead —
    # cross-holding views (the Proventos tab) render without a per-row lookup.
    asset_name: Optional[str] = None
    ticker: Optional[str] = None
    currency: Optional[str] = None
    logo_url: Optional[str] = None
    # Whether the holding is sold/archived — the manual-add picker and the
    # Proventos list both want to flag this without a second asset fetch.
    asset_sold: bool = False
    # `amount` converted to the user's primary currency, at the historical
    # rate on `date` — populated by the API layer (see
    # app/api/assets.py::_populate_income_primary_amounts), not here, since
    # it needs a DB round-trip. None until populated; aggregation
    # (get_monthly_summary) must fall back to `amount` when it's missing
    # instead of silently treating every currency as the primary one.
    amount_primary: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AssetIncomeByAsset(BaseModel):
    asset_id: uuid.UUID
    asset_name: str
    ticker: Optional[str] = None
    total: float


class AssetIncomeMonth(BaseModel):
    month: str  # "YYYY-MM"
    total: float
    by_asset: list[AssetIncomeByAsset]


class AssetIncomeMonthlySummary(BaseModel):
    months: list[AssetIncomeMonth]
    total: float


class DividendHistoryCandidate(BaseModel):
    date: _date
    amount: float
    # Suggested default (fund -> rendimento, else dividendo) — yfinance
    # doesn't distinguish dividendo from JCP, so this is editable before
    # confirming, same as the B3 import preview.
    kind: str


class DividendHistoryPreviewResponse(BaseModel):
    ticker: str
    candidates: list[DividendHistoryCandidate]


class DividendHistoryApplyRequest(BaseModel):
    candidates: list[DividendHistoryCandidate]
