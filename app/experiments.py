from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import ExperimentRun, User
from .projects import get_project_or_404, require_project_access

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    project_id: int = Field(gt=0)
    authorization_mode: Literal["connection-only", "continuous"]
    cutoff_seconds: int = Field(default=5, ge=1, le=60)


def same_request(
    experiment: ExperimentRun,
    payload: ExperimentCreate,
) -> bool:
    return (
        experiment.project_id == payload.project_id
        and experiment.authorization_mode == payload.authorization_mode
        and experiment.cutoff_seconds == payload.cutoff_seconds
    )


def serialize_experiment(experiment: ExperimentRun) -> dict:
    return {
        "id": experiment.id,
        "project_id": experiment.project_id,
        "authorization_mode": experiment.authorization_mode,
        "cutoff_seconds": experiment.cutoff_seconds,
        "status": experiment.status,
        "attempt_count": experiment.attempt_count,
        "max_attempts": experiment.max_attempts,
        "result": experiment.result,
        "error": (
            {
                "code": experiment.error_code,
                "detail": experiment.error_detail,
            }
            if experiment.error_code
            else None
        ),
        "created_at": experiment.created_at,
        "started_at": experiment.started_at,
        "completed_at": experiment.completed_at,
        "events": [
            {
                "sequence": event.sequence,
                "type": event.event_type,
                "detail": event.detail,
                "occurred_at": event.occurred_at,
            }
            for event in experiment.events
        ],
    }


@router.post("", status_code=202)
def create_experiment(
    payload: ExperimentCreate,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=100),
    ],
    user: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    get_project_or_404(payload.project_id, database)
    require_project_access(payload.project_id, user, database)

    existing = database.scalar(
        select(ExperimentRun).where(
            ExperimentRun.owner_id == user.id,
            ExperimentRun.idempotency_key == idempotency_key,
        )
    )

    if existing:
        if not same_request(existing, payload):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Idempotency-Key was already used with "
                    "a different request"
                ),
            )
        return serialize_experiment(existing)

    experiment = ExperimentRun(
        owner_id=user.id,
        project_id=payload.project_id,
        idempotency_key=idempotency_key,
        authorization_mode=payload.authorization_mode,
        cutoff_seconds=payload.cutoff_seconds,
        status="queued",
    )
    database.add(experiment)

    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        existing = database.scalar(
            select(ExperimentRun).where(
                ExperimentRun.owner_id == user.id,
                ExperimentRun.idempotency_key == idempotency_key,
            )
        )
        if existing and same_request(existing, payload):
            return serialize_experiment(existing)
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key conflicts with another request",
        )

    database.refresh(experiment)
    response.status_code = 202
    return serialize_experiment(experiment)


@router.get("/{experiment_id}")
def read_experiment(
    experiment_id: int,
    user: User = Depends(require_user),
    database: Session = Depends(get_db),
) -> dict:
    experiment = database.get(ExperimentRun, experiment_id)

    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=404, detail="Experiment not found")

    return serialize_experiment(experiment)