"""Pydantic models with MongoDB ObjectId support."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional, List

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field


def _coerce_objectid(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_coerce_objectid)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        return cls(**doc)

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=True)
        data.pop("_id", None)
        return data


# ---------- Auth payloads ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PublicUser(BaseModel):
    id: str
    email: str
    name: str
    role: str
    active: bool
    created_at: str


# ---------- API keys ----------
class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


# ---------- Optimize (programmatic) ----------
class OptimizeTextRequest(BaseModel):
    text: str = Field(min_length=1)
    threshold: float = Field(default=0.82, ge=0.5, le=1.0)
    min_length: int = Field(default=3, ge=1, le=200)
