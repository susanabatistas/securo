import uuid
from datetime import date as _date
from typing import Optional

from pydantic import BaseModel


class IRAssetEstimate(BaseModel):
    asset_id: uuid.UUID
    name: str
    ticker: Optional[str] = None
    tax_category: str  # renda_fixa, fii, acoes_etfs_cripto
    gain: float
    purchase_date: Optional[_date] = None
    days_held: Optional[int] = None
    rate_pct: float
    estimated_tax: float
    note: Optional[str] = None


class IREstimateResponse(BaseModel):
    assets: list[IRAssetEstimate]
    total_estimated_tax: float
    # False when the user's primary (display) currency isn't BRL: the rates
    # and thresholds below are Brazilian personal-income-tax rules and only
    # make sense applied to a BRL-denominated gain. `assets`/`total_estimated_tax`
    # are left empty rather than computed against a foreign-currency amount.
    applicable: bool = True
    disclaimer: str = (
        "Estimativa com base nas regras gerais de IR para pessoa física, calculada como se cada "
        "posição fosse vendida integralmente hoje. Não considera isenções por volume de vendas do "
        "mês, compensação de perdas, ou particularidades do seu caso. Não é orientação fiscal."
    )
