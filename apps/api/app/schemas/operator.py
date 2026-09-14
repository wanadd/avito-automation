import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import OperatorRole


class OperatorLoginRequest(BaseModel):
    username: str
    password: str


class OperatorUserRead(BaseModel):
    id: uuid.UUID
    username: str
    role: OperatorRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class OperatorSessionRead(BaseModel):
    user: OperatorUserRead
    csrf_token: str
    expires_at: datetime


class OperatorCreateRequest(BaseModel):
    username: str
    password: str
    role: OperatorRole = OperatorRole.OPERATOR


class OperatorListItem(BaseModel):
    id: uuid.UUID
    username: str
    role: OperatorRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
