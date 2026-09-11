import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IdResponse(ORMModel):
    id: uuid.UUID


class Timestamped(ORMModel):
    created_at: datetime
    updated_at: datetime

