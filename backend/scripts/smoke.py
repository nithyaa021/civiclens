"""End-to-end smoke test against a *running* CivicLens stack.

Prerequisites (all four processes must be up):
    1. MongoDB on mongodb://localhost:27017
    2. Redis  on redis://localhost:6379
    3. API    on http://127.0.0.1:8000   (uvicorn app.main:app)
    4. Worker (celery -A app.workers.celery_app worker)

Run with the backend virtualenv active:

    python scripts/smoke.py

Every step hits the real HTTP API; async jobs are executed by the real
worker through the Redis broker (this script never uses eager mode).
"""

from __future__ import annotations

import sys
import time
import uuid
from io import BytesIO
from typing import Any

import httpx
from PIL import Image

BASE_URL = "http://127.0.0.1:8000"
POLL_TIMEOUT_SECONDS = 30.0

PASS = "PASS"
FAIL = "FAIL"
_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    line = f"  [{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not ok:
        _failures.append(name)


def poll_job(client: httpx.AsyncClient, task_id: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/jobs/{task_id}", headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if body["state"] in {"SUCCESS", "FAILURE"}:
            return body
        time.sleep(0.5)
    raise TimeoutError(f"job {task_id} still not finished after {POLL_TIMEOUT_SECONDS}s")


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    citizen = {"email": f"smoke_{suffix}@example.com", "password": "SmokeTest!2026"}
    officer = {"email": f"smokeoff_{suffix}@example.com", "password": "SmokeTest!2026"}

    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        # --- Liveness / readiness ----------------------------------------
        print("\n== Health ==")
        r = client.get("/health")
        check("GET /health -> 200", r.status_code == 200, r.text[:120])

        r = client.get("/api/v1/health")
        deps = r.json().get("dependencies", {}) if r.status_code == 200 else {}
        check(
            "GET /api/v1/health -> mongo+redis ok",
            r.status_code == 200
            and deps.get("mongo", {}).get("status") == "ok"
            and deps.get("redis", {}).get("status") == "ok",
            f"status={r.status_code} mongo={deps.get('mongo', {}).get('status')} "
            f"redis={deps.get('redis', {}).get('status')}",
        )

        # --- Auth ---------------------------------------------------------
        print("\n== Auth ==")
        r = client.post(
            "/api/v1/auth/register",
            json={
                "email": citizen["email"],
                "full_name": "Smoke Citizen",
                "password": citizen["password"],
            },
        )
        check("register citizen -> 201", r.status_code == 201, f"{r.status_code} {r.text[:150]}")
        citizen_id = r.json().get("id", "")

        r = client.post(
            "/api/v1/auth/login",
            data={"username": citizen["email"], "password": citizen["password"]},
        )
        check("login -> 200 + tokens", r.status_code == 200 and "access_token" in r.json())
        tokens = r.json()
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}

        r = client.get("/api/v1/auth/me", headers=auth)
        check(
            "GET /auth/me -> own account",
            r.status_code == 200 and r.json()["user"]["email"] == citizen["email"],
        )

        r = client.get("/api/v1/auth/me")
        check(
            "GET /auth/me without token -> 401 + envelope",
            r.status_code == 401 and "error" in r.json(),
        )

        r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        check("refresh rotation -> 200", r.status_code == 200)
        r.json()
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        check(
            "replayed old refresh -> 401",
            r.status_code == 401 and r.json()["error"]["code"] == "refresh_revoked",
        )

        # --- RBAC ---------------------------------------------------------
        print("\n== RBAC ==")
        r = client.get("/api/v1/users", headers=auth)
        check(
            "citizen -> admin endpoint 403",
            r.status_code == 403 and r.json()["error"]["code"] == "forbidden",
        )

        # Bootstrap an admin through the service layer (mirrors seeding), then use HTTP.
        import asyncio

        from app.db.mongo import get_database
        from app.models.user import Role, UserCreate
        from app.services.users import create_user

        admin_pw = "SmokeAdmin!2026"
        admin_email = f"smokeadmin_{suffix}@example.com"

        async def _bootstrap() -> None:
            await create_user(
                get_database(),
                UserCreate(
                    email=admin_email,
                    full_name="Smoke Admin",
                    password=admin_pw,
                    role=Role.ADMIN,
                    ward=None,
                ),
            )

        asyncio.run(_bootstrap())

        r = client.post("/api/v1/auth/login", data={"username": admin_email, "password": admin_pw})
        admin_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.get("/api/v1/users", params={"search": citizen["email"]}, headers=admin_auth)
        check(
            "admin lists users (finds the citizen)",
            r.status_code == 200 and any(i["email"] == citizen["email"] for i in r.json()["items"]),
            f"status={r.status_code}",
        )

        r = client.post(
            "/api/v1/users",
            json={
                "email": officer["email"],
                "full_name": "Smoke Officer",
                "password": officer["password"],
                "role": "ward_officer",
                "ward": 7,
            },
            headers=admin_auth,
        )
        check(
            "admin provisions ward officer -> 201 (ward=7)",
            r.status_code == 201 and r.json().get("ward") == 7,
            f"{r.status_code} {r.text[:150]}",
        )

        # --- Async jobs (real worker) --------------------------------------
        print("\n== Async jobs (real Celery worker) ==")
        r = client.post(
            "/api/v1/jobs/embeddings",
            json={
                "text": "Overflowing drain near the Sarjapur water tank after last night's rain.",
                "kind": "complaint",
            },
            headers=auth,
        )
        check("queue embedding -> 202", r.status_code == 202, r.text[:150])
        if r.status_code == 202:
            job = poll_job(client, r.json()["task_id"], auth)
            check(
                "embedding job SUCCESS (norm=1.0)",
                job["state"] == "SUCCESS" and abs(job["result"]["norm"] - 1.0) < 1e-6,
                f"state={job['state']} result={job.get('result')}",
            )

        buf = BytesIO()
        Image.new("RGB", (96, 72), (18, 90, 160)).save(buf, format="PNG")
        r = client.post(
            "/api/v1/jobs/image-analysis",
            files={"file": ("street.png", buf.getvalue(), "image/png")},
            headers=auth,
        )
        check("queue image analysis -> 202", r.status_code == 202, r.text[:150])
        if r.status_code == 202:
            job = poll_job(client, r.json()["task_id"], auth)
            ok = (
                job["state"] == "SUCCESS"
                and job["result"]["width"] == 96
                and job["result"]["format"] == "PNG"
            )
            check(
                "image analysis job SUCCESS (96x72 PNG)",
                ok,
                f"state={job['state']} result={job.get('result')}",
            )

        r = client.post(
            "/api/v1/jobs/notifications",
            json={
                "user_id": citizen_id,
                "subject": "Complaint acknowledged",
                "body": "Ward 7 officer has been notified.",
                "channel": "in_app",
            },
            headers=admin_auth,
        )
        check("queue notification -> 202", r.status_code == 202, r.text[:150])
        if r.status_code == 202:
            # Ownership: the *admin* queued it, so only admin (or owner) may poll it.
            job = poll_job(client, r.json()["task_id"], admin_auth)
            check(
                "notification job SUCCESS (stored)",
                job["state"] == "SUCCESS",
                f"state={job['state']} result={job.get('result')}",
            )
            # But the *recipient* sees it in their notification list.
            r = client.get("/api/v1/jobs/notifications", headers=auth)
            found = any(i["subject"] == "Complaint acknowledged" for i in r.json()["items"])
            check("notification visible in recipient's list", found)

        # --- OpenAPI --------------------------------------------------------
        print("\n== OpenAPI ==")
        r = client.get("/openapi.json")
        spec = r.json()
        check(
            "openapi.json valid (title/paths/security)",
            r.status_code == 200
            and spec["info"]["title"] == "CivicLens AI"
            and "/api/v1/auth/login" in spec["paths"]
            and "OAuth2Password" in spec.get("components", {}).get("securitySchemes", {}),
        )
        check("/docs renders", client.get("/docs").status_code == 200)

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} check(s) FAILED: {_failures}")
        return 1
    print("RESULT: ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
