"""进阶学习巩固会话：持久化对话状态并评价最终提交。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from tortoise.exceptions import IntegrityError

from backend.src.models.advanced_practice_model import AdvancedPracticeSession
from backend.src.models.path_model import LearningPath, PathNode

PHASES = (
    ("understand", "理解问题"),
    ("evidence", "寻找证据"),
    ("hypothesis", "提出假设"),
    ("compare", "比较方案"),
    ("verify", "验证结果"),
    ("review", "总结"),
)
PHASE_IDS = {phase_id for phase_id, _ in PHASES}
PHASE_LABELS = dict(PHASES)
MAX_MESSAGES = 120
MAX_MESSAGE_LENGTH = 4000


def _clip_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    cleaned = []
    for item in messages[-MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        text = _clip_text(item.get("text"), MAX_MESSAGE_LENGTH)
        if role in {"user", "assistant"} and text:
            cleaned.append({"role": role, "text": text})
    return cleaned


def _clean_list(values: Any, limit: int = 20, item_limit: int = 240) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        text = _clip_text(value, item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _task_snapshot(task: Any) -> dict:
    if not isinstance(task, dict):
        return {}
    return {
        "id": _clip_text(task.get("id"), 128),
        "title": _clip_text(task.get("title"), 240),
        "problem": _clip_text(task.get("problem") or task.get("scenario"), 1200),
        "focus": _clip_text(task.get("focus"), 240),
        "criteria": _clean_list(task.get("criteria"), limit=8),
        "deliverables": _clean_list(
            [item.get("label") if isinstance(item, dict) else item for item in task.get("deliverables") or []],
            limit=8,
        ),
    }


def _welcome_message() -> dict[str, str]:
    return {
        "role": "assistant",
        "text": "我们从“理解问题”开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。",
    }


def _serialize(session: AdvancedPracticeSession) -> dict:
    return {
        "session_id": session.session_key,
        "task_id": session.task_key,
        "path_id": session.path_id,
        "node_id": session.node_id,
        "status": session.status,
        "current_phase": session.current_phase,
        "current_phase_label": PHASE_LABELS.get(session.current_phase, "理解问题"),
        "completed_phase_ids": session.completed_phases or [],
        "messages": session.messages or [],
        "confirmed_facts": session.confirmed_facts or [],
        "assumptions": session.assumptions or [],
        "final_submission": session.final_submission or "",
        "evaluation": session.evaluation,
        "resume_available": session.status in {"active", "paused"},
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


class AdvancedPracticeService:
    @staticmethod
    async def _validate_workspace(user_id: int, path_id: int, node_id: int) -> None:
        if not await LearningPath.filter(id=path_id, user_id=user_id).exists():
            raise ValueError("学习路径不存在或无权访问")
        if not await PathNode.filter(id=node_id, path_id=path_id).exists():
            raise ValueError("学习节点不存在或不属于当前路径")

    @staticmethod
    async def open_session(user_id: int, task_id: str, path_id: int, node_id: int, task: Any) -> dict:
        task_key = _clip_text(task_id, 128)
        if not task_key:
            raise ValueError("缺少进阶任务标识")
        await AdvancedPracticeService._validate_workspace(user_id, path_id, node_id)

        session = await AdvancedPracticeSession.filter(
            user_id=user_id,
            task_key=task_key,
            path_id=path_id,
            node_id=node_id,
        ).first()
        if not session:
            try:
                session = await AdvancedPracticeSession.create(
                    user_id=user_id,
                    session_key=uuid.uuid4().hex,
                    task_key=task_key,
                    path_id=path_id,
                    node_id=node_id,
                    task_snapshot=_task_snapshot(task),
                    status="active",
                    current_phase="understand",
                    completed_phases=[],
                    messages=[_welcome_message()],
                    confirmed_facts=[],
                    assumptions=[],
                )
            except IntegrityError:
                # 多窗口同时打开同一任务时，唯一约束由先完成创建的请求获胜。
                session = await AdvancedPracticeSession.filter(
                    user_id=user_id,
                    task_key=task_key,
                    path_id=path_id,
                    node_id=node_id,
                ).first()
                if not session:
                    raise

        if session.status == "paused":
            session.status = "active"
            session.ended_at = None
            await session.save(update_fields=["status", "ended_at", "updated_at"])
        return _serialize(session)

    @staticmethod
    async def get_session(user_id: int, session_key: str) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        return _serialize(session)

    @staticmethod
    async def save_state(
        user_id: int,
        session_key: str,
        *,
        current_phase: str,
        completed_phase_ids: Any,
        messages: Any,
        confirmed_facts: Any = None,
        assumptions: Any = None,
    ) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        if session.status == "completed":
            return _serialize(session)
        normalized_phase = current_phase if current_phase in PHASE_IDS else "understand"
        completed = [item for item in _clean_list(completed_phase_ids, limit=len(PHASES), item_limit=32) if item in PHASE_IDS]
        session.status = "active"
        session.current_phase = normalized_phase
        session.completed_phases = completed
        session.messages = _clean_messages(messages)
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.ended_at = None
        await session.save()
        return _serialize(session)

    @staticmethod
    async def pause_session(user_id: int, session_key: str) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        if session.status != "completed":
            session.status = "paused"
            session.ended_at = datetime.now()
            await session.save(update_fields=["status", "ended_at", "updated_at"])
        return _serialize(session)

    @staticmethod
    async def submit(
        user_id: int,
        session_key: str,
        *,
        final_submission: str,
        current_phase: str,
        completed_phase_ids: Any,
        messages: Any,
        confirmed_facts: Any = None,
        assumptions: Any = None,
    ) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        if session.status == "completed":
            return _serialize(session)

        normalized_messages = _clean_messages(messages)
        completed = [item for item in _clean_list(completed_phase_ids, limit=len(PHASES), item_limit=32) if item in PHASE_IDS]
        submission = _clip_text(final_submission, 6000)
        if not submission:
            submission = next((item["text"] for item in reversed(normalized_messages) if item["role"] == "user"), "")
        evaluation = AdvancedPracticeService._evaluate(
            session.task_snapshot or {},
            normalized_messages,
            completed,
            submission,
        )
        session.status = "completed"
        session.current_phase = current_phase if current_phase in PHASE_IDS else session.current_phase
        session.completed_phases = completed
        session.messages = normalized_messages
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.final_submission = submission
        session.evaluation = evaluation
        session.ended_at = datetime.now()
        await session.save()
        return _serialize(session)

    @staticmethod
    def _evaluate(task: dict, messages: list[dict[str, str]], completed: list[str], submission: str) -> dict:
        user_text = "\n".join(item["text"] for item in messages if item["role"] == "user")
        corpus = f"{user_text}\n{submission}"
        user_count = sum(1 for item in messages if item["role"] == "user")
        phase_score = round(len(set(completed)) / len(PHASES) * 40)
        evidence_score = 30 if re.search(r"依据|材料|数据|日志|证据|指标|文档", corpus) else 0
        validation_score = 20 if re.search(r"验证|测试|对比|复现|评估|回归", corpus) else 0
        decision_score = 10 if re.search(r"方案|选择|取舍|原因|风险|假设", corpus) else 0
        activity_score = 0 if user_count == 0 else min(10, user_count * 2)
        score = min(100, phase_score + evidence_score + validation_score + decision_score + activity_score)
        passed = bool(submission and user_count > 0 and score >= 60)

        strengths = []
        if evidence_score:
            strengths.append("已引用材料、数据或其他判断依据")
        if decision_score:
            strengths.append("已经说明方案选择或取舍")
        if validation_score:
            strengths.append("已经提出验证、测试或评估方式")
        if not strengths:
            strengths.append("已经开始把基础知识放入具体任务中")

        next_steps = []
        if len(completed) < len(PHASES):
            next_steps.append("补齐尚未完成的阶段，尤其是验证和复盘")
        if not evidence_score:
            next_steps.append("补充一条具体材料、数据或日志作为依据")
        if not validation_score:
            next_steps.append("写清楚如何测试结果，以及什么现象算有效")
        if not next_steps:
            next_steps.append("把本次方案整理成可复查的项目记录")

        criteria = [
            {"label": "问题理解", "passed": "understand" in completed},
            {"label": "证据与依据", "passed": bool(evidence_score)},
            {"label": "方案取舍", "passed": bool(decision_score)},
            {"label": "验证方法", "passed": bool(validation_score)},
        ]
        return {
            "score": score,
            "passed": passed,
            "label": "达到当前任务要求" if passed else "已提交，仍需补强",
            "strengths": strengths,
            "next_steps": next_steps,
            "criteria": criteria,
            "task_title": task.get("title") or "当前实践任务",
        }
