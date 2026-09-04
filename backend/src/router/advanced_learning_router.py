"""Goal-oriented advanced learning endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from backend.src.service.advanced.service import AdvancedLearningService
from backend.src.utils.jwt import get_user_id_from_token

router = APIRouter(prefix="/learning/advanced", tags=["进阶学习"])


@router.get("/current")
async def get_current_advanced_task(user_id: int = Depends(get_user_id_from_token)):
    """Aggregate onboarding, diagnosis, and path data into the current task."""
    try:
        result = await AdvancedLearningService.get_current(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "success", "data": result}
