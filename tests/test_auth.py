import os

os.environ.setdefault(
    "REVOKELAB_SESSION_SECRET",
    "test-only-key-never-used-in-production",
)

from fastapi.testclient import TestClient

from app.auth import hash_password, verify_password
from app.main import app


def test_password_is_hashed_and_verifiable():
    password = "temporary-test-password"
    stored_hash = hash_password(password)

    assert stored_hash != password
    assert verify_password(password, stored_hash)
    assert not verify_password("wrong-password", stored_hash)


def test_protected_route_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_incorrect_credentials_return_401():
    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            data={
                "username": "nonexistent-user",
                "password": "wrong-password",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"