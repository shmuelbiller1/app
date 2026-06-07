"""Authentication helpers: password hashing, JWT, API keys."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from fastapi import HTTPException, Request

JWT_ALGORITHM = "HS256"
API_KEY_PREFIX = "tio_"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key="access_token", value=access_token, httponly=True,
        secure=True, samesite="none", max_age=3600, path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True,
        secure=True, samesite="none", max_age=604800, path="/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


# ---------- API key utilities ----------
def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix_display, sha256_hash)."""
    raw = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}{raw}"
    key_hash = hashlib.sha256(full.encode("utf-8")).hexdigest()
    prefix_display = full[:12]
    return full, prefix_display, key_hash


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


# ---------- Dependencies ----------
def _extract_token(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


async def get_current_user(request: Request) -> dict:
    db = request.app.state.db
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    return user


async def get_current_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_user_by_api_key(request: Request) -> dict:
    """Authenticate a programmatic request via X-API-Key header."""
    db = request.app.state.db
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    key_hash = hash_api_key(api_key)
    key_doc = await db.api_keys.find_one({"key_hash": key_hash, "revoked": False})
    if not key_doc:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    user = await db.users.find_one({"_id": ObjectId(key_doc["user_id"])})
    if not user or not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account inactive")
    await db.api_keys.update_one(
        {"_id": key_doc["_id"]},
        {"$set": {"last_used": datetime.now(timezone.utc).isoformat()},
         "$inc": {"usage_count": 1}},
    )
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    return user
