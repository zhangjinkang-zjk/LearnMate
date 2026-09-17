"""首次使用能力诊断：逐题生成、判分并同步知识点掌握度。"""

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any

from backend.src.models.exam_model import ExamQuestion, ExamRecord
from backend.src.models.portraitmodel import User_picture
from backend.src.models.usermodel import User
from backend.src.service.exam.service import ExamService
from backend.src.service.portrait.service import dump_traits, is_usable_direction, parse_traits, record_learning_event
from backend.src.utils import llm_stream
from backend.src.utils.database import init_db
from backend.src.utils.json_parser import parse_llm_json
from backend.src.utils.prompt_loader import fill_prompt, load_prompt

logger = logging.getLogger(__name__)

_MIN_QUESTIONS = 3
_MAX_QUESTIONS = 5

# 出题/判分各有兜底，但兜底只有在调用**返回**之后才有机会跑。模型挂住不给响应时
# 必须靠超时把它推进兜底分支，否则诊断流会一直发 keepalive、用户永远等不到下一题。
#
# 60 秒这个值是按实测分布定的，不是拍的：同一个诊断提示词（1137 字）四次采样分别是
# 9.3s / 20.8s / 50.8s / 156s。当前模型是推理模型且吞吐随供应商负载波动（约 10~21
# token/秒），慢的是长尾而不是首字 —— 流式调用首字只要 1.9 秒。
# 40 秒卡在分布中间，一半的题会掉兜底；60 秒能覆盖到 50.8s 那档，最长等待仍是 1 分钟。
# 之所以不能再往上抬：诊断有 5 题，180 秒的兜底上限会变成十几分钟的等待，比兜底题更糟。
try:
    _DIAGNOSIS_LLM_TIMEOUT = max(5, int(os.getenv("DIAGNOSIS_LLM_TIMEOUT_SECONDS", "60")))
except (TypeError, ValueError):
    _DIAGNOSIS_LLM_TIMEOUT = 60

# asyncio 只保留任务的弱引用，不留强引用的话后台任务可能在跑完前被 GC 掉。
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


# 两段式输出的处理放在 utils/llm_stream（画像访谈也用同一套）。这里保留这几个别名，
# 免得改一处就要动一片调用点。
_VISIBLE_MARKER = llm_stream.VISIBLE_MARKER
_channel_writer = llm_stream.bind_channel
_split_visible = llm_stream.split_visible
_consume_stream = llm_stream.consume_stream
_tail_payload = llm_stream.tail_payload


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
    # 只覆盖这几个键，不整份替换 onboarding：整份替换会把 init_from_dialogue 存在那里的
    # onboarding["assessment"]（访谈之后那次测评的结果）一起抹掉。首次流程撞不上这件事
    # —— 诊断跑在画像生成之前 —— 但**重做一次诊断**就会，而那条记录正是"这个起点是
    # 怎么来的"的答案。新测评的结果由收尾时的 init_from_dialogue 覆盖，这里不动它。
    onboarding = traits.get("onboarding")
    if not isinstance(onboarding, dict):
        onboarding = {}
    onboarding.update({
        "identity": identity[:80],
        "goal": goal[:160],
        "source": "user_stated",
    })
    # 学习方向要是一个真的方向才能写。学生第 1 问答「不知道」时，这个字符串以前照样被
    # 存下来，然后一路被拿去拆科目、生成路径 —— 最后长出一整套跟他的方向毫无关系的课。
    # 拿不到就保留画像里已有的（可能是定向页填的，也可能是上一次真的方向），不覆盖。
    if is_usable_direction(direction):
        onboarding["direction"] = direction[:120]
    else:
        logger.warning("诊断收到的学习方向不可用，不写进画像 direction=%r", direction)
    traits["onboarding"] = onboarding
    # 保留后端既有枚举字段供画像/路径逻辑使用，原始中文目标放在 traits 中。
    # 这个枚举描述的是**目标**（考试/竞赛/考证/兴趣/求职），所以只从 goal 推 ——
    # 从方向推会得到"interest"，把"为就业准备"这类目标丢掉。
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


async def _generate_question(user_id: int, identity: str, direction: str, goal: str, history: list[dict], index: int, max_steps: int, on_delta=None) -> dict:
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
        state = await _consume_stream(
            llm.astream(prompt, priority="high", user_id=int(user_id), pool="diagnosis"),
            on_delta,
            timeout=_DIAGNOSIS_LLM_TIMEOUT,
        )
        if state["raw"]:
            result = _tail_payload(state["raw"])
            # 正文以流出来的那句为准（它就是学生屏幕上已经看到的东西）；JSON 里若还带了
            # content（老格式），只在流式那段为空时兜一下。
            content = state["visible"].strip() or str(result.get("content") or "").strip()
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


