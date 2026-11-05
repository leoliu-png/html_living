import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers.auth import me


class FakeRequest:
    def __init__(self, *, session=None):
        self.session = session or {}


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "admin@feedmob.com,ops@feedmob.com")


@pytest.mark.anyio
async def test_me_returns_current_user_and_admin_flag() -> None:
    response = await me(
        FakeRequest(
            session={
                "user": {
                    "sub": "admin-1",
                    "email": "admin@feedmob.com",
                    "name": "Admin",
                }
            }
        )
    )

    assert response["user"]["email"] == "admin@feedmob.com"
    assert response["is_admin"] is True


@pytest.mark.anyio
async def test_me_returns_false_for_non_admin_user() -> None:
    response = await me(
        FakeRequest(
            session={
                "user": {
                    "sub": "user-1",
                    "email": "alice@feedmob.com",
                    "name": "Alice",
                }
            }
        )
    )

    assert response["user"]["email"] == "alice@feedmob.com"
    assert response["is_admin"] is False


@pytest.mark.anyio
async def test_me_rejects_missing_session_user() -> None:
    with pytest.raises(HTTPException) as exc:
        await me(FakeRequest())

    assert exc.value.status_code == 401
