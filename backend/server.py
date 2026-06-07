from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import logging
import os
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

import auth as A
from models import (
    CreateKeyRequest,
    LoginRequest,
    OptimizeTextRequest,
    RegisterRequest,
)
from optimizer import optimize
from parsers import parse_bytes, split_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("tokenforge")

MAX_BYTES = 50 * 1024 * 1024  # 50 MB

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="TokenForge - LLM Token Ingestion Optimizer")
app.state.db = db
api = APIRouter(prefix="/api")


def public_user(u: dict) -> dict:
    return {
        "id": str(u.get("_id", u.get("id"))),
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u.get("role", "user"),
        "active": u.get("active", True),
        "created_at": u.get("created_at", ""),
    }


# ============================ AUTH ============================
@api.post("/auth/register")
async def register(body: RegisterRequest, response: Response):
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "email": email,
        "password_hash": A.hash_password(body.password),
        "name": body.name.strip(),
        "role": "user",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.users.insert_one(doc)
    uid = str(res.inserted_id)
    access = A.create_access_token(uid, email)
    refresh = A.create_refresh_token(uid)
    A.set_auth_cookies(response, access, refresh)
    doc["_id"] = uid
    return public_user(doc)


@api.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not A.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")
    uid = str(user["_id"])
    access = A.create_access_token(uid, email)
    refresh = A.create_refresh_token(uid)
    A.set_auth_cookies(response, access, refresh)
    return public_user(user)


@api.post("/auth/logout")
async def logout(response: Response):
    A.clear_auth_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(A.get_current_user)):
    return public_user(user)


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    import jwt as _jwt

    try:
        payload = _jwt.decode(token, A.get_jwt_secret(), algorithms=[A.JWT_ALGORITHM])
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access = A.create_access_token(str(user["_id"]), user["email"])
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=3600, path="/")
    return {"ok": True}


# ============================ API KEYS ============================
@api.get("/keys")
async def list_keys(user: dict = Depends(A.get_current_user)):
    keys = await db.api_keys.find({"user_id": user["_id"]}).sort("created_at", -1).to_list(200)
    return [{
        "id": str(k["_id"]),
        "name": k["name"],
        "prefix": k["prefix"],
        "revoked": k.get("revoked", False),
        "usage_count": k.get("usage_count", 0),
        "last_used": k.get("last_used"),
        "created_at": k["created_at"],
    } for k in keys]


