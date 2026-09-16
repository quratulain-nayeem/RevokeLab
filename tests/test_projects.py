import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "REVOKELAB_SESSION_SECRET",
    "test-only-key-never-used-in-production",
)

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Membership, Project, User


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    TestingSession = sessionmaker(bind=test_engine)
    Base.metadata.create_all(test_engine)

    with TestingSession() as database:
        admin = User(
            id=1,
            username="admin",
            password_hash=hash_password("admin-test-password"),
            role="admin",
        )
        alice = User(
            id=2,
            username="alice",
            password_hash=hash_password("alice-test-password"),
            role="member",
        )
        bob = User(
            id=3,
            username="bob",
            password_hash=hash_password("bob-test-password"),
            role="member",
        )
        database.add_all([admin, alice, bob])
        database.flush()

        project = Project(
            id=1,
            name="Project Red",
            created_by=admin.id,
        )
        database.add(project)
        database.flush()

        database.add(
            Membership(
                id=1,
                user_id=alice.id,
                project_id=project.id,
                status="active",
            )
        )
        database.commit()

    def override_database():
        with TestingSession() as database:
            yield database

    app.dependency_overrides[get_db] = override_database

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200


def test_bob_cannot_read_project(client: TestClient):
    login(client, "bob", "bob-test-password")

    response = client.get("/projects/1")

    assert response.status_code == 403


def test_message_creation_is_safe_to_retry(client: TestClient):
    login(client, "alice", "alice-test-password")
    payload = {
        "message_code": "DEMO-001",
        "content": "Private test message",
    }

    first = client.post("/projects/1/messages", json=payload)
    second = client.post("/projects/1/messages", json=payload)

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]


def test_revocation_blocks_and_grant_restores_access(client: TestClient):
    login(client, "admin", "admin-test-password")

    first_revoke = client.post("/projects/1/members/2/revoke")
    second_revoke = client.post("/projects/1/members/2/revoke")

    assert first_revoke.json()["changed"] is True
    assert second_revoke.json()["changed"] is False

    login(client, "alice", "alice-test-password")
    assert client.get("/projects/1").status_code == 403

    login(client, "admin", "admin-test-password")
    first_grant = client.post("/projects/1/members/2/grant")
    second_grant = client.post("/projects/1/members/2/grant")

    assert first_grant.json()["changed"] is True
    assert second_grant.json()["changed"] is False

    login(client, "alice", "alice-test-password")
    assert client.get("/projects/1").status_code == 200