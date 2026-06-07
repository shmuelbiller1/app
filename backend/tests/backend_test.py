"""TokenForge backend integration tests.

Covers:
  - auth register/login/me/logout, deactivation 403
  - api keys create/list/revoke
  - jobs upload/polling/fragments/export/delete
  - public /v1/optimize with API key (and 401 cases)
  - admin stats/users/toggle/delete (and ownership/admin rules)
  - dedup correctness assertions
"""
from __future__ import annotations

import io
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@tokenforge.io"
ADMIN_PASSWORD = "Admin@12345"

# unique user per run so re-runs don't collide
RUN = uuid.uuid4().hex[:8]
USER_EMAIL = f"tester_{RUN}@test.com"
USER_PASSWORD = "Test@12345"
USER_NAME = f"Tester {RUN}"

SECONDARY_EMAIL = f"victim_{RUN}@test.com"
SECONDARY_PASSWORD = "Victim@12345"


def _client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_client():
    s = _client()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    assert body["role"] == "admin"
    return s


@pytest.fixture(scope="session")
def user_client():
    s = _client()
    r = s.post(f"{API}/auth/register",
               json={"email": USER_EMAIL, "password": USER_PASSWORD, "name": USER_NAME})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    body = r.json()
    assert body["email"] == USER_EMAIL
    assert body["role"] == "user"
    return s


