import uuid
from datetime import date as _date
from typing import Optional

from pydantic import BaseModel


class B3RowSchema(BaseModel):
    ticker: str
    kind: str  # buy | sell
    quantity: float
    price: float
    date: _date


class B3IncomeRowSchema(BaseModel):
    ticker: str
    kind: str  # dividendo | jcp | rendimento
    amount: float
    date: _date


class B3TickerPreview(BaseModel):
    ticker: str
    buy_quantity: float
    buy_average_price: float
    sell_quantity: float
    sell_average_price: float
    first_date: _date
    last_date: _date
    row_count: int


class B3ImportPreviewResponse(BaseModel):
    # Individual parsed rows — sent back verbatim to /import/b3-apply so the
    # apply step doesn't need to re-upload/re-parse the file.
    rows: list[B3RowSchema]
    income_rows: list[B3IncomeRowSchema]
    # Aggregated by ticker, for the preview screen only.
    tickers: list[B3TickerPreview]
    skipped_count: int
    skipped_kinds: dict[str, int]


class B3ImportApplyRequest(BaseModel):
    rows: list[B3RowSchema]
    income_rows: list[B3IncomeRowSchema] = []
    group_id: Optional[uuid.UUID] = None


class B3ApplyErrorSchema(BaseModel):
    ticker: str
    kind: str
    date: _date
    reason: str


class B3ImportApplyResponse(BaseModel):
    applied_count: int
    income_applied_count: int
    errors: list[B3ApplyErrorSchema]
