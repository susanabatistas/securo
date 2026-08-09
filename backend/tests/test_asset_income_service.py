import uuid
from datetime import date

from app.schemas.asset_income import AssetIncomeRead
from app.services.asset_income_service import get_monthly_summary

ASSET_A = uuid.uuid4()
ASSET_B = uuid.uuid4()


def _row(asset_id, name, ticker, amount, d) -> AssetIncomeRead:
    return AssetIncomeRead(
        id=uuid.uuid4(), asset_id=asset_id, kind="dividendo", amount=amount, date=d,
        source="manual", created_at=d, asset_name=name, ticker=ticker, currency="BRL",
    )


def test_get_monthly_summary_groups_by_month_and_asset():
    rows = [
        _row(ASSET_A, "Petrobras", "PETR4", 10.0, date(2026, 3, 5)),
        _row(ASSET_A, "Petrobras", "PETR4", 5.0, date(2026, 3, 20)),
        _row(ASSET_B, "HGLG11", "HGLG11", 20.0, date(2026, 3, 10)),
        _row(ASSET_A, "Petrobras", "PETR4", 8.0, date(2026, 4, 1)),
    ]
    summary = get_monthly_summary(rows)

    assert summary.total == 43.0
    assert [m.month for m in summary.months] == ["2026-03", "2026-04"]

    march = summary.months[0]
    assert march.total == 35.0
    by_asset = {a.asset_id: a.total for a in march.by_asset}
    assert by_asset[ASSET_A] == 15.0
    assert by_asset[ASSET_B] == 20.0
    # Sorted descending by total within the month.
    assert march.by_asset[0].asset_id == ASSET_B

    april = summary.months[1]
    assert april.total == 8.0


def test_get_monthly_summary_empty():
    summary = get_monthly_summary([])
    assert summary.months == []
    assert summary.total == 0
