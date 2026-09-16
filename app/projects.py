from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .realtime import manager
from .auth import require_user
from .database import get_db
from .models import Membership, Message, Project, User, utc_now

router = APIRouter(prefix="/projects", tags=["projects"])


class MessageCreate(BaseModel):
    message_code: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Z0-9-]+$",
    )
    content: str = Field(min_length=1, max_length=1000)


def get_project_or_404(project_id: int, database: Session) -> Project:
    project = database.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_project_access(
    project_id: int,
    user: User,
    database: Session,
) -> None:
    if user.role == "admin":
        return

    membership = database.scalar(
        select(Membership).where(
            Membership.project_id == project_id,
            Membership.user_id == user.id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You do not have active access to this project",
        )


@router.get("/{project_id}")
def read_project(
    project_id: int,
    user: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    project = get_project_or_404(project_id, database)
    require_project_access(project_id, user, database)

    messages = database.scalars(
        select(Message)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at)
    ).all()

    return {
        "id": project.id,
        "name": project.name,
        "messages": [
            {
                "id": message.id,
                "message_code": message.message_code,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@router.post("/{project_id}/messages", status_code=201)
async def create_message(
    project_id: int,
    payload: MessageCreate,
    response: Response,
    user: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    get_project_or_404(project_id, database)
    require_project_access(project_id, user, database)

    existing = database.scalar(
        select(Message).where(
            Message.message_code == payload.message_code
        )
    )
    if existing:
        same_request = (
            existing.project_id == project_id
            and existing.sender_id == user.id
            and existing.content == payload.content
        )
        if not same_request:
            raise HTTPException(
                status_code=409,
                detail="Message code already belongs to a different request",
            )

        response.status_code = 200
        return {
            "id": existing.id,
            "message_code": existing.message_code,
            "created": False,
        }

    message = Message(
        message_code=payload.message_code,
        project_id=project_id,
        sender_id=user.id,
        content=payload.content,
    )
    database.add(message)
    database.commit()
    database.refresh(message)
    await manager.broadcast(
        project_id,
        {
            "type": "private_message",
            "message": {
                "id": message.id,
                "message_code": message.message_code,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            },
        },
    )
    return {
        "id": message.id,
        "message_code": message.message_code,
        "created": True,
    }
@router.post("/{project_id}/members/{user_id}/grant")
def grant_membership(
    project_id: int,
    user_id: int,
    admin: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator role required",
        )

    get_project_or_404(project_id, database)

    target_user = database.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    membership = database.scalar(
        select(Membership).where(
            Membership.project_id == project_id,
            Membership.user_id == user_id,
        )
    )

    if membership and membership.status == "active":
        return {
            "membership_id": membership.id,
            "status": "active",
            "changed": False,
        }

    if membership is None:
        membership = Membership(
            project_id=project_id,
            user_id=user_id,
            status="active",
        )
        database.add(membership)
    else:
        membership.status = "active"
        membership.granted_at = utc_now()
        membership.revoked_at = None

    database.commit()
    database.refresh(membership)

    return {
        "membership_id": membership.id,
        "status": "active",
        "changed": True,
    }

@router.post("/{project_id}/members/{user_id}/revoke")
def revoke_membership(
    project_id: int,
    user_id: int,
    admin: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator role required",
        )

    get_project_or_404(project_id, database)

    membership = database.scalar(
        select(Membership).where(
            Membership.project_id == project_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    if membership.status == "revoked":
        return {
            "membership_id": membership.id,
            "status": "revoked",
            "changed": False,
        }

    membership.status = "revoked"
    membership.revoked_at = utc_now()
    database.commit()

    return {
        "membership_id": membership.id,
        "status": "revoked",
        "changed": True,
    }