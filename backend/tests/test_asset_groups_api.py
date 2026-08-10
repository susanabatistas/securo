import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_create_group_with_target_pct(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/asset-groups",
        headers=auth_headers,
        json={"name": "ETFs", "target_pct": 20},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["target_pct"] == 20.0


@pytest.mark.asyncio
async def test_create_group_without_target_pct_defaults_to_none(client: AsyncClient, auth_headers: dict):
    response = await client.post("/api/asset-groups", headers=auth_headers, json={"name": "No target"})
    assert response.status_code == 201, response.text
    assert response.json()["target_pct"] is None


@pytest.mark.asyncio
async def test_update_group_sets_target_pct(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/asset-groups", headers=auth_headers, json={"name": "Renda Fixa"})
    group_id = create.json()["id"]

    response = await client.patch(
        f"/api/asset-groups/{group_id}", headers=auth_headers, json={"target_pct": 40}
    )
    assert response.status_code == 200, response.text
    assert response.json()["target_pct"] == 40.0


@pytest.mark.asyncio
async def test_update_group_clears_target_pct(client: AsyncClient, auth_headers: dict):
    create = await client.post(
        "/api/asset-groups", headers=auth_headers, json={"name": "Ações", "target_pct": 60}
    )
    group_id = create.json()["id"]

    response = await client.patch(
        f"/api/asset-groups/{group_id}", headers=auth_headers, json={"target_pct": None}
    )
    assert response.status_code == 200, response.text
    assert response.json()["target_pct"] is None


@pytest.mark.asyncio
async def test_list_groups_includes_target_pct(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User
):
    await client.post("/api/asset-groups", headers=auth_headers, json={"name": "FIIs", "target_pct": 15})
    response = await client.get("/api/asset-groups", headers=auth_headers)
    assert response.status_code == 200
    fiis = next(g for g in response.json() if g["name"] == "FIIs")
    assert fiis["target_pct"] == 15.0
