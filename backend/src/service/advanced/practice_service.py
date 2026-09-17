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

# ── 阶段词汇 ──────────────────────────────────────────
# 每个阶段是 `(id, label, hint)`。id 进账本和数据库，label/hint 只给人看。
#
# **通用词汇（下面这 6 个）是"没有 kind 的会话"用的**，也就是这次改动之前建的所有
# 会话 —— 它们的 `completed_phases` 里存的就是这 6 个 id。保留它是为了**不做数据
# 迁移**：老会话继续按 6 阶段解释，进度不丢。
#
# 新会话按任务类型取 `PHASE_SETS` 里那一套（都是 4 个）。三类任务的阶段数一致是有
# 意的：`phase_score` 的分母就是阶段数，统一成 4 才不会让某一类任务"每阶段更值钱"。
PHASES = (
    ("understand", "理解问题", "界定目标与限制"),
    ("evidence", "寻找证据", "从材料提取依据"),
    ("hypothesis", "提出假设", "说明可能原因"),
    ("compare", "比较方案", "解释取舍关系"),
    ("verify", "验证结果", "设计检查方法"),
    ("review", "总结", "留下可复查结论"),
)
PHASE_IDS = {phase_id for phase_id, _, _ in PHASES}
PHASE_LABELS = {phase_id: label for phase_id, label, _ in PHASES}
PHASE_ORDER = tuple(phase_id for phase_id, _, _ in PHASES)

PHASE_SETS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "case": (
        ("clues", "线索筛选", "圈出材料里可用的线索"),
        ("fault", "定位故障", "指出出问题的环节"),
        ("reasoning", "说明推理", "讲清从线索到结论的链条"),
        # 不是 `hypothesis`：那个 id 已经在通用词汇里表示"提出假设"，同一个 id 在两套
        # 词汇里指两个不同的阶段，"这串 id 属于哪一套"就没法只从 id 本身看出来。
        ("check", "验证假设", "给出能证伪的检查"),
    ),
    "transfer": (
        ("source", "识别原方法", "说清原情境里的做法"),
        ("breakdown", "找出失效点", "指出新情境下哪一条不成立"),
        ("redesign", "改造方案", "给出改造后的方案与取舍"),
        ("boundary", "说明边界", "讲清适用范围与失效条件"),
    ),
    "project": (
        ("scope", "拆解需求", "界定目标、约束与交付物"),
        ("delivery", "阶段交付", "按阶段产出可检查的结果"),
        ("integration", "集成验证", "把各部分接起来并验证"),
        ("retro", "复盘", "留下可复查的结论"),
    ),
}

MAX_MESSAGES = 120
MAX_MESSAGE_LENGTH = 4000


def phases_for(kind: Any) -> tuple[tuple[str, str, str], ...]:
    """这个任务类型用哪套阶段。缺失或未知 kind → 通用 6 阶段。

    回落到通用集合而不是某个默认类型，是因为"没有 kind"恰恰是**改动之前建的会话**
    的记号：它们必须继续按老词汇解释，否则进度会被当成未知 id 全部丢掉。
    """
    return PHASE_SETS.get(str(kind or "").strip().lower(), PHASES)


