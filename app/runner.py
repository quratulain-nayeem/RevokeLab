import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TimelineEvent:
    event_type: str
    detail: str
    occurred_at: datetime = field(default_factory=utc_now)


@dataclass
class ExperimentOutcome:
    result: str
    events: list[TimelineEvent]


class ExperimentExecutionError(Exception):
    def __init__(
        self,
        message: str,
        events: list[TimelineEvent],
    ) -> None:
        super().__init__(message)
        self.events = events


def required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


async def login(
    client: httpx.AsyncClient,
    username: str,
    password: str,
) -> None:
    response = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Login failed for {username}: HTTP {response.status_code}"
        )


async def execute_experiment(
    experiment_id: int,
    attempt_number: int,
    authorization_mode: str,
    cutoff_seconds: int,
) -> ExperimentOutcome:
    base_url = required_setting("REVOKELAB_BASE_URL").rstrip("/")
    alice_username = required_setting("REVOKELAB_ALICE_USERNAME")
    alice_password = required_setting("REVOKELAB_ALICE_PASSWORD")
    admin_username = required_setting("REVOKELAB_ADMIN_USERNAME")
    admin_password = required_setting("REVOKELAB_ADMIN_PASSWORD")

    websocket_base = (
        base_url.replace("https://", "wss://", 1)
        if base_url.startswith("https://")
        else base_url.replace("http://", "ws://", 1)
    )

    events: list[TimelineEvent] = []
    alice_id: int | None = None
    admin_ready = False

    async with (
        httpx.AsyncClient(
            base_url=base_url,
            timeout=10,
            follow_redirects=True,
        ) as alice_client,
        httpx.AsyncClient(
            base_url=base_url,
            timeout=10,
            follow_redirects=True,
        ) as admin_client,
    ):
        try:
            await login(alice_client, alice_username, alice_password)
            alice_response = await alice_client.get("/auth/me")
            alice_response.raise_for_status()
            alice_id = alice_response.json()["id"]

            events.append(
                TimelineEvent(
                    "alice_authenticated",
                    f"Alice authenticated as user {alice_id}",
                )
            )

            cookie_header = "; ".join(
                f"{name}={value}"
                for name, value in alice_client.cookies.items()
            )

            websocket_url = (
                f"{websocket_base}/ws/{authorization_mode}/projects/1"
            )

            async with websockets.connect(
                websocket_url,
                additional_headers={"Cookie": cookie_header},
                open_timeout=5,
            ) as websocket:
                connected = json.loads(
                    await asyncio.wait_for(websocket.recv(), timeout=5)
                )
                if connected.get("type") != "connected":
                    raise RuntimeError("WebSocket did not confirm connection")

                events.append(
                    TimelineEvent(
                        "websocket_connected",
                        f"Opened {authorization_mode} connection",
                    )
                )

                await login(admin_client, admin_username, admin_password)
                admin_ready = True

                revoke_response = await admin_client.post(
                    f"/projects/1/members/{alice_id}/revoke"
                )
                revoke_response.raise_for_status()

                events.append(
                    TimelineEvent(
                        "access_revoked",
                        f"Alice removed; cutoff is {cutoff_seconds} seconds",
                    )
                )

                await asyncio.sleep(cutoff_seconds)

                message_code = (
                    f"EXPERIMENT-{experiment_id}-A{attempt_number}"
                )
                message_response = await admin_client.post(
                    "/projects/1/messages",
                    json={
                        "message_code": message_code,
                        "content": (
                            "Private data created after access removal"
                        ),
                    },
                )
                message_response.raise_for_status()

                events.append(
                    TimelineEvent(
                        "private_message_created",
                        f"Created {message_code} after the cutoff",
                    )
                )

                try:
                    observed = json.loads(
                        await asyncio.wait_for(
                            websocket.recv(),
                            timeout=3,
                        )
                    )
                except asyncio.TimeoutError:
                    events.append(
                        TimelineEvent(
                            "observation_timeout",
                            "No WebSocket event arrived within 3 seconds",
                        )
                    )
                    return ExperimentOutcome("inconclusive", events)

                events.append(
                    TimelineEvent(
                        "websocket_observation",
                        json.dumps(observed, sort_keys=True),
                    )
                )

                if observed.get("type") == "private_message":
                    return ExperimentOutcome("fail", events)

                if observed.get("type") == "access_revoked":
                    return ExperimentOutcome("pass", events)

                return ExperimentOutcome("inconclusive", events)

        except Exception as error:
            events.append(
                TimelineEvent(
                    "execution_error",
                    f"{type(error).__name__}: {error}",
                )
            )
            raise ExperimentExecutionError(str(error), events) from error

        finally:
            if admin_ready and alice_id is not None:
                cleanup = await admin_client.post(
                    f"/projects/1/members/{alice_id}/grant"
                )
                events.append(
                    TimelineEvent(
                        "cleanup_completed",
                        f"Restored Alice; HTTP {cleanup.status_code}",
                    )
                )