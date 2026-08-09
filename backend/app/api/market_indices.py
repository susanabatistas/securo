from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import current_active_user
from app.core.config import get_settings
from app.models.user import User
from app.providers.bcb import get_bcb_provider

router = APIRouter(prefix="/api/market-indices", tags=["market-indices"])


def _ensure_bcb_enabled() -> None:
    if not get_settings().bcb_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BCB integration disabled")


@router.get("/cdi-12m")
async def cdi_12m(
    user: User = Depends(current_active_user),
):
    """Trailing 12-month accumulated CDI (%), compounded from BCB SGS série 4390."""
    _ensure_bcb_enabled()
    value = await get_bcb_provider().get_cdi_accumulated(months=12)
    if value is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not fetch CDI from BCB")
    return {"cdi_12m_pct": float(value)}


@router.get("/usd-brl")
async def usd_brl(
    user: User = Depends(current_active_user),
):
    """Latest USD/BRL PTAX (sell) rate from BCB SGS série 1."""
    _ensure_bcb_enabled()
    quote = await get_bcb_provider().get_usd_brl_ptax()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not fetch USD/BRL PTAX from BCB")
    return {"rate": float(quote.value), "as_of": quote.date.isoformat(), "source": "bcb_ptax"}
