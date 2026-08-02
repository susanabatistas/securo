import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.recurring_transaction import RecurringTransactionCreate, RecurringTransactionUpdate
from app.services.recurring_transaction_service import (
    create_recurring_transaction,
    delete_recurring_transaction,
    generate_pending,
    get_occurrences_in_range,
    get_recurring_transaction,
    get_recurring_transactions,
    update_recurring_transaction,
)


@pytest_asyncio.fixture
async def test_account_for_recurring(session: AsyncSession, test_user) -> Account:
    account = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="RecurAcc",
        type="checking",
        balance=Decimal("10000"),
        currency="BRL",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_recurring_transaction(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    data = RecurringTransactionCreate(
        description="Netflix",
        amount=Decimal("39.90"),
        type="debit",
        frequency="monthly",
        start_date=date(2025, 1, 15),
        account_id=test_account_for_recurring.id,
    )
    rec = await create_recurring_transaction(session, test_workspace.id, test_user.id, data)

    assert rec.id is not None
    assert rec.description == "Netflix"
    assert rec.amount == Decimal("39.90")
    assert rec.frequency == "monthly"
    assert rec.next_occurrence == date(2025, 1, 15)
    assert rec.is_active is True


@pytest.mark.asyncio
async def test_create_with_skip_first(session: AsyncSession, test_user, test_workspace, test_account_for_recurring):
    data = RecurringTransactionCreate(
        description="Rent",
        amount=Decimal("2000"),
        type="debit",
        frequency="monthly",
        start_date=date(2025, 3, 1),
        account_id=test_account_for_recurring.id,
        skip_first=True,
    )
    rec = await create_recurring_transaction(session, test_workspace.id, test_user.id, data)

    # skip_first should advance to next month
    assert rec.start_date == date(2025, 3, 1)
    assert rec.next_occurrence == date(2025, 4, 1)


@pytest.mark.asyncio
async def test_get_recurring_transactions(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    for desc, dt in [("Sub1", date(2025, 1, 1)), ("Sub2", date(2025, 2, 1))]:
        await create_recurring_transaction(
            session,
            test_workspace.id, test_user.id,
            RecurringTransactionCreate(
                description=desc,
                amount=Decimal("10"),
                type="debit",
                frequency="monthly",
                start_date=dt,
                account_id=test_account_for_recurring.id,
            ),
        )

    result = await get_recurring_transactions(session, test_workspace.id)
    assert len(result) >= 2

    # Ordered by next_occurrence
    dates = [r.next_occurrence for r in result]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_get_recurring_transaction_by_id(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    created = await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="Lookup",
            amount=Decimal("50"),
            type="debit",
            frequency="weekly",
            start_date=date(2025, 6, 1),
            account_id=test_account_for_recurring.id,
        ),
    )
    fetched = await get_recurring_transaction(session, created.id, test_workspace.id)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_recurring_transaction_not_found(session: AsyncSession, test_user, test_workspace):
    result = await get_recurring_transaction(session, uuid.uuid4(), test_workspace.id)
    assert result is None


@pytest.mark.asyncio
async def test_update_recurring_transaction(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    rec = await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="Old",
            amount=Decimal("100"),
            type="debit",
            frequency="monthly",
            start_date=date(2025, 1, 1),
            account_id=test_account_for_recurring.id,
        ),
    )
    updated = await update_recurring_transaction(
        session,
        rec.id,
        test_workspace.id,
        RecurringTransactionUpdate(description="Updated", amount=Decimal("150")),
    )
    assert updated is not None
    assert updated.description == "Updated"
    assert updated.amount == Decimal("150")


@pytest.mark.asyncio
async def test_update_recurring_not_found(session: AsyncSession, test_user, test_workspace):
    result = await update_recurring_transaction(
        session,
        uuid.uuid4(),
        test_workspace.id,
        RecurringTransactionUpdate(description="Nope"),
    )
    assert result is None


@pytest.mark.asyncio
async def test_delete_recurring_transaction(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    rec = await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="ToDelete",
            amount=Decimal("10"),
            type="debit",
            frequency="monthly",
            start_date=date(2025, 1, 1),
            account_id=test_account_for_recurring.id,
        ),
    )
    assert await delete_recurring_transaction(session, rec.id, test_workspace.id) is True
    assert await get_recurring_transaction(session, rec.id, test_workspace.id) is None


@pytest.mark.asyncio
async def test_delete_recurring_not_found(session: AsyncSession, test_user, test_workspace):
    assert await delete_recurring_transaction(session, uuid.uuid4(), test_workspace.id) is False


# ---------------------------------------------------------------------------
# get_occurrences_in_range
# ---------------------------------------------------------------------------


def test_get_occurrences_in_range_monthly():
    occurrences = get_occurrences_in_range(
        start=date(2025, 1, 1),
        frequency="monthly",
        end_date=None,
        range_start=date(2025, 3, 1),
        range_end=date(2025, 6, 1),
    )
    assert occurrences == [date(2025, 3, 1), date(2025, 4, 1), date(2025, 5, 1)]


