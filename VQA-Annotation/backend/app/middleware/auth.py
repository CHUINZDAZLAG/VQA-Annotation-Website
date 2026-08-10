from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.task import TaskAssignment, TaskType
from app.models.user import SystemRole, User
from app.services.auth_service import GoogleIdentityError, decode_application_token

DatabaseSession = Annotated[Session, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    database_session: DatabaseSession,
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    try:
        token_payload = decode_application_token(credentials.credentials, "access")
        user_id = int(token_payload["sub"])
    except (GoogleIdentityError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is invalid or expired.",
        ) from error

    user = database_session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive.",
        )
    return user


def require_system_role(role: SystemRole) -> Callable[[User], User]:
    def role_dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.system_role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return current_user

    return role_dependency


require_admin = require_system_role(SystemRole.ADMIN)
require_user = require_system_role(SystemRole.USER)


def require_task_assignment(task_type: TaskType) -> Callable[[int, User, Session], User]:
    def assignment_dependency(
        task_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        database_session: DatabaseSession,
    ) -> User:
        assignment = database_session.query(TaskAssignment).filter(
            TaskAssignment.task_id == task_id,
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.task_type == task_type,
            TaskAssignment.status == "ACTIVE",
        ).first()
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned this task type for this task.",
            )
        return current_user

    return assignment_dependency
