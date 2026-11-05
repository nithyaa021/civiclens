"""Shared pytest fixtures.

Tests run against **real** MongoDB and Redis instances (the same services the
Docker Compose file provisions).  Configure them via env vars:

    MONGO_URI  (default mongodb://localhost:27017)
    REDIS_URL  (default redis://localhost:6379/15)  <- dedicated test DB 15

The test database is dropped before and after the session.  Note that
httpx's ASGITransport does not run lifespan events, so this module performs
the startup work (logging + index creation) explicitly.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# --- Environment must be configured before importing the app -----------------
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_DB", f"civiclens_test_{uuid.uuid4().hex[:8]}")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("RATE_LIMIT_AUTH_LIMIT", "1000")  # effectively disabled by default
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-for-production-0123456789")

# Phase-2 isolation: test-only model artifacts and Qdrant store, so tests never
# read or lock the developer's populated index.
TEST_QDRANT_PATH = Path(f"var/qdrant_test_{uuid.uuid4().hex[:8]}")
os.environ.setdefault("QDRANT_PATH", str(TEST_QDRANT_PATH))
os.environ.setdefault("MODELS_DIR", "var/test_models")
os.environ.setdefault("RESOLUTION_MODEL_PATH", "var/test_models/resolution_comparator.joblib")
os.environ.setdefault("FORECAST_MODEL_PATH", "var/test_models/forecast_xgb.joblib")
os.environ.setdefault("WHISPER_MODEL", "tiny")

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.indexes import ensure_indexes  # noqa: E402
from app.db.mongo import close_resources, get_database  # noqa: E402
from app.main import create_app  # noqa: E402

settings = get_settings()
assert settings.environment == "test", "tests must run with ENVIRONMENT=test"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database() -> None:
    """Prepare (and tear down) the test database + indexes."""
    configure_logging("WARNING", json_logs=False)
    db = get_database()
    await db.client.drop_database(db.name)
    await ensure_indexes(db)
    yield
    await db.client.drop_database(db.name)
    await close_resources()
    # Release the embedded Qdrant store and remove the test-only index.
    try:
        from app.ai import vector_store

        if vector_store._client is not None:  # noqa: SLF001 - test teardown
            vector_store._client.close()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass
    shutil.rmtree(TEST_QDRANT_PATH, ignore_errors=True)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _wards(_database: None) -> None:
    """Insert the corpus wards (polygons + sensitive sites) for geo lookups."""
    from app.data.corpus import generate_wards
    from app.db.mongo import get_database

    db = get_database()
    for ward in generate_wards():
        await db["wards"].replace_one(
            {"ward_no": ward.ward_no},
            {
                "ward_no": ward.ward_no,
                "name": ward.name,
                "zone": ward.zone,
                "geometry": ward.geometry,
                "sensitive_locations": ward.sensitive_locations,
            },
            upsert=True,
        )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _trained_models(_database: None) -> None:
    """Ensure test-only model artifacts exist (trained on the corpus if missing)."""
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    from app.ai import classifier, forecast, resolution
    from app.data.corpus import (
        ComplaintCategory,
        generate_resolution_pairs,
        split_text_samples,
    )

    classifier_path = classifier.classifier_path()
    if not classifier_path.exists():
        train_samples, _ = split_text_samples()
        pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True
                    ),
                ),
                ("clf", LogisticRegression(max_iter=2000, C=4.0, random_state=42)),
            ]
        )
        pipeline.fit(
            [sample.text for sample in train_samples],
            [sample.category.value for sample in train_samples],
        )
        classifier_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "pipeline": pipeline,
                "labels": sorted(pipeline.classes_.tolist()),
                "version": "test-classifier-v1",
            },
            classifier_path,
        )

    forecast_path = Path(settings.forecast_model_path)
    if not forecast_path.exists():
        import random
        from datetime import date, timedelta

        rng = random.Random(11)
        start = date(2026, 1, 1)
        series = {}
        for ward_no in (1, 2):
            for category in (ComplaintCategory.ROADS, ComplaintCategory.DRAINAGE):
                series[(ward_no, category.value)] = {
                    start + timedelta(days=offset): rng.randint(0, 5) for offset in range(120)
                }
        artifact = forecast.train(series, holdout_days=14)
        forecast.save_artifact(artifact, forecast_path)

    resolution_path = Path(settings.resolution_model_path)
    if not resolution_path.exists():
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline as SkPipeline
        from sklearn.preprocessing import StandardScaler

        pairs = generate_resolution_pairs(count=24, seed=21)
        features = []
        labels = []
        for before, after, label, _pair_id in pairs:
            extracted = resolution.extract_features(before, after)
            features.append([extracted[name] for name in resolution.FEATURE_NAMES])
            labels.append(label)
        model = SkPipeline(
            [
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(max_iter=1000, random_state=42)),
            ]
        )
        model.fit(np.asarray(features), np.asarray(labels))
        resolution_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": model,
                "feature_names": resolution.FEATURE_NAMES,
                "version": "test-comparator-v1",
            },
            resolution_path,
        )
    classifier.reset_cache()
    forecast.reset_cache()
    resolution.reset_cache()


# --- Phase-2 account fixtures --------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def db():  # noqa: ANN201
    """Application database handle for direct fixture setup/assertions."""
    from app.db.mongo import get_database

    return get_database()


@pytest_asyncio.fixture(scope="session")
async def officer(client: AsyncClient) -> dict:  # noqa: ANN201
    """An active ward officer for ward 1."""
    from app.db.mongo import get_database
    from app.models.user import Role, UserCreate
    from app.services.users import create_user

    email = f"officer_{uuid.uuid4().hex[:8]}@example.com"
    password = "OfficerPass!2026"
    user = await create_user(
        get_database(),
        UserCreate(
            email=email,
            full_name="Ward One Officer",
            password=password,
            role=Role.WARD_OFFICER,
            ward=1,
        ),
    )
    return {"email": email, "password": password, "id": user.id, "ward": 1}


@pytest_asyncio.fixture(scope="session")
async def officer_ward2(client: AsyncClient) -> dict:  # noqa: ANN201
    """An active ward officer for ward 2 (for cross-ward permission tests)."""
    from app.db.mongo import get_database
    from app.models.user import Role, UserCreate
    from app.services.users import create_user

    email = f"officer2_{uuid.uuid4().hex[:8]}@example.com"
    password = "OfficerTwoPass!2026"
    user = await create_user(
        get_database(),
        UserCreate(
            email=email,
            full_name="Ward Two Officer",
            password=password,
            role=Role.WARD_OFFICER,
            ward=2,
        ),
    )
    return {"email": email, "password": password, "id": user.id, "ward": 2}


@pytest_asyncio.fixture(scope="session")
async def officer_headers(client: AsyncClient, officer: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": officer["email"], "password": officer["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="session")
async def citizen2(client: AsyncClient) -> dict:  # noqa: ANN201
    email = f"citizen2_{uuid.uuid4().hex[:8]}@example.com"
    password = "CitizenTwo!2026"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Second Citizen", "password": password},
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "password": password, "id": resp.json()["id"]}


@pytest_asyncio.fixture(scope="session")
async def citizen2_headers(client: AsyncClient, citizen2: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": citizen2["email"], "password": citizen2["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}



@pytest_asyncio.fixture(scope="session")
async def app():  # noqa: ANN201 - fixture type
    return create_app()


@pytest_asyncio.fixture(scope="session")
async def client(app) -> AsyncClient:  # noqa: ANN001, ANN201
    """HTTP client wired to the ASGI app (no network socket needed)."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# --- Account fixtures ---------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def citizen(client: AsyncClient) -> dict:  # noqa: ANN201
    """A registered citizen account with credentials."""
    email = f"citizen_{uuid.uuid4().hex[:8]}@example.com"
    password = "CitizenPass!2026"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Test Citizen", "password": password},
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "password": password, "id": resp.json()["id"]}


@pytest_asyncio.fixture(scope="session")
async def citizen_headers(client: AsyncClient, citizen: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": citizen["email"], "password": citizen["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="session")
async def admin(client: AsyncClient) -> dict:  # noqa: ANN201
    """Admin account created through the service layer (bootstrap)."""
    from app.db.mongo import get_database
    from app.models.user import Role, UserCreate
    from app.services.users import create_user

    email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
    password = "AdminPass!2026"
    payload = UserCreate(
        email=email, full_name="Test Admin", password=password, role=Role.ADMIN, ward=None
    )
    user = await create_user(get_database(), payload)
    return {"email": email, "password": password, "id": user.id}


@pytest_asyncio.fixture(scope="session")
async def admin_headers(client: AsyncClient, admin: dict) -> dict[str, str]:  # noqa: ANN201
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin["email"], "password": admin["password"]},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