def test_get_occurrences_in_range_respects_end_date():
    occurrences = get_occurrences_in_range(
        start=date(2025, 1, 1),
        frequency="monthly",
        end_date=date(2025, 4, 15),
        range_start=date(2025, 3, 1),
        range_end=date(2025, 12, 1),
    )
    assert occurrences == [date(2025, 3, 1), date(2025, 4, 1)]


def test_get_occurrences_in_range_weekly():
    occurrences = get_occurrences_in_range(
        start=date(2025, 1, 6),
        frequency="weekly",
        end_date=None,
        range_start=date(2025, 1, 6),
        range_end=date(2025, 1, 27),
    )
    assert len(occurrences) == 3  # Jan 6, 13, 20 (range_end is exclusive)


def test_get_occurrences_in_range_empty():
    occurrences = get_occurrences_in_range(
        start=date(2025, 6, 1),
        frequency="monthly",
        end_date=None,
        range_start=date(2025, 1, 1),
        range_end=date(2025, 3, 1),
    )
    assert occurrences == []


def test_get_occurrences_in_range_monthly_day_31_does_not_drift():
    # Regression test for #67: after Feb clamps to 28, subsequent months must
    # recover to their true month-end (31 / 30 / 31 / 30) instead of sticking at 28.
    occurrences = get_occurrences_in_range(
        start=date(2026, 1, 31),
        frequency="monthly",
        end_date=None,
        range_start=date(2026, 1, 1),
        range_end=date(2026, 7, 1),
        intended_day=31,
    )
    assert occurrences == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 30),
    ]


def test_get_occurrences_in_range_monthly_day_30_does_not_drift():
    occurrences = get_occurrences_in_range(
        start=date(2026, 1, 30),
        frequency="monthly",
        end_date=None,
        range_start=date(2026, 1, 1),
        range_end=date(2026, 7, 1),
        intended_day=30,
    )
    assert occurrences == [
        date(2026, 1, 30),
        date(2026, 2, 28),
        date(2026, 3, 30),
        date(2026, 4, 30),
        date(2026, 5, 30),
        date(2026, 6, 30),
    ]


def test_get_occurrences_in_range_monthly_day_29_does_not_drift():
    occurrences = get_occurrences_in_range(
        start=date(2026, 1, 29),
        frequency="monthly",
        end_date=None,
        range_start=date(2026, 1, 1),
        range_end=date(2026, 7, 1),
        intended_day=29,
    )
    assert occurrences == [
        date(2026, 1, 29),
        date(2026, 2, 28),
        date(2026, 3, 29),
        date(2026, 4, 29),
        date(2026, 5, 29),
        date(2026, 6, 29),
    ]


# ---------------------------------------------------------------------------
# generate_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_pending(session: AsyncSession, test_user, test_workspace, test_account_for_recurring):
    rec = await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="Monthly Sub",
            amount=Decimal("29.90"),
            type="debit",
            frequency="monthly",
            start_date=date(2025, 1, 1),
            account_id=test_account_for_recurring.id,
        ),
    )

    count = await generate_pending(session, test_user.id, up_to=date(2025, 3, 15))
    assert count == 3  # Jan, Feb, Mar

    # Verify transactions were created
    result = await session.execute(
        select(Transaction).where(
            Transaction.user_id == test_user.id,
            Transaction.source == "recurring",
            Transaction.description == "Monthly Sub",
        )
    )
    txns = result.scalars().all()
    assert len(txns) == 3

    # next_occurrence should be advanced past cutoff
    await session.refresh(rec)
    assert rec.next_occurrence == date(2025, 4, 1)


@pytest.mark.asyncio
async def test_generate_pending_deactivates_past_end_date(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    rec = await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="Short Sub",
            amount=Decimal("10"),
            type="debit",
            frequency="monthly",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 2, 15),
            account_id=test_account_for_recurring.id,
        ),
    )

    count = await generate_pending(session, test_user.id, up_to=date(2025, 12, 31))
    # Should create Jan and Feb (Feb 1 <= Feb 15), then deactivate
    assert count == 2

    await session.refresh(rec)
    assert rec.is_active is False


@pytest.mark.asyncio
async def test_generate_pending_no_duplicates(
    session: AsyncSession, test_user, test_workspace, test_account_for_recurring
):
    await create_recurring_transaction(
        session,
        test_workspace.id, test_user.id,
        RecurringTransactionCreate(
            description="NoDup",
            amount=Decimal("5"),
            type="debit",
            frequency="monthly",
            start_date=date(2025, 1, 1),
            account_id=test_account_for_recurring.id,
        ),
    )

    # Generate once
    count1 = await generate_pending(session, test_user.id, up_to=date(2025, 3, 1))
    # Generate again with same cutoff — should produce 0
    count2 = await generate_pending(session, test_user.id, up_to=date(2025, 3, 1))
    assert count1 == 3
    assert count2 == 0
