from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/api/user", tags=["user"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/profile", response_model=UserResponse)
def get_profile(current_user: CurrentUser) -> User:
    return current_user


@router.get("/me", response_model=UserResponse)
def get_account(current_user: CurrentUser) -> User:
    return current_user
