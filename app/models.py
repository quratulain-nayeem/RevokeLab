from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('member', 'admin')",
            name="ck_users_valid_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    created_projects: Mapped[list["Project"]] = relationship(back_populates="creator")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    sent_messages: Mapped[list["Message"]] = relationship(back_populates="sender")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    creator: Mapped["User"] = relationship(back_populates="created_projects")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="project")
    messages: Mapped[list["Message"]] = relationship(back_populates="project")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            name="uq_memberships_user_project",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_memberships_valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="memberships")
    project: Mapped["Project"] = relationship(back_populates="memberships")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="sent_messages")
    
class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_experiment_runs_owner_idempotency",
        ),
        CheckConstraint(
            "authorization_mode IN ('connection-only', 'continuous')",
            name="ck_experiment_runs_authorization_mode",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_experiment_runs_status",
        ),
        CheckConstraint(
            "cutoff_seconds BETWEEN 1 AND 60",
            name="ck_experiment_runs_cutoff",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    authorization_mode: Mapped[str] = mapped_column(String(30))
    cutoff_seconds: Mapped[int] = mapped_column(default=5)
    status: Mapped[str] = mapped_column(
        String(20),
        default="queued",
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    result: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    owner: Mapped["User"] = relationship()
    project: Mapped["Project"] = relationship()
    events: Mapped[list["ExperimentEvent"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="ExperimentEvent.sequence",
    )


class ExperimentEvent(Base):
    __tablename__ = "experiment_events"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "sequence",
            name="uq_experiment_events_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_runs.id")
    )
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    experiment: Mapped["ExperimentRun"] = relationship(
        back_populates="events"
    )