def snapshot_phases(snapshot: Any) -> tuple[tuple[str, str, str], ...]:
    """会话快照该用哪套阶段：快照里的 kind 选词汇，快照里的 stages 提供文案。

    快照里的 `stages` 是"服务端 id + 任务生成器文案"合并后的结果（见
    `_clean_stages`），所以文案用它那份更像给人看的；**id 一定以服务端这套为准** ——
    按 id 去取它的文案，取不到就用默认文案。
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    base = phases_for(snapshot.get("kind"))
    stored = {
        str(item.get("id")): item
        for item in (snapshot.get("stages") or [])
        if isinstance(item, dict) and item.get("id")
    }
    if not stored:
        return base
    merged = []
    for phase_id, label, hint in base:
        item = stored.get(phase_id) or {}
        merged.append((
            phase_id,
            _clip_text(item.get("label"), 40) or label,
            _clip_text(item.get("hint"), 60) or hint,
        ))
    return tuple(merged)


def session_phases(session: Any) -> tuple[tuple[str, str, str], ...]:
    return snapshot_phases(getattr(session, "task_snapshot", None))

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


# ── 阶段账本 ──────────────────────────────────────────
# 下面四个函数都要求显式传 `phases`（该会话那套词汇）。不给默认值是有意的：写一个
# 默认值看起来省事，但调用点漏传时就会**静默**地用错词汇 —— 症状是用户的进度被当成
# 未知 id 清空，而日志里什么都不显。宁可让 8 个调用点各自写明白。

def _clean_deliverable_state(values: Any, snapshot: Any) -> dict[str, bool]:
    """交付物勾选状态：只留这条任务真有的交付物，值只留 bool。

    上限跟着快照里的交付物条数走 —— 学生勾的是任务给他的那份清单，客户端塞进来的
    多余键既没意义也没地方显示，留着只会让下次 hydrate 出一堆幽灵条目。
    """
    if not isinstance(values, dict):
        return {}
    labels = (snapshot or {}).get("deliverables") if isinstance(snapshot, dict) else None
    if not isinstance(labels, list):
        return {}
    allowed = {_clip_text(label, 240) for label in labels}
    return {
        _clip_text(key, 240): bool(value)
        for key, value in values.items()
        if _clip_text(key, 240) in allowed
    }


def _clean_phases(values: Any, phases: Any) -> list[str]:
    """把阶段 id 列表规整成 `phases` 的顺序，去掉重复和未知值。

    未知 id 会被丢掉 —— 这正是"前端不能拿任务 stages 的 id 去往返"的原因：两套词汇
    只共用一个 `verify`，混着用等于把进度清零。
    """
    order = tuple(item[0] for item in phases)
    cleaned = _clean_list(values, limit=len(order), item_limit=32)
    return [phase_id for phase_id in order if phase_id in set(cleaned)]


def _next_phase(phase_id: str, phases: Any) -> str | None:
    """下一个阶段 id；已经是最后一个阶段则返回 None。"""
    order = tuple(item[0] for item in phases)
    if phase_id not in order:
        return None
    index = order.index(phase_id)
    return order[index + 1] if index + 1 < len(order) else None


def clamp_current_phase(requested: str, completed: Any, phases: Any) -> str:
    """把客户端想要的当前阶段夹紧到它已经解锁的范围内。

    回看任何一个**已完成**的阶段是允许的（那只是浏览），但不能往前跳到还没解锁的
    阶段 —— 否则一轮对话就能把 `current_phase` 推到最后，进度条显示的就不是真实
    进度了。这跟前端 `isPhaseAvailable` 是同一条规则，区别是这条规则现在由服务端
    说了算，前端只负责提前给出反馈。
    """
    order = tuple(item[0] for item in phases)
    if requested not in order:
        return order[0]
    done = _clean_phases(completed, phases)
    unlocked = min(len(done), len(order) - 1)
    index = order.index(requested)
    return requested if index <= unlocked else order[unlocked]


def advance_phase_state(completed: Any, current_phase: str, markers: Any, phases: Any) -> tuple[list[str], str]:
    """按智能体留下的标记推进一格，返回新的 `(completed, current_phase)`。

    没有 `done` 标记就原样返回 —— 学生只是聊了一轮，不构成过关。有标记时只完成
    **当前**阶段（标记不带阶段 id），所以进度永远是连续前缀，不会出现
    `["understand", "review"]` 这种跳级状态。这套机制对任意阶段数和任意 id 都成立，
    所以换 kind 的阶段集合不需要动它，只要把 `phases` 传对。
    """
    order = tuple(item[0] for item in phases)
    done = _clean_phases(completed, phases)
    current = current_phase if current_phase in order else order[0]
    seen = {str(item or "").strip().lower() for item in markers or []}
    if PHASE_DONE_MARKER not in seen:
        return done, current
    done = _clean_phases([*done, current], phases)
    return done, _next_phase(current, phases) or current


def practice_record_text(session: Any) -> str:
    """把服务端手里的会话记录拼成"本次巩固总结"的输入。

    **不取客户端传来的文本**：那等于让调用方自己描述"我刚才学了什么"，总结就变成给
    自己的作文打分。消息、阶段、评价在库里都有权威版本，用它们 —— 和阶段推进同一个
    道理，能自己算的就别问客户端。
    """
    snapshot = getattr(session, "task_snapshot", None)
    if not isinstance(snapshot, dict):
        snapshot = {}
    phases = session_phases(session)
    completed = _clean_phases(getattr(session, "completed_phases", None), phases)
    phase_labels = {phase_id: label for phase_id, label, _ in phases}
    # 用人看的 label（"线索筛选"）而不是 id：这段文字直接喂给总结提示词，那边不该
    # 看见 kind 相关的内部 id。
    labels = "、".join(phase_labels[item] for item in completed) or "还没有阶段完成"
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


def build_grading_prompt(task: dict, messages: Any, completed: list[str], submission: str, phases: Any) -> str:
    """拼一次判分的输入。`task` 必须是服务端快照里那个任务（见 `resolve_server_task`）。

    `phases` 是这个会话那套阶段词汇：完成情况要用它的 label 呈现，否则项目实训的
    判分提示词里会写着"理解问题"这种别的类型的阶段名。
    """
    from backend.src.utils.prompt_loader import fill_prompt, load_prompt

    task = task if isinstance(task, dict) else {}
    deliverables = [
        item.get("label") if isinstance(item, dict) else item
        for item in task.get("deliverables") or []
    ]
    phase_labels = {phase_id: label for phase_id, label, _ in phases}
    completed_labels = "、".join(phase_labels[item] for item in completed if item in phase_labels)
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
        completed_phases=completed_labels or "没有阶段记录",
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
    phases = session_phases(session)
    completed = _clean_phases(session.completed_phases, phases)
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

        prompt = build_grading_prompt(task, messages, completed, submission, phases)
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
    """会话自己那份任务快照。

    这里以前只留了 id/title/problem/focus/criteria/deliverables，把 `kind` /
    `support_level` / `stages` 丢掉了 —— 而这三个恰恰决定"这次任务该怎么学"：
    阶段词汇按 kind 选，提示强度按 support_level 给，阶段文案优先用生成器写的那份。
    丢掉之后，会话就再也不知道自己做的是案例诊断还是项目实训了。
    """
    if not isinstance(task, dict):
        return {}
    kind = _clip_text(task.get("kind"), 32).lower()
    return {
        "id": _clip_text(task.get("id"), 128),
        "title": _clip_text(task.get("title"), 240),
        "kind": kind if kind in PHASE_SETS else "",
        "support_level": _clip_text(task.get("support_level"), 16).lower(),
        "problem": _clip_text(task.get("problem") or task.get("scenario"), 1200),
        "focus": _clip_text(task.get("focus"), 240),
        "criteria": _clean_list(task.get("criteria"), limit=8),
        "deliverables": _clean_list(
            [item.get("label") if isinstance(item, dict) else item for item in task.get("deliverables") or []],
            limit=8,
        ),
        # 阶段骨架（id/status）是服务端的，这里存的只是"给这个 id 配了什么文案"。
        "stages": _clean_stages(task.get("stages"), kind),
    }


def _clean_stages(stages: Any, kind: str) -> list[dict[str, str]]:
    """把任务里的 stages 规整成该 kind 的阶段骨架 + 它给的文案。

    id 和顺序一律取服务端那套：智能体写的 `context/plan/verify/review` 进不了账本，
    留着它只会在 `_clean_phases` 那里被静默丢掉。文案（label/hint）可以用它的。
    """
    phases = phases_for(kind)
    items = [item for item in (stages if isinstance(stages, list) else []) if isinstance(item, dict)]
    if len(items) != len(phases):
        return [{"id": pid, "label": label, "hint": hint} for pid, label, hint in phases]
    return [
        {
            "id": pid,
            "label": _clip_text(items[index].get("label"), 40) or label,
            "hint": _clip_text(items[index].get("hint"), 60) or hint,
        }
        for index, (pid, label, hint) in enumerate(phases)
    ]


def _welcome_message(snapshot: Any = None) -> dict[str, str]:
    """新建会话时种下的开场。

    这是学生进页面**立刻**能看到的那一句（教练那份开场是流式的，要等），所以它必须
    点出任务是什么：以前这里是一句跟任务无关的通用话术，学生看完不知道要回答什么，
    只能回一句"你在说啥"，要等第二轮模型才把任务讲清楚。

    阶段名取该会话那套词汇的首个阶段 —— 项目实训的第一句不该是"我们从理解问题开始"。
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    title = _clip_text(snapshot.get("title"), 120)
    phase = snapshot_phases(snapshot)[0][1]
    if title:
        text = (
            f"我们先从「{phase}」开始：这个任务要你产出的是「{title}」。"
            "先说说它要解决的核心问题，以及你准备依据哪些信息判断。"
        )
    else:
        text = f"我们从「{phase}」开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。"
    return {"role": "assistant", "text": text}


