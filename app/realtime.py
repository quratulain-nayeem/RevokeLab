from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .database import SessionLocal
from .models import Membership, Project, User

router = APIRouter(tags=["realtime"])


@dataclass
class ActiveConnection:
    websocket: WebSocket
    user_id: int
    project_id: int
    authorization_mode: str


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[ActiveConnection] = []

    async def connect(
        self,
        websocket: WebSocket,
        user_id: int,
        project_id: int,
        authorization_mode: str,
    ) -> ActiveConnection:
        await websocket.accept()

        connection = ActiveConnection(
            websocket=websocket,
            user_id=user_id,
            project_id=project_id,
            authorization_mode=authorization_mode,
        )
        self.connections.append(connection)
        return connection

    def disconnect(self, connection: ActiveConnection) -> None:
        if connection in self.connections:
            self.connections.remove(connection)

    def user_still_has_access(
        self,
        user_id: int,
        project_id: int,
    ) -> bool:
        with SessionLocal() as database:
            user = database.get(User, user_id)
            if user is None or not user.is_active:
                return False

            if user.role == "admin":
                return True

            membership = database.scalar(
                select(Membership).where(
                    Membership.user_id == user_id,
                    Membership.project_id == project_id,
                    Membership.status == "active",
                )
            )
            return membership is not None

    async def broadcast(self, project_id: int, payload: dict) -> None:
        project_connections = [
            connection
            for connection in self.connections.copy()
            if connection.project_id == project_id
        ]

        for connection in project_connections:
            if (
                connection.authorization_mode == "continuous"
                and not self.user_still_has_access(
                    connection.user_id,
                    project_id,
                )
            ):
                await connection.websocket.send_json(
                    {
                        "type": "access_revoked",
                        "detail": "Project access has been removed",
                    }
                )
                await connection.websocket.close(code=4403)
                self.disconnect(connection)
                continue

            try:
                await connection.websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws/{authorization_mode}/projects/{project_id}")
async def project_websocket(
    websocket: WebSocket,
    authorization_mode: str,
    project_id: int,
) -> None:
    if authorization_mode not in {"connection-only", "continuous"}:
        await websocket.close(code=4400)
        return

    user_id = websocket.session.get("user_id")
    if user_id is None:
        await websocket.close(code=4401)
        return

    with SessionLocal() as database:
        user = database.get(User, user_id)
        project = database.get(Project, project_id)

        if user is None or not user.is_active:
            await websocket.close(code=4401)
            return

        if project is None:
            await websocket.close(code=4404)
            return

        membership = database.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.project_id == project_id,
                Membership.status == "active",
            )
        )

        if user.role != "admin" and membership is None:
            await websocket.close(code=4403)
            return

    connection = await manager.connect(
        websocket,
        user_id,
        project_id,
        authorization_mode,
    )

    await websocket.send_json(
        {
            "type": "connected",
            "project_id": project_id,
            "authorization_mode": authorization_mode,
        }
    )

    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(connection)