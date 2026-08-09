from typing import Optional

from pydantic import BaseModel


class StockChecklistCriterion(BaseModel):
    key: str  # roe, revenue_cagr, profit_cagr, net_debt_to_ebitda
    value: Optional[float] = None
    threshold: float
    status: str  # pass, fail, not_evaluated


class StockChecklistResult(BaseModel):
    symbol: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    criteria: list[StockChecklistCriterion]
    overall_status: str  # aprovado, rever, a_evitar, nao_avaliado
    years_used: int
    # The asset's manual override (Asset.stock_checklist_status), if set —
    # the UI decides whether to show the computed or the overridden verdict.
    manual_override: Optional[str] = None
