from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

router = APIRouter(prefix="/auth", tags=["authentication"])
password_hasher = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    return password_hasher.hash(plain_password)


def verify_password(plain_password: str, stored_hash: str) -> bool:
    return password_hasher.verify(plain_password, stored_hash)


def require_user(
    request: Request,
    database: Session = Depends(get_db),
) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = database.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid",
        )

    return user


@router.post("/login")
def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    database: Session = Depends(get_db),
) -> dict[str, str]:
    user = database.scalar(
        select(User).where(User.username == username)
    )

    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    request.session.clear()
    request.session["user_id"] = user.id

    return {
        "message": "Login successful",
        "username": user.username,
        "role": user.role,
    }


@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"message": "Logout successful"}


@router.get("/me")
def current_account(
    user: User = Depends(require_user),
) -> dict[str, str | int]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
    }