# 改动之前种下的那句开场。它不带任务名，所以被它开过头的会话等于还没开过头 ——
# 留着这个字面量是为了认得老会话，不是为了让新代码再产生它。
_LEGACY_OPENINGS = frozenset({
    "我们从“理解问题”开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。",
})


def _opening_pending(session: AdvancedPracticeSession) -> bool:
    """这次会话是不是还在等教练生成开场（前端据此决定要不要发那一轮请求）。

    判据：学生还没说过话，且助手那侧没有说过开场以外的话。用服务端自己种的文案做
    精确比对，前端就不需要知道那句话是什么 —— 否则又是两处会各自漂移的字面量。
    """
    seed = _welcome_message(session.task_snapshot).get("text")
    for message in session.messages or []:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        # 学生说过话就说明对话已经开起来了；助手说过别的话就说明开场已经生成过。
        if message.get("role") == "user" or (text != seed and text not in _LEGACY_OPENINGS):
            return False
    return True


def session_phase_list(session: Any) -> list[dict[str, str]]:
    """下发给前端的阶段列表：id / label / hint / status。

    前端以前自己抄了一份 6 阶段（含文案），于是服务端一直在送 `current_phase_label`
    而它丢掉不用、自己再算一遍 —— 两处各写各的，迟早对不上。现在阶段列表由服务端
    出，前端只渲染。
    """
    phases = session_phases(session)
    completed = set(_clean_phases(getattr(session, "completed_phases", None), phases))
    current = getattr(session, "current_phase", "") or ""
    result = []
    for phase_id, label, hint in phases:
        if phase_id in completed:
            status = "completed"
        elif phase_id == current:
            status = "current"
        else:
            status = "pending"
        result.append({"id": phase_id, "label": label, "hint": hint, "status": status})
    return result


