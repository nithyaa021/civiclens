"""Hotspot forecasting endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUserDep, DbDep, SettingsDep
from app.models.complaint import ComplaintCategory, ForecastResponse
from app.services import forecasts as service

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.get(
    "",
    response_model=ForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="Forecast complaint volume for a ward and category",
    description=(
        "Predicts daily complaint counts for the next `horizon_days` (default 14) "
        "using the trained global XGBoost model over calendar + lag/rolling "
        "features. `holdout_mae` is the model's measured error on the held-out "
        "tail of history."
    ),
    responses={
        200: {"description": "Forecast points, newest history included."},
        401: {"description": "Not authenticated."},
        409: {"description": "Not enough history for this ward/category."},
        503: {"description": "Forecast model not trained yet."},
    },
)
async def get_forecast(
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
    ward: Annotated[int, Query(ge=1, le=999, description="Ward number.")],
    category: Annotated[ComplaintCategory, Query(description="Complaint category.")],
    horizon_days: Annotated[int | None, Query(ge=1, le=60)] = None,
) -> ForecastResponse:
    return await service.forecast(
        db,
        ward=ward,
        category=category,
        horizon_days=horizon_days or settings.forecast_horizon_days,
        settings=settings,
    )


@router.get(
    "/wards",
    response_model=list[ForecastResponse],
    status_code=status.HTTP_200_OK,
    summary="Forecast every category for one ward",
    description=(
        "Convenience endpoint for the ward dashboard: one forecast per category. "
        "Categories without enough history are returned as errors individually, so "
        "this endpoint skips them instead (the response only contains usable series)."
    ),
    responses={
        200: {"description": "Usable forecasts for the ward."},
        401: {"description": "Not authenticated."},
        503: {"description": "Forecast model not trained yet."},
    },
)
async def forecast_ward(
    user: CurrentUserDep,
    db: DbDep,
    settings: SettingsDep,
    ward: Annotated[int, Query(ge=1, le=999)],
    horizon_days: Annotated[int | None, Query(ge=1, le=60)] = None,
) -> list[ForecastResponse]:
    from app.core.errors import ApiError

    results: list[ForecastResponse] = []
    for category in ComplaintCategory:
        try:
            results.append(
                await service.forecast(
                    db,
                    ward=ward,
                    category=category,
                    horizon_days=horizon_days or settings.forecast_horizon_days,
                    settings=settings,
                )
            )
        except ApiError as error:
            if error.status_code in (409, 503):
                continue
            raise
    return results
