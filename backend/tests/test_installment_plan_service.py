import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.schemas.transaction import InstallmentPlanCreate
from app.services.transaction_service import create_installment_plan


@pytest_asyncio.fixture
async def installment_account(session: AsyncSession, test_user) -> Account:
    account = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="InstallmentAcc",
        type="checking",
        balance=Decimal("10000"),
        currency="BRL",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_create_installment_plan_basic(
    session: AsyncSession, test_user, test_workspace, test_categories, installment_account
):
    data = InstallmentPlanCreate(
        description="Alura",
        account_id=installment_account.id,
        category_id=test_categories[0].id,
        amount=Decimal("59.60"),
        total_installments=24,
        first_installment_date=date(2024, 5, 22),
    )
    txns = await create_installment_plan(session, test_workspace.id, test_user.id, data)

    assert len(txns) == 24
    assert [t.installment_number for t in txns] == list(range(1, 25))
    for t in txns:
        assert t.description == "Alura"
        assert t.source == "manual"
        assert t.category_id == test_categories[0].id
        assert t.total_installments == 24
        assert t.installment_total_amount == Decimal("1430.40")
        assert t.installment_purchase_date == date(2024, 5, 22)
        assert t.date.day == 22

    assert txns[0].date == date(2024, 5, 22)
    assert txns[1].date == date(2024, 6, 22)
    assert txns[-1].date == date(2026, 4, 22)


@pytest.mark.asyncio
async def test_create_installment_plan_month_end_clamping(
    session: AsyncSession, test_user, test_workspace, test_categories, installment_account
):
    data = InstallmentPlanCreate(
        description="Clamped plan",
        account_id=installment_account.id,
        category_id=test_categories[0].id,
        amount=Decimal("10"),
        total_installments=3,
        first_installment_date=date(2025, 1, 31),
    )
    txns = await create_installment_plan(session, test_workspace.id, test_user.id, data)

    assert [t.date for t in txns] == [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]


@pytest.mark.asyncio
async def test_create_installment_plan_weekly_and_yearly(
    session: AsyncSession, test_user, test_workspace, test_categories, installment_account
):
    weekly = await create_installment_plan(
        session, test_workspace.id, test_user.id,
        InstallmentPlanCreate(
            description="Weekly plan", account_id=installment_account.id,
            category_id=test_categories[0].id, amount=Decimal("5"),
            total_installments=3, first_installment_date=date(2025, 1, 1),
            frequency="weekly",
        ),
    )
    assert [t.date for t in weekly] == [date(2025, 1, 1), date(2025, 1, 8), date(2025, 1, 15)]

    yearly = await create_installment_plan(
        session, test_workspace.id, test_user.id,
        InstallmentPlanCreate(
            description="Yearly plan", account_id=installment_account.id,
            category_id=test_categories[0].id, amount=Decimal("100"),
            total_installments=2, first_installment_date=date(2024, 2, 29),
            frequency="yearly",
        ),
    )
    assert [t.date for t in yearly] == [date(2024, 2, 29), date(2025, 2, 28)]


@pytest.mark.asyncio
async def test_create_installment_plan_account_not_found(
    session: AsyncSession, test_user, test_workspace
):
    data = InstallmentPlanCreate(
        description="Orphan plan",
        account_id=uuid.uuid4(),
        amount=Decimal("10"),
        total_installments=2,
        first_installment_date=date(2025, 1, 1),
    )
    with pytest.raises(ValueError, match="Account not found"):
        await create_installment_plan(session, test_workspace.id, test_user.id, data)


@pytest.mark.asyncio
async def test_create_installment_plan_applies_rules_when_no_category(
    session: AsyncSession, test_user, test_workspace, test_categories, installment_account
):
    rule = Rule(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="UBER auto",
        conditions_op="or",
        conditions=[{"field": "description", "op": "starts_with", "value": "UBER"}],
        actions=[{"op": "set_category", "value": str(test_categories[1].id)}],
        priority=10,
        is_active=True,
    )
    session.add(rule)
    await session.commit()

    data = InstallmentPlanCreate(
        description="UBER PASS",
        account_id=installment_account.id,
        amount=Decimal("20"),
        total_installments=4,
        first_installment_date=date(2025, 1, 1),
    )
    txns = await create_installment_plan(session, test_workspace.id, test_user.id, data)

    assert all(t.category_id == test_categories[1].id for t in txns)


@pytest.mark.asyncio
async def test_create_installment_plan_atomicity(
    session: AsyncSession, test_user, test_workspace, installment_account
):
    data = InstallmentPlanCreate(
        description="Failing Plan",
        account_id=installment_account.id,
        amount=Decimal("10"),
        total_installments=5,
        first_installment_date=date(2025, 1, 1),
    )
    with patch(
        "app.services.transaction_service.apply_rules_to_transaction",
        side_effect=[None, None, RuntimeError("boom"), None, None],
    ):
        with pytest.raises(RuntimeError):
            await create_installment_plan(session, test_workspace.id, test_user.id, data)

    await session.rollback()
    count = (
        await session.execute(
            select(func.count(Transaction.id)).where(Transaction.description == "Failing Plan")
        )
    ).scalar_one()
    assert count == 0
