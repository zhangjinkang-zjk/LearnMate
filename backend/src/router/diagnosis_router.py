"""首次使用能力诊断接口。"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.src.service.diagnosis.service import answer as answer_diagnosis
from backend.src.service.diagnosis.service import start as start_diagnosis
from backend.src.utils.jwt import get_user_id_from_token

router = APIRouter(prefix="/learning/diagnosis", tags=["能力诊断"])


class StartDiagnosisRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=80)
    direction: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=160)
    max_steps: int = Field(default=3, ge=3, le=5)


class AnswerDiagnosisRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    question_id: int
    answer: str = Field(default="", max_length=2000)
    time_spent: Optional[int] = Field(default=None, ge=0)
    max_steps: int = Field(default=3, ge=3, le=5)


@router.post("/start")
async def start_diagnosis_endpoint(data: StartDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return {"code": 200, "msg": "success", "data": await start_diagnosis(user_id, data.identity, data.direction, data.goal, data.max_steps)}


@router.post("/answer")
async def answer_diagnosis_endpoint(data: AnswerDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return {"code": 200, "msg": "success", "data": await answer_diagnosis(user_id, data.session_id, data.question_id, data.answer, data.time_spent, data.max_steps)}