async def _evaluate_answer(user_id: int, question: ExamQuestion, answer_text: str, on_delta=None) -> dict:
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
        state = await _consume_stream(
            llm.astream(prompt, priority="high", user_id=int(user_id), pool="diagnosis"),
            on_delta,
            timeout=_DIAGNOSIS_LLM_TIMEOUT,
        )
        if state["raw"]:
            result = _tail_payload(state["raw"])
            is_correct = result.get("is_correct")
            if isinstance(is_correct, bool):
                # 学生屏幕上那句就是服务端认的那句，两者必须同一个来源 —— 否则会出现
                # "屏幕上说答得好、后台判 0 分"这种自相矛盾。
                text = state["visible"].strip() or str(result.get("feedback") or "").strip() or feedback_basis or "已记录你的回答。"
                return {"is_correct": is_correct, "score": 1.0 if is_correct else 0.0, "feedback": text[:500]}
    except Exception:
        logger.warning("开放回答评估失败，使用关键词兜底 user_id=%s question_id=%s", user_id, question.id, exc_info=True)
    return _fallback_evaluation(question, answer)


async def _submit_open_answer(user_id: int, record: ExamRecord, answer_text: str, time_spent: int | None, session_id: str, on_delta=None) -> dict:
    question = await record.question
    evaluation = await _evaluate_answer(user_id, question, answer_text, _channel_writer(on_delta, "reply"))
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


async def start(user_id: int, identity: str, direction: str, goal: str, max_steps: int = 3, on_delta=None) -> dict:
    await init_db()
    identity, direction, goal = str(identity or "").strip(), str(direction or "").strip(), str(goal or "").strip()
    if not identity or not direction or not goal:
        raise ValueError("身份、学习方向和学习目标不能为空")
    # 有值但不等于有方向：提示词里出现"学习方向：不知道"时，模型会照着"一个不知道该学
    # 什么的人"出一整套题，这次诊断就白做了。当成未填写处理，让它按身份和目标问。
    if not is_usable_direction(direction):
        logger.warning("诊断启动时学习方向不可用，按未填写处理 direction=%r", direction)
        direction = ""
    max_steps = max(_MIN_QUESTIONS, min(int(max_steps or _MIN_QUESTIONS), _MAX_QUESTIONS))
    await _save_onboarding_context(user_id, identity, direction, goal)
    try:
        await record_learning_event(
            user_id,
            "onboarding",
            evidence=f"学习方向：{direction}；学习目标：{goal}",
            metadata={"identity": identity, "direction": direction, "goal": goal},
        )
    except Exception:
        logger.exception("首次定向学习事件记录失败 user_id=%s", user_id)
    session_id = str(uuid.uuid4())[:12]
    payload = await _generate_question(user_id, identity, direction, goal, [], 0, max_steps, _channel_writer(on_delta, "question"))
    question = await _create_question(user_id, session_id, payload)
    return {"session_id": session_id, "current_index": 0, "total_questions": max_steps, "question": _safe_question(question)}


def _replay_feedback(record: ExamRecord) -> dict:
    """重复提交时的反馈：用已落库的判定还原，不再让模型判一次。"""
    is_correct = bool(record.is_correct)
    note = "这道题的判定已经记录过了，我们接着往下。"
    return {
        "is_correct": is_correct,
        "score": 100.0 if is_correct else 0.0,
        "correct_answer": None,
        "analysis": note,
        "feedback": note,
    }


