import uuid
from datetime import date as _date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset


class AssetIncome(Base):
    """A single dividend/JCP/rendimento receipt for a holding.

    Deliberately separate from `AssetTransaction`: income doesn't change
    units, average_price, or cost basis, so it never enters the buy/sell
    ledger replay (`asset_transaction_service._recompute`). Sold or
    archived assets can still receive income rows here — a dividend can be
    declared for a period when the position was still held, even if it was
    sold afterward.
    """

    __tablename__ = "asset_income"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # dividendo, jcp, rendimento, outro
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2))  # asset currency
    date: Mapped[_date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual, import
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asset: Mapped["Asset"] = relationship()
