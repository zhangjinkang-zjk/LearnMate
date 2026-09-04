"""首次使用能力诊断：逐题生成、判分并同步知识点掌握度。"""

import json
import logging
import uuid
from typing import Any

from backend.src.models.exam_model import ExamQuestion, ExamRecord
from backend.src.models.portraitmodel import User_picture
from backend.src.models.usermodel import User
from backend.src.service.exam.service import ExamService
from backend.src.service.portrait.service import dump_traits, parse_traits
from backend.src.utils.database import init_db
from backend.src.utils.json_parser import parse_llm_json
from backend.src.utils.prompt_loader import fill_prompt, load_prompt

logger = logging.getLogger(__name__)

_MIN_QUESTIONS = 3
_MAX_QUESTIONS = 5


def _goal_code(goal: str) -> str:
    text = str(goal or "")
    if any(word in text for word in ("考试", "课程", "成绩", "考研")):
        return "exam"
    if "竞赛" in text:
        return "competition"
    if any(word in text for word in ("证书", "认证")):
        return "certification"
    if any(word in text for word in ("就业", "岗位", "项目", "职业")):
        return "job"
    return "interest"


async def _save_onboarding_context(user_id: int, identity: str, direction: str, goal: str) -> None:
    user = await User.filter(id=user_id).first()
    if not user:
        raise ValueError("用户不存在")
    picture = await user.picture
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()

    traits = parse_traits(picture.traits)
    traits["onboarding"] = {
        "identity": identity[:80],
        "direction": direction[:120],
        "goal": goal[:160],
        "source": "user_stated",
    }
    # 保留后端既有枚举字段供画像/路径逻辑使用，原始中文目标放在 traits 中。
    picture.learning_goal = _goal_code(goal)
    picture.traits = dump_traits(traits)
    await picture.save()


def _safe_question(question: ExamQuestion) -> dict:
    try:
        options = json.loads(question.options) if question.options else []
    except (json.JSONDecodeError, TypeError):
        options = []
    try:
        tags = json.loads(question.knowledge_tags) if question.knowledge_tags else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "question_id": question.id,
        "question_type": question.question_type,
        "content": question.content,
        "options": options,
        "difficulty": question.difficulty,
        "knowledge_tags": tags,
    }


def _fallback_question(index: int, direction: str) -> dict:
    """LLM 不可用时仍保持诊断结构，但兜底题只覆盖已定义的核心考点。"""
    topic = direction or "当前学习方向"
    items = [
        {
            "content": f"学习“{topic}”时，第一步更应该做什么？",
            "options": ["A. 先明确问题和评价标准", "B. 先堆叠更多工具", "C. 先复制一份复杂案例", "D. 先追求最终界面效果"],
            "answer": "A",
            "analysis": "先明确问题与评价标准，才能判断后续方案是否有效；工具数量、案例复杂度和界面效果都不能替代问题定义。",
            "tags": ["问题定义", "评价标准"],
            "difficulty": "easy",
        },
        {
            "content": f"如果“{topic}”的第一次结果不理想，你更适合先检查什么？",
            "options": ["A. 结果是否符合目标和证据", "B. 立刻整体推倒重来", "C. 只更换最热门的工具", "D. 直接增加任务数量"],
            "answer": "A",
            "analysis": "先对照目标检查结果和证据，才能定位问题来源；盲目重做、换工具或加量都无法形成有效诊断。",
            "tags": ["结果评估", "问题排查"],
            "difficulty": "medium",
        },
        {
            "content": f"要把“{topic}”用于一个新场景，最能说明你已经掌握的是？",
            "options": ["A. 能解释取舍并用结果验证方案", "B. 能复述完整术语定义", "C. 能记住所有工具参数", "D. 能照着示例逐步操作"],
            "answer": "A",
            "analysis": "迁移能力体现在能结合新场景做出取舍，并用结果验证方案；复述、记参数或照做只能说明接触过。",
            "tags": ["迁移应用", "方案取舍"],
            "difficulty": "medium",
        },
    ]
    return items[min(index, len(items) - 1)]