async def answer(user_id: int, session_id: str, question_id: int, answer_text: str, time_spent: int | None = None, max_steps: int = 3, on_delta=None) -> dict:
    await init_db()
    max_steps = max(_MIN_QUESTIONS, min(int(max_steps or _MIN_QUESTIONS), _MAX_QUESTIONS))
    record = await ExamRecord.filter(user_id=user_id, session_id=session_id, question_id=question_id).first()
    if not record:
        raise ValueError("诊断题目不存在或不属于当前会话")

    if record.is_correct is not None:
        # 答案上一轮已经落库，但下一题没生成出来（客户端断连触发了取消、模型超时、进程重启…）。
        # 这里必须能接着往下走：抛"该题已经提交过"会把用户永久钉在这一题上，重试永远失败，
        # 只能整轮重开、进度清零 —— 也就是用户看到的"诊断异常中断"。
        # 注意不能重跑 _submit_open_answer：ExamService.submit_answer 会再记一次掌握度、
        # 学习事件和雷达，重复提交等于把同一次作答统计两次。
        logger.info(
            "诊断题重复提交，接续已有判定 user_id=%s session_id=%s question_id=%s",
            user_id, session_id, question_id,
        )
        feedback = _replay_feedback(record)
        summary = await ExamService.get_session(session_id, user_id) or {}
    else:
        feedback = await _submit_open_answer(user_id, record, str(answer_text or ""), time_spent, session_id, on_delta)
        summary = feedback.get("session_summary") or {}

    records = await ExamRecord.filter(user_id=user_id, session_id=session_id).order_by("id").prefetch_related("question").all()
    answered = [item for item in records if item.is_correct is not None]
    if len(answered) >= max_steps:
        percentage = summary.get("percentage")
        user = await User.filter(id=user_id).first()
        picture = await user.picture if user else None
        onboarding = parse_traits(picture.traits if picture else None).get("onboarding") or {}
        # 放后台跑，诊断结果立刻返回，用户在结果页看「正在分析」而不是干等最后一题。
        _spawn_background(_generate_paths_after_diagnosis(
            user_id,
            onboarding.get("direction", ""),
            onboarding.get("goal", ""),
        ))
        return {"finished": True, "reply": _reply_text(feedback), "feedback": feedback, "result": {"session_id": session_id, "percentage": percentage, "correct_count": summary.get("correct_count", 0), "total_questions": len(records), "message": _result_message(percentage)}}

    user = await User.filter(id=user_id).first()
    picture = await user.picture if user else None
    traits = parse_traits(picture.traits if picture else None)
    onboarding = traits.get("onboarding") or {}
    history = []
    for index, item in enumerate(answered):
        history.append({"index": index + 1, "content": item.question.content, "answer_text": item.user_answer or "", "is_correct": bool(item.is_correct)})
    payload = await _generate_question(user_id, onboarding.get("identity", ""), onboarding.get("direction", ""), onboarding.get("goal", ""), history, len(answered), max_steps, _channel_writer(on_delta, "question"))
    question = await _create_question(user_id, session_id, payload)
    return {"finished": False, "reply": _reply_text(feedback), "feedback": feedback, "current_index": len(answered), "total_questions": max_steps, "question": _safe_question(question)}


def _reply_text(feedback) -> str:
    """回给学生的这一句反馈，**保证非空**。

    以前这句话是前端自己去嵌套字典里掏的（先 `feedback.feedback`，再 `feedback.analysis`），
    任何一层形状对不上，学生看到的就是"正在生成回复…"—— 一句永远不会兑现的话，而服务端
    其实已经把反馈写好了。掏不到、类型不对、空串，全都长得一样：屏幕上少一句话，没人知道。

    所以这里把它变成响应体上的一个平铺字段，并且这里是唯一出口：真拿不到就给一句诚实的话，
    而不是留空让前端去猜。
    """
    if isinstance(feedback, str):
        text = feedback
    else:
        data = feedback if isinstance(feedback, dict) else {}
        text = data.get("feedback") or data.get("analysis") or ""
    return str(text).strip() or "已记录你的回答，我们接着往下。"


def _result_message(percentage: float | None) -> str:
    score = float(percentage or 0)
    if score >= 85:
        return "基础概念和应用都较稳定，可以直接进入迁移练习。"
    if score >= 60:
        return "已经具备部分基础，建议先补齐关键方法，再进入项目练习。"
    return "目前处于起步阶段，建议先完成基础讲解，再用小任务建立理解。"


async def _generate_paths_after_diagnosis(user_id: int, direction: str, goal: str) -> None:
    """答完诊断后拆解方向并创建科目路径。失败只记日志，不连累诊断结果返回。"""
    try:
        from backend.src.service.curriculum.service import sync_direction_subjects
        from backend.src.service.path.service import PathService

        subjects = await sync_direction_subjects(user_id, direction, goal, 4)
        logger.info("诊断完成，开始生成学习路径 user_id=%s direction=%s subjects=%s", user_id, direction, subjects)
        results = await asyncio.gather(
            *[PathService.generate_path(subject, user_id, "medium", 0) for subject in subjects],
            return_exceptions=True,
        )
        failed = [str(item) for item in results if isinstance(item, Exception)]
        if failed:
            logger.error("学习路径生成部分失败 user_id=%s failed=%s", user_id, failed)
        else:
            logger.info("学习路径生成完成 user_id=%s path_count=%s", user_id, len(results))
    except Exception:
        logger.exception("诊断后学习路径生成失败 user_id=%s direction=%s", user_id, direction)
