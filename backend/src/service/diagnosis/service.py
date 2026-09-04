"""首次使用能力诊断：逐题生成、判分并同步知识点掌握度。"""

import json
import logging
import re
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
        "options": options if question.question_type in {"single_choice", "multi_choice", "true_false"} else [],
        "difficulty": question.difficulty,
        "knowledge_tags": tags,
    }


def _fallback_question(index: int, direction: str) -> dict:
    """LLM 不可用时仍保持开放式访谈结构。"""
    topic = direction or "当前学习方向"
    items = [
        {
            "content": f"用自己的话说说，在学习“{topic}”时，你认为最核心的概念或方法是什么？它解决什么问题？",
            "reference_answer": "能够说清核心概念的定义、要解决的问题，以及它与学习方向的关系。",
            "evaluation_points": ["概念定义", "解决的问题"],
            "analysis": "先确认你是否理解概念和它要解决的问题，再进入具体应用。",
            "tags": ["核心概念", "问题定义"],
            "difficulty": "easy",
        },
        {
            "content": f"假设你第一次把“{topic}”用于一个真实任务，结果没有达到目标，你会先检查什么？请说说你的判断顺序。",
            "reference_answer": "先对照目标和评价标准确认问题，再检查输入、关键步骤和输出证据，最后决定是否调整方案。",
            "evaluation_points": ["目标与标准", "输入和步骤", "证据验证"],
            "analysis": "应用能力不只看会不会操作，还要看能否按证据定位问题。",
            "tags": ["结果评估", "问题排查"],
            "difficulty": "medium",
        },
        {
            "content": f"如果要把“{topic}”迁移到一个你没见过的新场景，你会怎样做取舍并验证方案有效？",
            "reference_answer": "先分析新场景约束和目标，说明方案取舍，再用可观察的指标或对照结果验证效果并迭代。",
            "evaluation_points": ["场景约束", "方案取舍", "指标验证"],
            "analysis": "迁移能力体现在面对新约束时能解释取舍，并用结果验证，而不是复述示例。",
            "tags": ["迁移应用", "方案取舍", "效果验证"],
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
            content = str(result.get("content") or "").strip()
            reference_answer = str(result.get("reference_answer") or result.get("answer") or "").strip()
            evaluation_points = [str(point).strip()[:80] for point in (result.get("evaluation_points") or []) if str(point).strip()][:3]
            if content and reference_answer:
                return {
                    "content": content[:300],
                    "reference_answer": reference_answer[:600],
                    "evaluation_points": evaluation_points,
                    "analysis": str(result.get("analysis") or "").strip()[:500],
                    "tags": [str(tag)[:40] for tag in (result.get("knowledge_tags") or [])][:3],
                    "difficulty": str(result.get("difficulty") or "medium"),
                }
    except Exception:
        logger.warning("能力诊断出题失败，使用兜底题 user_id=%s index=%s", user_id, index, exc_info=True)
    return fallback


async def _create_question(user_id: int, session_id: str, payload: dict) -> ExamQuestion:
    evaluation_context = {
        "feedback_basis": payload.get("analysis") or "",
        "evaluation_points": payload.get("evaluation_points") or [],
    }
    question = await ExamQuestion.create(
        question_type="short_answer",
        content=payload["content"],
        options=None,
        answer=payload["reference_answer"],
        analysis=json.dumps(evaluation_context, ensure_ascii=False),
        difficulty=payload.get("difficulty") if payload.get("difficulty") in {"easy", "medium", "hard"} else "medium",
        knowledge_tags=json.dumps(payload.get("tags") or [], ensure_ascii=False),
        point_value=1.0,
        user_id=user_id,
    )
    await ExamRecord.create(question=question, user_id=user_id, session_id=session_id)
    return question


def _evaluation_context(question: ExamQuestion) -> tuple[str, list[str]]:
    try:
        context = json.loads(question.analysis or "{}")
    except (json.JSONDecodeError, TypeError):
        context = {}
    points = [str(point).strip() for point in (context.get("evaluation_points") or []) if str(point).strip()]
    return str(context.get("feedback_basis") or "").strip(), points


def _fallback_evaluation(question: ExamQuestion, answer_text: str) -> dict:
    """LLM 评估不可用时，用参考答案和评估要点做保守的关键词覆盖判断。"""
    answer = str(answer_text or "").strip()
    reference = str(question.answer or "").strip()
    _, points = _evaluation_context(question)
    if not answer:
        return {"is_correct": False, "score": 0.0, "feedback": "还没有收到你的回答，请先说说你的理解。"}
    source = " ".join([reference, *points])
    tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{1,}", source.casefold()))
    matched = {token for token in tokens if token in answer.casefold()}
    coverage = len(matched) / max(len(tokens), 1)
    is_correct = answer.casefold() == reference.casefold() or (len(answer) >= 8 and coverage >= 0.35)
    feedback = "你的回答覆盖了关键判断，我继续从应用和迁移角度确认。" if is_correct else "你的回答里已经有部分线索，但还缺少关键依据；我会据此调整后续问题。"
    return {"is_correct": is_correct, "score": 1.0 if is_correct else 0.0, "feedback": feedback}


async def _evaluate_answer(user_id: int, question: ExamQuestion, answer_text: str) -> dict:
    answer = str(answer_text or "").strip()[:2000]
    feedback_basis, points = _evaluation_context(question)
    try:
        from backend.src.ai_core.llm_config import llm

        prompt = fill_prompt(
            load_prompt("diagnosis_evaluate"),
            question=question.content[:500],
            reference_answer=str(question.answer or "")[:600],
            evaluation_points="；".join(points)[:300] or "关注回答是否给出概念、依据或验证方式",
            answer=answer,
        )
        response = await llm.ainvoke(prompt, priority="high", user_id=int(user_id), pool="diagnosis")
        result = parse_llm_json(response.content.strip())
        if isinstance(result, dict) and isinstance(result.get("is_correct"), bool):
            return {
                "is_correct": result["is_correct"],
                "score": 1.0 if result["is_correct"] else 0.0,
                "feedback": str(result.get("feedback") or feedback_basis or "已记录你的回答。")[:500],
            }
    except Exception:
        logger.warning("开放回答评估失败，使用关键词兜底 user_id=%s question_id=%s", user_id, question.id, exc_info=True)
    return _fallback_evaluation(question, answer)


async def _submit_open_answer(user_id: int, record: ExamRecord, answer_text: str, time_spent: int | None, session_id: str) -> dict:
    question = await record.question
    evaluation = await _evaluate_answer(user_id, question, answer_text)
    # 复用 ExamService 的掌握度、画像和会话汇总逻辑；题目答案是服务端参考答案，实际回答随后写回记录。
    probe_answer = str(question.answer or "") if evaluation["is_correct"] else "__learnmate_incorrect_answer__"
    result = await ExamService.submit_answer(question.id, user_id, probe_answer, time_spent, session_id)
    saved_record = await ExamRecord.filter(user_id=user_id, session_id=session_id, question_id=question.id).order_by("-id").first()
    if saved_record:
        saved_record.user_answer = str(answer_text or "").strip()[:2000]
        saved_record.is_correct = evaluation["is_correct"]
        saved_record.score = evaluation["score"]
        await saved_record.save()
    result.update({
        "is_correct": evaluation["is_correct"],
        "score": 100.0 if evaluation["is_correct"] else 0.0,
        "correct_answer": None,
        "analysis": evaluation["feedback"],
        "feedback": evaluation["feedback"],
    })
    return result


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

    result = await _submit_open_answer(user_id, record, str(answer_text or ""), time_spent, session_id)
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