@api.post("/keys")
async def create_key(body: CreateKeyRequest, user: dict = Depends(A.get_current_user)):
    full, prefix, key_hash = A.generate_api_key()
    doc = {
        "user_id": user["_id"],
        "name": body.name.strip(),
        "prefix": prefix,
        "key_hash": key_hash,
        "revoked": False,
        "usage_count": 0,
        "last_used": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.api_keys.insert_one(doc)
    return {
        "id": str(res.inserted_id),
        "name": doc["name"],
        "prefix": prefix,
        "api_key": full,  # shown ONCE
        "created_at": doc["created_at"],
    }


@api.delete("/keys/{key_id}")
async def revoke_key(key_id: str, user: dict = Depends(A.get_current_user)):
    res = await db.api_keys.update_one(
        {"_id": ObjectId(key_id), "user_id": user["_id"]},
        {"$set": {"revoked": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"ok": True}


# ============================ JOBS ============================
async def _run_job(job_id: str, data: bytes, filename: str, threshold: float, min_length: int):
    loop = asyncio.get_event_loop()
    try:
        fragments = await loop.run_in_executor(None, parse_bytes, data, filename, min_length)
        if not fragments:
            await db.jobs.update_one({"_id": ObjectId(job_id)},
                {"$set": {"status": "failed", "error": "No readable text fragments found",
                          "completed_at": datetime.now(timezone.utc).isoformat()}})
            return
        result = await loop.run_in_executor(None, optimize, fragments, threshold)
        frags = result["fragments"]
        # store fragments in batches
        await db.fragments.delete_many({"job_id": job_id})
        batch = []
        for idx, f in enumerate(frags):
            batch.append({"job_id": job_id, "order": idx, **f})
            if len(batch) >= 1000:
                await db.fragments.insert_many(batch)
                batch = []
        if batch:
            await db.fragments.insert_many(batch)
        await db.jobs.update_one({"_id": ObjectId(job_id)},
            {"$set": {"status": "completed", "stats": result["stats"],
                      "completed_at": datetime.now(timezone.utc).isoformat()}})
    except Exception as e:  # pragma: no cover
        logger.exception("job failed")
        await db.jobs.update_one({"_id": ObjectId(job_id)},
            {"$set": {"status": "failed", "error": str(e),
                      "completed_at": datetime.now(timezone.utc).isoformat()}})


@api.post("/jobs")
async def create_job(
    file: UploadFile = File(...),
    threshold: float = 0.82,
    min_length: int = 3,
    user: dict = Depends(A.get_current_user),
):
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
    threshold = max(0.5, min(1.0, threshold))
    doc = {
        "user_id": user["_id"],
        "filename": file.filename,
        "size_bytes": len(data),
        "threshold": threshold,
        "status": "processing",
        "stats": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    res = await db.jobs.insert_one(doc)
    job_id = str(res.inserted_id)
    asyncio.create_task(_run_job(job_id, data, file.filename, threshold, min_length))
    return {"id": job_id, "status": "processing", "filename": file.filename}


def _job_out(j: dict) -> dict:
    return {
        "id": str(j["_id"]),
        "filename": j["filename"],
        "size_bytes": j.get("size_bytes", 0),
        "threshold": j.get("threshold"),
        "status": j["status"],
        "stats": j.get("stats"),
        "error": j.get("error"),
        "created_at": j["created_at"],
        "completed_at": j.get("completed_at"),
    }


@api.get("/jobs")
async def list_jobs(user: dict = Depends(A.get_current_user)):
    jobs = await db.jobs.find({"user_id": user["_id"]}).sort("created_at", -1).to_list(200)
    return [_job_out(j) for j in jobs]


@api.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(A.get_current_user)):
    j = await db.jobs.find_one({"_id": ObjectId(job_id), "user_id": user["_id"]})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_out(j)


@api.get("/jobs/{job_id}/fragments")
async def job_fragments(job_id: str, page: int = 1, page_size: int = 50,
                        search: str = "", user: dict = Depends(A.get_current_user)):
    j = await db.jobs.find_one({"_id": ObjectId(job_id), "user_id": user["_id"]})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    query = {"job_id": job_id}
    if search:
        query["text"] = {"$regex": search, "$options": "i"}
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    total = await db.fragments.count_documents(query)
    cursor = db.fragments.find(query, {"_id": 0}).sort("order", 1) \
        .skip((page - 1) * page_size).limit(page_size)
    items = await cursor.to_list(page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@api.get("/jobs/{job_id}/export")
async def export_job(job_id: str, user: dict = Depends(A.get_current_user)):
    j = await db.jobs.find_one({"_id": ObjectId(job_id), "user_id": user["_id"]})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    frags = await db.fragments.find({"job_id": job_id}, {"_id": 0, "job_id": 0}) \
        .sort("order", 1).to_list(length=None)
    payload = {
        "filename": j["filename"],
        "stats": j.get("stats"),
        "optimized_text": "\n".join(f["text"] for f in frags),
        "fragments": frags,
    }
    return JSONResponse(content=payload, headers={
        "Content-Disposition": f'attachment; filename="optimized_{job_id}.json"'})


@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user: dict = Depends(A.get_current_user)):
    res = await db.jobs.delete_one({"_id": ObjectId(job_id), "user_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.fragments.delete_many({"job_id": job_id})
    return {"ok": True}


# ============================ PUBLIC API (API KEY) ============================
@api.post("/v1/optimize")
async def v1_optimize(body: OptimizeTextRequest, user: dict = Depends(A.get_user_by_api_key)):
    fragments = split_text(body.text, body.min_length)
    if not fragments:
        raise HTTPException(status_code=400, detail="No text fragments to optimize")
    result = optimize(fragments, body.threshold)
    return result


# ============================ ADMIN ============================
@api.get("/admin/stats")
async def admin_stats(admin: dict = Depends(A.get_current_admin)):
    total_users = await db.users.count_documents({})
    active_users = await db.users.count_documents({"active": True})
    total_jobs = await db.jobs.count_documents({})
    total_keys = await db.api_keys.count_documents({"revoked": False})
    agg = await db.jobs.aggregate([
        {"$match": {"status": "completed"}},
        {"$group": {"_id": None,
                    "tokens_saved": {"$sum": "$stats.tokens_saved"},
                    "tokens_before": {"$sum": "$stats.tokens_before"}}},
    ]).to_list(1)
    saved = agg[0]["tokens_saved"] if agg else 0
    before = agg[0]["tokens_before"] if agg else 0
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_jobs": total_jobs,
        "active_keys": total_keys,
        "total_tokens_saved": saved,
        "total_tokens_processed": before,
    }


@api.get("/admin/users")
async def admin_users(admin: dict = Depends(A.get_current_admin)):
    users = await db.users.find({}).sort("created_at", -1).to_list(1000)
    out = []
    for u in users:
        uid = str(u["_id"])
        jobs = await db.jobs.count_documents({"user_id": uid})
        keys = await db.api_keys.count_documents({"user_id": uid, "revoked": False})
        item = public_user(u)
        item["job_count"] = jobs
        item["key_count"] = keys
        out.append(item)
    return out


@api.patch("/admin/users/{user_id}")
async def admin_toggle_user(user_id: str, request: Request,
                            admin: dict = Depends(A.get_current_admin)):
    body = await request.json()
    active = bool(body.get("active", True))
    if user_id == admin["_id"]:
        raise HTTPException(status_code=400, detail="Cannot modify your own account")
    res = await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"active": active}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "active": active}


@api.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: dict = Depends(A.get_current_admin)):
    if user_id == admin["_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete an admin account")
    await db.users.delete_one({"_id": ObjectId(user_id)})
    job_ids = [str(j["_id"]) async for j in db.jobs.find({"user_id": user_id}, {"_id": 1})]
    await db.jobs.delete_many({"user_id": user_id})
    await db.api_keys.delete_many({"user_id": user_id})
    if job_ids:
        await db.fragments.delete_many({"job_id": {"$in": job_ids}})
    return {"ok": True}


@api.get("/")
async def root():
    return {"service": "TokenForge", "status": "ok"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.api_keys.create_index("key_hash", unique=True)
    await db.api_keys.create_index("user_id")
    await db.jobs.create_index("user_id")
    await db.fragments.create_index("job_id")
    # seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": A.hash_password(admin_password),
            "name": "Owner",
            "role": "admin",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Seeded admin %s", admin_email)
    elif not A.verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one({"email": admin_email},
            {"$set": {"password_hash": A.hash_password(admin_password), "role": "admin", "active": True}})


@app.on_event("shutdown")
async def shutdown():
    client.close()
