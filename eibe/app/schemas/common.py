"""공통 응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """ORM 객체에서 직접 직렬화되는 응답 모델의 기반."""

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    env: str
