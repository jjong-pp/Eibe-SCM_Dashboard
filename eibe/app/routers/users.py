"""
사용자 계정 API — 관리자 전용.

구 버전은 `GET /api/users` 에 가드가 없어 **무인증으로 전 계정이 노출**됐다.
여기서는 라우터 기본 의존성으로 관리자를 요구하므로, 라우트마다 붙이는 것을
잊어도 뚫리지 않는다 (P-01).

비밀번호 해시는 어떤 응답에도 담기지 않는다 — `UserResponse` 에 필드 자체가 없다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.security import hash_password
from app.database import get_db
from app.models.auth import Role, User
from app.schemas.auth import UserCreate, UserResponse, UserUpdate
from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/users",
    tags=["사용자 관리"],
    dependencies=[Depends(require_admin)],
)


def _get_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다."
        )
    return user


def _remaining_admins(db: Session, excluding: int) -> int:
    """자기 자신을 뺀 활성 관리자 수."""
    return len(
        db.scalars(
            select(User.id).where(
                User.role == Role.ADMIN,
                User.is_active.is_(True),
                User.id != excluding,
            )
        ).all()
    )


@router.get("", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        name=payload.name,
        email=payload.email,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("사용자 생성: %s (%s)", user.username, user.role)
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    """계정 수정.

    **마지막 관리자의 권한을 내리거나 비활성화할 수 없다.** 아무도 들어갈 수
    없는 시스템이 되면 DB 를 직접 고치는 수밖에 없다.
    """
    user = _get_or_404(db, user_id)

    changes = payload.model_dump(exclude_unset=True)
    demoting = changes.get("role") not in (None, Role.ADMIN) and user.role == Role.ADMIN
    deactivating = changes.get("is_active") is False and user.is_active

    if (demoting or deactivating) and _remaining_admins(db, excluding=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="마지막 관리자입니다. 다른 관리자를 먼저 지정하세요.",
        )

    password = changes.pop("password", None)
    if password:
        user.password_hash = hash_password(password)

    for attribute, value in changes.items():
        setattr(user, attribute, value)

    db.commit()
    db.refresh(user)
    logger.info("사용자 수정: %s (by %s)", user.username, current_user.username)
    return user


@router.delete("/{user_id}", response_model=MessageResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> MessageResponse:
    """계정 비활성화.

    실제로 지우지 않는다. 감사 관점에서 '누가 등록했는가'를 남겨야 하고,
    같은 아이디가 재사용되면 과거 기록의 주체가 바뀌어 버린다.
    """
    user = _get_or_404(db, user_id)

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="자기 계정은 비활성화할 수 없습니다.",
        )
    if user.role == Role.ADMIN and _remaining_admins(db, excluding=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="마지막 관리자입니다. 다른 관리자를 먼저 지정하세요.",
        )

    user.is_active = False
    db.commit()
    logger.info("사용자 비활성화: %s (by %s)", user.username, current_user.username)
    return MessageResponse(message=f"{user.username} 계정을 비활성화했습니다.")