async def _generate_question(user_id: int, identity: str, direction: str, goal: str, history: list[dict], index: int, max_steps: int) -> dict:
    history_lines = []
    for item in history:
        history_lines.append(f"第{item['index']}题：{item['content']}")
        history_lines.append(f"用户回答：{item['answer_text']}；判定：{'正确' if item['is_correct'] else '错误'}")
    fallback = _fallback_question(index, direction)
    try:
        from backend.src.ai_core.llm_config import llm

        prompt = fill_prompt(
            load_prompt("diagnosis"),
            identity=identity or "未填写",
            direction=direction or "未填写",
            goal=goal or "未填写",
            step=str(index + 1),
            max_steps=str(max_steps),
            history="\n".join(history_lines) or "暂无，这是第一题。",
        )
        response = await llm.ainvoke(prompt, priority="high", user_id=int(user_id), pool="diagnosis")
        result = parse_llm_json(response.content.strip())
        if isinstance(result, dict):
            options = result.get("options")
            answer = str(result.get("answer") or "").strip().upper()
            content = str(result.get("content") or "").strip()
            if content and isinstance(options, list) and len(options) == 4 and answer in {"A", "B", "C", "D"}:
                return {
                    "content": content[:300],
                    "options": [str(option)[:120] for option in options],
                    "answer": answer,
                    "analysis": str(result.get("analysis") or "").strip()[:500],
                    "tags": [str(tag)[:40] for tag in (result.get("knowledge_tags") or [])][:3],
                    "difficulty": str(result.get("difficulty") or "medium"),
                }
    except Exception:
        logger.warning("能力诊断出题失败，使用兜底题 user_id=%s index=%s", user_id, index, exc_info=True)
    return fallback


async def _create_question(user_id: int, session_id: str, payload: dict) -> ExamQuestion:
    question = await ExamQuestion.create(
        question_type="single_choice",
        content=payload["content"],
        options=json.dumps(payload["options"], ensure_ascii=False),
        answer=payload["answer"],
        analysis=payload.get("analysis") or "",
        difficulty=payload.get("difficulty") if payload.get("difficulty") in {"easy", "medium", "hard"} else "medium",
        knowledge_tags=json.dumps(payload.get("tags") or [], ensure_ascii=False),
        point_value=1.0,
        user_id=user_id,
    )
    await ExamRecord.create(question=question, user_id=user_id, session_id=session_id)
    return question


async def start(user_id: int, identity: str, direction: str, goal: str, max_steps: int = 3) -> dict:
    await init_db()
    identity, direction, goal = str(identity or "").strip(), str(direction or "").strip(), str(goal or "").strip()
    if not identity or not direction or not goal:
        raise ValueError("身份、学习方向和学习目标不能为空")
    max_steps = max(_MIN_QUESTIONS, min(int(max_steps or _MIN_QUESTIONS), _MAX_QUESTIONS))
    await _save_onboarding_context(user_id, identity, direction, goal)
    session_id = str(uuid.uuid4())[:12]
    payload = await _generate_question(user_id, identity, direction, goal, [], 0, max_steps)
    question = await _create_question(user_id, session_id, payload)
    return {"session_id": session_id, "current_index": 0, "total_questions": max_steps, "question": _safe_question(question)}


async def answer(user_id: int, session_id: str, question_id: int, answer_text: str, time_spent: int | None = None, max_steps: int = 3) -> dict:
    await init_db()
    record = await ExamRecord.filter(user_id=user_id, session_id=session_id, question_id=question_id).first()
    if not record:
        raise ValueError("诊断题目不存在或不属于当前会话")
    if record.is_correct is not None:
        raise ValueError("该题已经提交过")

    result = await ExamService.submit_answer(question_id, user_id, str(answer_text or ""), time_spent, session_id)
    records = await ExamRecord.filter(user_id=user_id, session_id=session_id).order_by("id").prefetch_related("question").all()
    answered = [item for item in records if item.is_correct is not None]
    max_steps = max(_MIN_QUESTIONS, min(int(max_steps or _MIN_QUESTIONS), _MAX_QUESTIONS))
    if len(answered) >= max_steps:
        summary = result.get("session_summary") or {}
        percentage = summary.get("percentage")
        return {"finished": True, "feedback": result, "result": {"session_id": session_id, "percentage": percentage, "correct_count": summary.get("correct_count", 0), "total_questions": len(records), "message": _result_message(percentage)}}

    user = await User.filter(id=user_id).first()
    picture = await user.picture if user else None
    traits = parse_traits(picture.traits if picture else None)
    onboarding = traits.get("onboarding") or {}
    history = []
    for index, item in enumerate(answered):
        history.append({"index": index + 1, "content": item.question.content, "answer_text": item.user_answer or "", "is_correct": bool(item.is_correct)})
    payload = await _generate_question(user_id, onboarding.get("identity", ""), onboarding.get("direction", ""), onboarding.get("goal", ""), history, len(answered), max_steps)
    question = await _create_question(user_id, session_id, payload)
    return {"finished": False, "feedback": result, "current_index": len(answered), "total_questions": max_steps, "question": _safe_question(question)}


def _result_message(percentage: float | None) -> str:
    score = float(percentage or 0)
    if score >= 85:
        return "基础概念和应用都较稳定，可以直接进入迁移练习。"
    if score >= 60:
        return "已经具备部分基础，建议先补齐关键方法，再进入项目练习。"
    return "目前处于起步阶段，建议先完成基础讲解，再用小任务建立理解。"
