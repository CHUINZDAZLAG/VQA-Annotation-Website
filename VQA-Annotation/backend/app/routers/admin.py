from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.config.database import get_db
from app.middleware.auth import require_admin
from app.models.user import SystemRole, User
from app.schemas.user import UserResponse, UserRoleUpdate, UserStatusUpdate

router = APIRouter(prefix="/api/admin", tags=["admin"])
AdminUser = Annotated[User, Depends(require_admin)]


@router.get("/users", response_model=list[UserResponse])
def list_users(_: AdminUser, database_session=Depends(get_db)) -> list[User]:
    return list(database_session.scalars(select(User).order_by(User.created_at.desc())))


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, _: AdminUser, database_session=Depends(get_db)) -> User:
    user = database_session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    _: AdminUser,
    database_session=Depends(get_db),
) -> User:
    user = database_session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.system_role = payload.system_role
    database_session.commit()
    database_session.refresh(user)
    return user


@router.patch("/users/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    _: AdminUser,
    database_session=Depends(get_db),
) -> User:
    user = database_session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = payload.is_active
    database_session.commit()
    database_session.refresh(user)
    return user
