"""Grounded natural-language assistant over complaint data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.ai.assistant import Assistant
from app.core.deps import CurrentUserDep, DbDep, SettingsDep, default_rate_limit
from app.models.complaint import AssistantQuery, AssistantResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])

EXAMPLES = [
    "Top recurring issues in Ward 12 this month",
    "Status of my pothole report",
    "Show my open complaints",
    "Which complaints are overdue in Ward 5?",
    "How many garbage complaints in Ward 7 this week?",
]


@router.post(
    "/query",
    response_model=AssistantResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question about complaint data",
    description=(
        "Retrieval-augmented answers over live complaint records. The question is "
        "matched to an intent (recurring issues, status, my reports, overdue SLAs, "
        "category counts), slots are parsed (ward, category, period), and the answer "
        "is rendered from real MongoDB rows with cited complaint ids. Citizen "
        "citations are restricted to their own reports, ward officers to their ward, "
        "admins to everything."
    ),
    responses={
        200: {"description": "Grounded answer with citations."},
        401: {"description": "Not authenticated."},
        422: {"description": "Validation error."},
        429: {"description": "Rate limit exceeded."},
    },
    dependencies=[Depends(default_rate_limit)],
)
async def query(
    payload: AssistantQuery,
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
) -> AssistantResponse:
    return await Assistant(db, user, settings).answer(payload.question)


@router.get(
    "/examples",
    response_model=list[str],
    status_code=status.HTTP_200_OK,
    summary="Sample assistant questions",
    description="Suggested prompts; every one is supported by the intent retriever.",
    responses={
        200: {"description": "Example questions."},
        401: {"description": "Not authenticated."},
    },
)
async def examples(user: CurrentUserDep) -> list[str]:
    return EXAMPLES
