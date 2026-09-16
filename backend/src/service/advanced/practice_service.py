"""进阶学习巩固会话：持久化对话状态并评价最终提交。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from tortoise.exceptions import IntegrityError

from backend.src.models.advanced_practice_model import AdvancedPracticeSession
from backend.src.models.advanced_task_model import AdvancedTaskSnapshot
from backend.src.models.path_model import LearningPath, PathNode
from backend.src.service.advanced.task_jobs import ensure_grading_job, is_grading

logger = logging.getLogger(__name__)

# ── 智能体判分 ────────────────────────────────────────
# `_evaluate` 是确定性基线：正则匹配「依据/验证/方案」几个词，给 30+20+10 分。一条
# 同时含这三个词的消息就是 60 分，正好压在通过线上 —— 它量的不是"方案好不好"，而是
# "有没有出现这几个词"。所以智能体在它的基础上做一次真正的判分。
#
# 两个约束决定了整形的形状：
#
# 1. **判分口径来自服务端。** `session.task_snapshot` 是 `open_session` 时由客户端传的
#    （`PracticeSessionRequest.task`），用它判分等于让提交方自己定验收线 —— 比正则还
#    好作弊。所以标准从 `AdvancedTaskSnapshot` 里按 task_key 取。
# 2. **判分不能阻塞提交。** 实测一次判分（提示词 1359 字）耗时 57.6 秒，而前端
#    httpClient 的超时是 15 秒 —— 差了近 4 倍，同步判分必然超时。所以提交立刻返回
#    确定性基线，智能体在后台复核，复核完覆盖它（见 `practice_evaluation_status`）。
PASS_SCORE = 60
GRADING_TIMEOUT_SECONDS = 120
CRITERIA_LABELS = ("问题理解", "证据与依据", "方案取舍", "验证方法")

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
PHASE_ORDER = tuple(phase_id for phase_id, _ in PHASES)
MAX_MESSAGES = 120
MAX_MESSAGE_LENGTH = 4000

# ── 阶段推进 ──────────────────────────────────────────
# 阶段进度是**服务端**的账本。以前它由前端无条件推进（每说一句话就过一关），并且
# `PATCH /practice/sessions/{id}` 原样采信客户端传来的 `completed_phase_ids` —— 而
# `_evaluate` 的 phase_score 就是 `len(completed) / 6 * 40`，所以一次请求就能把六个
# 阶段全标完成、直接拿满这 40 分。
#
# 现在改成：智能体在回复末尾写一个内联标记 `[[PHASE:done]]`，服务端解析它并推进。
# 标记不带阶段 id（值只认 `done`），所以模型没法跳过中间的阶段，每轮最多推一格。
PHASE_DONE_MARKER = "done"
# 宽松匹配 `[[PHASE: done]]` / `[[phase:DONE]]`，免得模型大小写或空格不一致就白写。
_MARKER_PATTERN = re.compile(r"\[\[\s*phase\s*:\s*([A-Za-z_]+)\s*\]\]", re.IGNORECASE)
_MARKER_OPEN = "[["
# 收到 `[[` 时还不知道后面是不是标记，先扣住；扣满这么多字符仍不闭合就当普通正文放行，
# 免得一个孤立的 `[[`（比如模型在引用语法）把后面的内容全卡住。标记本身最长
# `[[PHASE:hypothesis]]` 是 19 个字符，留 32 够用。
_MARKER_MAX_TAIL = 32


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


def _clean_phases(values: Any) -> list[str]:
    """把阶段 id 列表规整成 `PHASES` 顺序，去掉重复和未知值。"""
    cleaned = _clean_list(values, limit=len(PHASES), item_limit=32)
    return [phase_id for phase_id in PHASE_ORDER if phase_id in set(cleaned)]


def _next_phase(phase_id: str) -> str | None:
    """下一个阶段 id；已经是最后一个阶段则返回 None。"""
    if phase_id not in PHASE_IDS:
        return None
    index = PHASE_ORDER.index(phase_id)
    return PHASE_ORDER[index + 1] if index + 1 < len(PHASE_ORDER) else None


def clamp_current_phase(requested: str, completed: Any) -> str:
    """把客户端想要的当前阶段夹紧到它已经解锁的范围内。

    回看任何一个**已完成**的阶段是允许的（那只是浏览），但不能往前跳到还没解锁的
    阶段 —— 否则一轮对话就能把 `current_phase` 推到最后，进度条显示的就不是真实
    进度了。这跟前端 `isPhaseAvailable` 是同一条规则，区别是这条规则现在由服务端
    说了算，前端只负责提前给出反馈。
    """
    if requested not in PHASE_IDS:
        return PHASE_ORDER[0]
    done = _clean_phases(completed)
    unlocked = min(len(done), len(PHASE_ORDER) - 1)
    index = PHASE_ORDER.index(requested)
    return requested if index <= unlocked else PHASE_ORDER[unlocked]


def advance_phase_state(completed: Any, current_phase: str, markers: Any) -> tuple[list[str], str]:
    """按智能体留下的标记推进一格，返回新的 `(completed, current_phase)`。

    没有 `done` 标记就原样返回 —— 学生只是聊了一轮，不构成过关。有标记时只完成
    **当前**阶段（标记不带阶段 id），所以进度永远是连续前缀，不会出现
    `["understand", "review"]` 这种跳级状态。
    """
    done = _clean_phases(completed)
    current = current_phase if current_phase in PHASE_IDS else PHASE_ORDER[0]
    seen = {str(item or "").strip().lower() for item in markers or []}
    if PHASE_DONE_MARKER not in seen:
        return done, current
    done = _clean_phases([*done, current])
    return done, _next_phase(current) or current


def practice_record_text(session: Any) -> str:
    """把服务端手里的会话记录拼成"本次巩固总结"的输入。

    **不取客户端传来的文本**：那等于让调用方自己描述"我刚才学了什么"，总结就变成给
    自己的作文打分。消息、阶段、评价在库里都有权威版本，用它们 —— 和阶段推进同一个
    道理，能自己算的就别问客户端。
    """
    snapshot = getattr(session, "task_snapshot", None)
    if not isinstance(snapshot, dict):
        snapshot = {}
    completed = _clean_phases(getattr(session, "completed_phases", None))
    labels = "、".join(PHASE_LABELS[item] for item in completed) or "还没有阶段完成"
    lines = [
        f"任务：{_clip_text(snapshot.get('title'), 120) or '实践任务'}",
        f"已完成阶段：{labels}",
    ]
    transcript = _transcript_text(getattr(session, "messages", None))
    if transcript:
        lines.append("对话记录：")
        lines.append(transcript)
    evaluation = getattr(session, "evaluation", None)
    if isinstance(evaluation, dict) and evaluation.get("label"):
        lines.append(f"提交结果：{evaluation['label']}（{evaluation.get('score')} 分）")
    return "\n".join(lines)


def _transcript_text(messages: Any, *, limit: int = 20, item_limit: int = 260) -> str:
    """把对话记录拼成给模型看的一段文本，跳过坏行和空行。"""
    lines = [
        f"{'学生' if item.get('role') == 'user' else '助教'}：{_clip_text(item.get('text'), item_limit)}"
        for item in (messages if isinstance(messages, list) else [])[-limit:]
        if isinstance(item, dict) and _clip_text(item.get("text"), item_limit)
    ]
    return "\n".join(lines)


def build_grading_prompt(task: dict, messages: Any, completed: list[str], submission: str) -> str:
    """拼一次判分的输入。`task` 必须是服务端快照里那个任务（见 `resolve_server_task`）。"""
    from backend.src.utils.prompt_loader import fill_prompt, load_prompt

    task = task if isinstance(task, dict) else {}
    deliverables = [
        item.get("label") if isinstance(item, dict) else item
        for item in task.get("deliverables") or []
    ]
    phases = "、".join(PHASE_LABELS[item] for item in completed if item in PHASE_LABELS)
    return fill_prompt(
        load_prompt("advanced/practice_evaluator"),
        task_title=_clip_text(task.get("title"), 240) or "当前实践任务",
        task_problem=_clip_text(task.get("problem") or task.get("scenario"), 600) or "（未提供情境）",
        task_focus=_clip_text(task.get("focus"), 240) or "（未指定）",
        criteria_json=json.dumps(
            [str(item) for item in task.get("criteria") or [] if item] or ["（这个任务没有单独列出验收标准）"],
            ensure_ascii=False,
        ),
        # 输出用的四条例行评分维度由服务端给出，和 parse_grading_payload 的校验同源 ——
        # 提示词里写死一份的话，两边一旦漂移就是"每次判分都被判为不合约"。
        rubric_labels_json=json.dumps(list(CRITERIA_LABELS), ensure_ascii=False),
        deliverables_json=json.dumps(
            [str(item) for item in deliverables if item] or ["（未指定交付物）"],
            ensure_ascii=False,
        ),
        completed_phases=phases or "没有阶段记录",
        transcript=_transcript_text(messages, limit=12, item_limit=300) or "（这次没有留下对话记录）",
        submission=_clip_text(submission, 3000) or "（提交内容为空）",
    )


def parse_grading_payload(raw: Any) -> dict | None:
    """解析智能体返回的判分 JSON。

    任何一处不合约就**整体作废**：半份评价比没有评价更难解释，而且我们本来就有确定性
    基线可以退。四条验收标准的 label 必须逐字对上 —— 对不上说明模型没按契约走，
    这时候它的分数也不可信。
    """
    if not isinstance(raw, dict):
        return None
    try:
        score = int(round(float(raw.get("score"))))
    except (TypeError, ValueError):
        return None
    criteria = raw.get("criteria")
    if not isinstance(criteria, list):
        return None
    passed_by_label: dict[str, bool] = {}
    for item in criteria:
        if not isinstance(item, dict):
            continue
        label = _clip_text(item.get("label"), 40)
        if label in CRITERIA_LABELS:
            passed_by_label[label] = bool(item.get("passed"))
    if len(passed_by_label) != len(CRITERIA_LABELS):
        return None
    return {
        "score": max(0, min(100, score)),
        "criteria": [
            {"label": label, "passed": passed_by_label[label]} for label in CRITERIA_LABELS
        ],
        "strengths": _clean_list(raw.get("strengths"), limit=3, item_limit=160),
        "next_steps": _clean_list(raw.get("next_steps"), limit=3, item_limit=160),
    }


def merge_evaluation(baseline: dict, graded: dict | None, *, eligible: bool) -> dict:
    """把智能体的复核结果落在确定性基线上；没有复核结果就整份用基线。

    `eligible`（有提交正文、且学生至少说过一句话）是**服务端的事实**，智能体不能翻案
    —— 否则一句"任务已完成"就能让空提交过关。验收标准的 label 也由基线提供，智能体
    只决定每条的 `passed`。
    """
    if not graded:
        return {**baseline, "source": "deterministic"}
    score = graded["score"]
    passed = bool(eligible and score >= PASS_SCORE)
    graded_passed = {item["label"]: item["passed"] for item in graded["criteria"]}
    return {
        "score": score,
        "passed": passed,
        "label": "达到当前任务要求" if passed else "已提交，仍需补强",
        "strengths": graded["strengths"] or baseline["strengths"],
        "next_steps": graded["next_steps"] or baseline["next_steps"],
        "criteria": [
            {"label": item["label"], "passed": graded_passed.get(item["label"], item["passed"])}
            for item in baseline["criteria"]
        ],
        "task_title": baseline.get("task_title") or "当前实践任务",
        "source": "agent",
    }


async def resolve_server_task(user_id: int, path_id: int, task_key: str) -> dict:
    """按 task_key 从服务端的任务快照里取这个任务（含验收标准）。

    取不到就返回空 dict，调用方自行决定退路 —— 这个函数只负责回答"服务端手上有没有"。
    """
    rows = await AdvancedTaskSnapshot.filter(user_id=user_id, path_id=path_id).all()
    for row in rows:
        payload = row.task_json if isinstance(row.task_json, dict) else {}
        for item in payload.get("tasks") or []:
            if isinstance(item, dict) and str(item.get("id") or "") == str(task_key):
                return item
    return {}


async def run_grading(user_id: int, session_key: str) -> None:
    """后台评分作业：跑一次智能体判分，把结果覆盖到会话上。

    失败一律退回已经写好的确定性基线 —— "智能体挂了"的后果是回到改动前的行为，
    而不是"没有分数"。
    """
    from backend.src.service.advanced.service import _describe_failure

    session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
    if session is None or session.status != "completed" or not session.evaluation:
        return

    messages = session.messages if isinstance(session.messages, list) else []
    completed = _clean_phases(session.completed_phases)
    submission = session.final_submission or ""
    baseline = session.evaluation if isinstance(session.evaluation, dict) else {}
    eligible = bool(
        submission.strip() and any(item.get("role") == "user" for item in messages if isinstance(item, dict))
    )

    task = await resolve_server_task(user_id, session.path_id, session.task_key)
    if not task:
        # 服务端没有这个任务的快照（里程碑可能已经被覆盖过）。退回会话里那份 ——
        # 它是客户端建的，但总比判不了分强；这条日志就是"还在用客户端口径"的痕迹。
        task = session.task_snapshot if isinstance(session.task_snapshot, dict) else {}
        logger.warning(
            "实践评分找不到服务端任务快照，退回会话快照 session_key=%s task_key=%s",
            session_key,
            session.task_key,
        )

    graded = None
    try:
        from backend.src.ai_core.llm_config import llm
        from backend.src.utils.json_parser import parse_llm_json

        prompt = build_grading_prompt(task, messages, completed, submission)
        response = await asyncio.wait_for(
            llm.ainvoke(prompt, priority="low", user_id=user_id, pool="advanced"),
            timeout=GRADING_TIMEOUT_SECONDS,
        )
        graded = parse_grading_payload(parse_llm_json(response.content))
        if graded is None:
            raise ValueError("实践评分返回的结构不合约，已作废")
    except Exception as exc:
        logger.warning(
            "实践评分降级到确定性基线 session_key=%s error=%s",
            session_key,
            _describe_failure(exc),
        )
        graded = None

    session.evaluation = merge_evaluation(baseline, graded, eligible=eligible)
    await session.save(update_fields=["evaluation", "updated_at"])
    logger.info(
        "实践评分完成 session_key=%s source=%s score=%s",
        session_key,
        session.evaluation.get("source"),
        session.evaluation.get("score"),
    )


def practice_evaluation_status(session: AdvancedPracticeSession) -> str:
    """这次会话的评价定稿了没有。

    提交后立刻就给一份确定性基线（用户不用等），智能体复核完再覆盖它 —— 所以
    "有没有分数"和"分数定没定稿"是两件事，前端要分开显示。
    """
    if session.status != "completed" or not session.evaluation:
        return "none"
    user_id = getattr(session, "user_id", None)
    if user_id is None:
        return "ready"
    return "reviewing" if is_grading(user_id, session.session_key) else "ready"


class PhaseStreamStripper:
    """边流边剥：把 `[[PHASE:done]]` 从智能体回复里摘掉，并记下它看到过什么标记。

    这些约束决定了它必须是个有状态的类，而不是一个函数：

    1. **标记会跨分片。** `[[PHASE:do` 和 `ne]]` 是两个 chunk，逐 chunk 做正则
       匹配永远匹配不上，会话里就会留下半截标记。所以匹配在累积文本上做。
    2. **尾巴不能急着下发。** 收到 `[[` 时还不知道后面是不是标记，先扣住；但模型
       万一真的就想说 `[[`，一直扣住会把正文卡死，所以扣够 `_MARKER_MAX_TAIL`
       个字符就放行。
    3. **剥掉的不只是流。** 调用方要用 `text`（而不是自己拼的原始文本）去落库，
       否则用户重新打开会话还是能看到残留的标记。
    """

    def __init__(self) -> None:
        self._raw = ""
        self._clean = ""
        self._emitted = 0
        self.markers: list[str] = []

    def feed(self, chunk: Any) -> str:
        """吃进一个分片，返回这次能安全下发的文本（已剥掉标记，可能为空串）。"""
        self._raw += str(chunk or "")
        safe = self._safe_length()
        if safe <= self._emitted:
            return ""
        segment = self._raw[self._emitted:safe]
        self._emitted = safe
        return self._strip(segment)

    def flush(self) -> str:
        """流结束：把扣住的尾巴吐出来（到这里不可能再有完整标记了）。"""
        segment = self._raw[self._emitted:]
        self._emitted = len(self._raw)
        return self._strip(segment)

    @property
    def text(self) -> str:
        """剥离标记之后的完整回复，用于落库和字数统计。"""
        return self._clean

    def _strip(self, segment: str) -> str:
        if not segment:
            return ""
        clean = _MARKER_PATTERN.sub(self._record, segment)
        self._clean += clean
        return clean

    def _record(self, match: re.Match) -> str:
        value = match.group(1).strip().lower()
        if value and value not in self.markers:
            self.markers.append(value)
        return ""

    def _safe_length(self) -> int:
        """`_raw` 里可以安全下发的长度 —— 末尾还没成形的标记不算。

        这里有一个容易漏掉的分片边界：`[` 和它后面那个 `[` 可能落在相邻两片里。
        如果放走了末尾这个单独的 `[`，下一片到达时 `[[` 就横跨在"已下发 / 未下发"
        之间，正则再也匹配不到，标记会被原样漏给学生。所以**末尾的单个 `[` 一律扣住**，
        这样 `[[` 只会出现在未下发的尾巴里，`rfind` 从 `_emitted` 起就一定能找到它。
        """
        limit = len(self._raw)
        if self._raw.endswith("["):
            limit -= 1
        index = self._raw.rfind(_MARKER_OPEN, self._emitted)
        if index < 0:
            return limit
        if self._raw.find("]]", index) >= 0:
            return limit
        if len(self._raw) - index > _MARKER_MAX_TAIL:
            return limit
        return index


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
        "evaluation_status": practice_evaluation_status(session),
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
        # `completed_phase_ids` 只保留在签名里兼容旧客户端：**不采信**。进度唯一的
        # 来源是流式回复里的 `[[PHASE:done]]` 标记（见 `record_phase_markers`）。
        completed = _clean_phases(session.completed_phases)
        session.status = "active"
        session.current_phase = clamp_current_phase(current_phase, completed)
        session.completed_phases = completed
        session.messages = _clean_messages(messages)
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.ended_at = None
        await session.save()
        return _serialize(session)

    @staticmethod
    async def record_phase_markers(session: AdvancedPracticeSession, markers: Any) -> dict:
        """把智能体回复里的阶段标记记进服务端账本，返回要下发给前端的阶段状态。

        没有推进（或已经完成）时返回空 dict，调用方据此跳过这次 SSE 事件。这是
        **唯一**会写 `completed_phases` 的地方；`save_state` / `submit` 都只读它。
        """
        if session is None or session.status == "completed":
            return {}
        completed, current = advance_phase_state(
            session.completed_phases,
            session.current_phase,
            markers,
        )
        if completed == _clean_phases(session.completed_phases) and current == session.current_phase:
            return {}
        session.completed_phases = completed
        session.current_phase = current
        await session.save(update_fields=["completed_phases", "current_phase", "updated_at"])
        return {
            "current_phase": current,
            "current_phase_label": PHASE_LABELS.get(current, ""),
            "completed_phase_ids": completed,
        }

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
        # 判分用的阶段进度取服务端账本，不取本次请求 —— 这里的 phase_score 占 40 分，
        # 采信客户端等于把分数交给提交方自己填。
        completed = _clean_phases(session.completed_phases)
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
        session.current_phase = clamp_current_phase(current_phase, completed)
        session.completed_phases = completed
        session.messages = normalized_messages
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.final_submission = submission
        # 先落确定性基线再回响应：用户不用等智能体。复核是另一件事，由下面的作业覆盖
        # 这份评价（`evaluation_status` 告诉前端它还在不在跑）。
        session.evaluation = {**evaluation, "source": "deterministic"}
        session.ended_at = datetime.now()
        await session.save()
        await ensure_grading_job(
            user_id,
            session.session_key,
            lambda: run_grading(user_id, session.session_key),
        )
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
