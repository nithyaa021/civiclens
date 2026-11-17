"""Public demo sessions.

The console is a showcase, not a staff tool, so visitors should be able to open
it and choose a view without meeting a login form.  Rather than weakening
authentication (which would put citizen PII in front of anonymous callers), the
demo mints a normal short-lived session for one of the *seeded synthetic*
accounts.  Every role guard, ward scope and audit trail therefore keeps working
exactly as in production.

Only accounts on the reserved ``civiclens.dev`` demo domain are eligible, so a
real deployment can never expose a genuine user through this path.
"""

from __future__ import annotations

import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.errors import ApiError, NotFoundError
from app.models.token import DemoDirectory, DemoPerspective
from app.models.user import Role, UserStatus

# Demo accounts are seeded with addresses in this reserved, non-routable domain.
DEMO_EMAIL_DOMAIN = "@civiclens.dev"

# Only the accounts the seeder creates are eligible.  Matching the exact local
# part (instead of just the domain) means a visitor who registers some other
# `@civiclens.dev` address can never be promoted into a demo perspective.
_DEMO_LOCAL_PART = re.compile(r"^(admin|officer\d{1,3}|citizen\d{1,3})$")

_ALLOWED_PERSPECTIVE = re.compile(r"^(admin|citizen|ward-\d{1,3})$")

_DEFAULT_PERSPECTIVE = "admin"


def _is_demo_account(doc: dict[str, Any]) -> bool:
    """True only for seeded synthetic accounts on the demo domain."""
    email = str(doc.get("email", "")).strip().lower()
    if not email.endswith(DEMO_EMAIL_DOMAIN):
        return False
    return bool(_DEMO_LOCAL_PART.match(email[: -len(DEMO_EMAIL_DOMAIN)]))


def _perspective_id(doc: dict[str, Any]) -> str:
    role = Role(doc["role"])
    if role == Role.ADMIN:
        return "admin"
    if role == Role.WARD_OFFICER:
        return f"ward-{doc.get('ward')}"
    return "citizen"


def _describe(doc: dict[str, Any]) -> DemoPerspective:
    role = Role(doc["role"])
    ward = doc.get("ward")
    if role == Role.ADMIN:
        return DemoPerspective(
            id="admin",
            label="City-wide administrator",
            role=role,
            ward=None,
            description="Every ward, all analytics, bulk actions and assignment.",
        )
    if role == Role.WARD_OFFICER:
        return DemoPerspective(
            id=f"ward-{ward}",
            label=f"Ward {ward} officer",
            role=role,
            ward=ward,
            description=f"Scoped to ward {ward}: its queue, map and workload.",
        )
    return DemoPerspective(
        id="citizen",
        label="Citizen",
        role=role,
        ward=ward,
        description="Reporter view: own complaints and resolution confirmation.",
    )


async def _eligible_accounts(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """Seeded synthetic accounts, filtered with the strict local-part match."""
    cursor = db["users"].find(
        {
            "email": {"$regex": f"{DEMO_EMAIL_DOMAIN}$"},
            "status": UserStatus.ACTIVE.value,
        }
    )
    return [doc async for doc in cursor if _is_demo_account(doc)]


async def directory(db: AsyncIOMotorDatabase, *, enabled: bool) -> DemoDirectory:
    """List every perspective a visitor can open, ordered for the picker.

    Ward officers exist once per ward, so the picker also becomes a ward
    chooser; a handful are plenty for a demo and keep the response small.
    """
    if not enabled:
        return DemoDirectory(enabled=False)

    eligible = await _eligible_accounts(db)

    perspectives: list[DemoPerspective] = []
    admin = next((doc for doc in eligible if doc.get("role") == Role.ADMIN.value), None)
    if admin is not None:
        perspectives.append(_describe(admin))

    officers = sorted(
        (doc for doc in eligible if doc.get("role") == Role.WARD_OFFICER.value),
        key=lambda doc: doc.get("ward") or 0,
    )
    # One officer per ward is seeded; de-duplicate defensively.
    seen_wards: set[int] = set()
    for doc in officers:
        ward = doc.get("ward")
        if ward is None or ward in seen_wards:
            continue
        seen_wards.add(ward)
        perspectives.append(_describe(doc))

    citizen = next((doc for doc in eligible if doc.get("role") == Role.CITIZEN.value), None)
    if citizen is not None:
        perspectives.append(_describe(citizen))

    default = perspectives[0].id if perspectives else None
    if any(item.id == _DEFAULT_PERSPECTIVE for item in perspectives):
        default = _DEFAULT_PERSPECTIVE

    return DemoDirectory(enabled=True, default=default, perspectives=perspectives)


async def resolve(db: AsyncIOMotorDatabase, perspective: str) -> dict[str, Any]:
    """Return the seeded account document behind ``perspective``.

    Raises:
        NotFoundError: unknown perspective, or demo mode is off.
        ApiError: the requested perspective has no eligible seeded account.
    """
    requested = perspective.strip().lower()
    if not _ALLOWED_PERSPECTIVE.match(requested):
        raise NotFoundError("Demo perspective", perspective)

    for doc in await _eligible_accounts(db):
        if _perspective_id(doc) == requested:
            return doc

    raise NotFoundError("Demo perspective", perspective)


def assert_enabled(settings: Any) -> None:
    """Guard the demo endpoints when the flow is switched off."""
    if not settings.demo_mode:
        raise ApiError(
            404,
            "demo_disabled",
            "The public demo is not enabled on this deployment.",
        )
