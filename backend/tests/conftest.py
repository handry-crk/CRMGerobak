import os
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["METRICS_API_KEY"] = "test-key"
os.environ["DEFAULT_ADMIN_PIN"] = "1234"

from app import db as dbmod  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    client = AsyncMongoMockClient(tz_aware=True)
    dbmod.set_db(client["test_stamp_bojot"])
    from app.security import rate_limiter
    rate_limiter.buckets.clear()
    yield
    dbmod.set_db(None)


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def admin(client):
    r = await client.post("/api/admin/login", json={"name": "Admin", "pin": "1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest_asyncio.fixture
async def outlets(client, admin):
    r = await client.post("/api/admin/seed", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["outlets"]