def _serialize(session: AdvancedPracticeSession) -> dict:
    phases = session_phases(session)
    labels = {phase_id: label for phase_id, label, _ in phases}
    return {
        "session_id": session.session_key,
        "task_id": session.task_key,
        "path_id": session.path_id,
        "node_id": session.node_id,
        "status": session.status,
        "current_phase": session.current_phase,
        "current_phase_label": labels.get(session.current_phase, phases[0][1]),
        "completed_phase_ids": session.completed_phases or [],
        # 阶段列表与交付物勾选状态都从这里下发，前端不再自己定义阶段词汇。
        "phases": session_phase_list(session),
        # 这一列是后加的：库里已存在的行是 NULL，取回来就是 None。用 getattr 是因为
        # 测试里的会话替身往往没有这个字段，而缺字段不该让整个响应拼不出来。
        "deliverable_state": getattr(session, "deliverable_state", None) or {},
        "messages": session.messages or [],
        # 前端据此决定要不要让教练生成开场（见 _opening_pending）。种下的那句开场
        # 是同步的、通用的；教练那份是流式的、读得到任务的。
        "opening_pending": _opening_pending(session),
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
            snapshot = _task_snapshot(task)
            try:
                session = await AdvancedPracticeSession.create(
                    user_id=user_id,
                    session_key=uuid.uuid4().hex,
                    task_key=task_key,
                    path_id=path_id,
                    node_id=node_id,
                    task_snapshot=snapshot,
                    status="active",
                    # 首个阶段按任务类型取：项目实训的第一阶段是"拆解需求"，不是
                    # "理解问题"。写死 "understand" 会让新会话一开局就带着一个不属于
                    # 自己词汇表的 current_phase，而它会被 clamp 悄悄换掉。
                    current_phase=snapshot_phases(snapshot)[0][0],
                    completed_phases=[],
                    messages=[_welcome_message(snapshot)],
                    deliverable_state={},
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
        deliverable_state: Any = None,
    ) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        if session.status == "completed":
            return _serialize(session)
        phases = session_phases(session)
        # `completed_phase_ids` 只保留在签名里兼容旧客户端：**不采信**。进度唯一的
        # 来源是流式回复里的 `[[PHASE:done]]` 标记（见 `record_phase_markers`）。
        completed = _clean_phases(session.completed_phases, phases)
        session.status = "active"
        session.current_phase = clamp_current_phase(current_phase, completed, phases)
        session.completed_phases = completed
        session.messages = _clean_messages(messages)
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.deliverable_state = _clean_deliverable_state(deliverable_state, session.task_snapshot)
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
        phases = session_phases(session)
        completed, current = advance_phase_state(
            session.completed_phases,
            session.current_phase,
            markers,
            phases,
        )
        if completed == _clean_phases(session.completed_phases, phases) and current == session.current_phase:
            return {}
        session.completed_phases = completed
        session.current_phase = current
        await session.save(update_fields=["completed_phases", "current_phase", "updated_at"])
        return {
            "current_phase": current,
            "current_phase_label": {pid: label for pid, label, _ in phases}.get(current, ""),
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
        deliverable_state: Any = None,
    ) -> dict:
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        if session.status == "completed":
            return _serialize(session)

        normalized_messages = _clean_messages(messages)
        phases = session_phases(session)
        # 判分用的阶段进度取服务端账本，不取本次请求 —— 这里的 phase_score 占 40 分，
        # 采信客户端等于把分数交给提交方自己填。
        completed = _clean_phases(session.completed_phases, phases)
        submission = _clip_text(final_submission, 6000)
        if not submission:
            submission = next((item["text"] for item in reversed(normalized_messages) if item["role"] == "user"), "")
        evaluation = AdvancedPracticeService._evaluate(
            session.task_snapshot or {},
            normalized_messages,
            completed,
            submission,
            phases,
        )
        session.status = "completed"
        session.current_phase = clamp_current_phase(current_phase, completed, phases)
        session.completed_phases = completed
        session.messages = normalized_messages
        session.confirmed_facts = _clean_list(confirmed_facts)
        session.assumptions = _clean_list(assumptions)
        session.deliverable_state = _clean_deliverable_state(deliverable_state, session.task_snapshot)
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
    def _evaluate(task: dict, messages: list[dict[str, str]], completed: list[str], submission: str, phases: Any) -> dict:
        user_text = "\n".join(item["text"] for item in messages if item["role"] == "user")
        corpus = f"{user_text}\n{submission}"
        user_count = sum(1 for item in messages if item["role"] == "user")
        # 分母是这套词汇的阶段数。三类任务都是 4 个，所以每完成一个阶段的价值一致；
        # 老会话（无 kind）走通用 6 阶段，分母仍是 6 —— 行为与改动前相同。
        phase_score = round(len(set(completed)) / len(phases) * 40)
        pending_labels = [label for phase_id, label, _ in phases if phase_id not in set(completed)]
        next_pending_label = pending_labels[0] if pending_labels else ""
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
        if len(completed) < len(phases):
            next_steps.append(f"补齐尚未完成的阶段，下一个是「{next_pending_label}」")
        if not evidence_score:
            next_steps.append("补充一条具体材料、数据或日志作为依据")
        if not validation_score:
            next_steps.append("写清楚如何测试结果，以及什么现象算有效")
        if not next_steps:
            next_steps.append("把本次方案整理成可复查的项目记录")

        criteria = [
            # 四条维度标签本身不动（它们描述提交质量，且判分提示词按标签逐字匹配），
            # 但第一条问的是"有没有走完第一个阶段"，那要看这套词汇的首个阶段 id。
            {"label": "问题理解", "passed": phases[0][0] in completed},
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