# ============ AUTH ============
class TestAuth:
    def test_me_returns_current_user(self, user_client):
        r = user_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == USER_EMAIL

    def test_login_wrong_password(self):
        r = _client().post(f"{API}/auth/login",
                           json={"email": USER_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_protected_endpoint_without_auth(self):
        r = _client().get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_logout_clears_session(self):
        s = _client()
        r = s.post(f"{API}/auth/login",
                   json={"email": USER_EMAIL, "password": USER_PASSWORD})
        assert r.status_code == 200
        assert s.get(f"{API}/auth/me").status_code == 200
        r = s.post(f"{API}/auth/logout")
        assert r.status_code == 200
        # cookies cleared
        assert s.get(f"{API}/auth/me").status_code == 401


# ============ API KEYS ============
class TestKeys:
    def test_create_list_and_use_key(self, user_client):
        r = user_client.post(f"{API}/keys", json={"name": "TEST_key_primary"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["api_key"].startswith("tio_")
        assert body["prefix"].startswith("tio_")
        TestKeys.full_key = body["api_key"]
        TestKeys.key_id = body["id"]

        # list
        r = user_client.get(f"{API}/keys")
        assert r.status_code == 200
        ids = [k["id"] for k in r.json()]
        assert TestKeys.key_id in ids

    def test_v1_optimize_with_key(self):
        text = "\n".join([
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox jumps over the lazy dog.",  # exact dup
            "The quick brown fox jumps over the lazy dog!",  # near dup (punct)
            "Completely unrelated sentence about pineapples.",
            "Hello world.",
            "hello world",  # near dup
        ])
        r = requests.post(f"{API}/v1/optimize",
                          headers={"X-API-Key": TestKeys.full_key,
                                   "Content-Type": "application/json"},
                          json={"text": text, "threshold": 0.7})
        assert r.status_code == 200, r.text
        body = r.json()
        st = body["stats"]
        assert st["fragments_in"] == 6
        assert st["unique_concepts"] <= 3
        assert st["tokens_after"] < st["tokens_before"]
        assert st["tokens_saved"] > 0
        # no data loss: variants preserved on canonical entries
        assert any(f.get("variant_count", 0) >= 1 for f in body["fragments"])

    def test_v1_optimize_missing_key(self):
        r = requests.post(f"{API}/v1/optimize", json={"text": "hi there friend"})
        assert r.status_code == 401

    def test_v1_optimize_bad_key(self):
        r = requests.post(f"{API}/v1/optimize",
                          headers={"X-API-Key": "tio_nope"},
                          json={"text": "hi there friend"})
        assert r.status_code == 401

    def test_revoke_key(self, user_client):
        r = user_client.delete(f"{API}/keys/{TestKeys.key_id}")
        assert r.status_code == 200
        # now invalid
        r = requests.post(f"{API}/v1/optimize",
                          headers={"X-API-Key": TestKeys.full_key},
                          json={"text": "hi there friend"})
        assert r.status_code == 401


# ============ JOBS ============
class TestJobs:
    SAMPLE = (
        "\n".join([
            "Pricing is $9.99 per month.",
            "Pricing is $9.99 per month.",
            "Pricing is $9.99 per month!",
            "Refunds are issued within 7 days.",
            "Refunds are issued within seven days.",
            "Refunds are issued within 7 days.",
            "Our office is in San Francisco.",
            "Our office is in San Francisco, California.",
            "Contact support at help@example.com.",
            "Contact support at help@example.com.",
        ] * 10)
    )

    def test_upload_and_complete(self, user_client):
        files = {"file": ("sample.txt", io.BytesIO(self.SAMPLE.encode()), "text/plain")}
        # remove session Content-Type so requests sets multipart boundary
        user_client.headers.pop("Content-Type", None)
        r = user_client.post(f"{API}/jobs", files=files,
                             data={"threshold": "0.7", "min_length": "3"})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["status"] == "processing"
        job_id = job["id"]
        TestJobs.job_id = job_id

        # poll
        status = "processing"
        for _ in range(40):
            time.sleep(1)
            r = user_client.get(f"{API}/jobs/{job_id}")
            assert r.status_code == 200
            status = r.json()["status"]
            if status in ("completed", "failed"):
                break
        assert status == "completed", f"job did not complete: {r.json()}"

        stats = r.json()["stats"]
        assert stats["tokens_after"] < stats["tokens_before"]
        assert stats["unique_concepts"] < stats["fragments_in"]
        assert stats["duplicates_removed"] > 0

    def test_list_jobs(self, user_client):
        r = user_client.get(f"{API}/jobs")
        assert r.status_code == 200
        assert any(j["id"] == TestJobs.job_id for j in r.json())

    def test_fragments_paginated(self, user_client):
        r = user_client.get(f"{API}/jobs/{TestJobs.job_id}/fragments",
                            params={"page": 1, "page_size": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["items"]) <= 10
        assert body["total"] >= 1
        # search
        r = user_client.get(f"{API}/jobs/{TestJobs.job_id}/fragments",
                            params={"search": "refund"})
        assert r.status_code == 200

    def test_export(self, user_client):
        r = user_client.get(f"{API}/jobs/{TestJobs.job_id}/export")
        assert r.status_code == 200
        payload = r.json()
        assert "stats" in payload
        assert "optimized_text" in payload
        assert "fragments" in payload

    def test_empty_file_rejected(self, user_client):
        files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        user_client.headers.pop("Content-Type", None)
        r = user_client.post(f"{API}/jobs", files=files)
        assert r.status_code == 400


# ============ ADMIN ============
class TestAdmin:
    def test_admin_stats(self, admin_client):
        r = admin_client.get(f"{API}/admin/stats")
        assert r.status_code == 200
        body = r.json()
        for k in ("total_users", "active_users", "total_jobs",
                  "active_keys", "total_tokens_saved", "total_tokens_processed"):
            assert k in body

    def test_admin_list_users_no_objectid(self, admin_client):
        r = admin_client.get(f"{API}/admin/users")
        assert r.status_code == 200
        users = r.json()
        assert any(u["email"] == USER_EMAIL for u in users)
        for u in users:
            assert "_id" not in u  # no Mongo ObjectId leak

    def test_non_admin_blocked(self, user_client):
        for path in ("/admin/stats", "/admin/users"):
            r = user_client.get(f"{API}{path}")
            assert r.status_code == 403

    def test_deactivate_reactivate_user(self, admin_client):
        # create secondary user
        s = _client()
        r = s.post(f"{API}/auth/register",
                   json={"email": SECONDARY_EMAIL, "password": SECONDARY_PASSWORD,
                         "name": "Victim"})
        assert r.status_code == 200
        secondary_id = r.json()["id"]
        TestAdmin.secondary_id = secondary_id

        # deactivate
        r = admin_client.patch(f"{API}/admin/users/{secondary_id}", json={"active": False})
        assert r.status_code == 200
        assert r.json()["active"] is False

        # deactivated user cannot login
        r = _client().post(f"{API}/auth/login",
                           json={"email": SECONDARY_EMAIL, "password": SECONDARY_PASSWORD})
        assert r.status_code == 403

        # reactivate
        r = admin_client.patch(f"{API}/admin/users/{secondary_id}", json={"active": True})
        assert r.status_code == 200
        assert r.json()["active"] is True

    def test_admin_cannot_modify_self(self, admin_client):
        me = admin_client.get(f"{API}/auth/me").json()
        r = admin_client.patch(f"{API}/admin/users/{me['id']}", json={"active": False})
        assert r.status_code == 400

        r = admin_client.delete(f"{API}/admin/users/{me['id']}")
        assert r.status_code == 400

    def test_admin_delete_user(self, admin_client):
        r = admin_client.delete(f"{API}/admin/users/{TestAdmin.secondary_id}")
        assert r.status_code == 200
        # ensure user gone
        r = _client().post(f"{API}/auth/login",
                           json={"email": SECONDARY_EMAIL, "password": SECONDARY_PASSWORD})
        assert r.status_code == 401
