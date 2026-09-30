"""进阶学习实践会话：持久化对话状态。

**这个模块只管账本**：谁跟哪个任务聊过、聊了什么、开场生成没有。

以前这里还有两套东西 —— 阶段推进（六阶段/按任务类型四阶段 + `[[PHASE:done]]` 标记）
和提交判分（确定性基线 + 智能体复核）。它们已经删掉，理由不是"多余"，而是**有害**：

1. **没有任何界面在读它们。** 前端的实践对话页只读 `messages` / `opening_pending` /
   `status`，阶段列表、交付物勾选、提交评价一个都不渲染 —— 提交入口早就没了。
2. **它们会反过来污染对话。** 阶段文案随任务快照存进会话，而历史消息又原样回放给
   模型，于是教练一直追一个**已经不存在的议程**：学生问"看看我的代码"，它回"我们先
   完成「定义交付」这一步"。删掉阶段机不会自动清掉那些历史措辞（它们在 chat_history
   里），但至少不再有新的话术被生产出来。
3. **判分口径是死代码里最贵的那种。** 一条同时含「依据/验证/方案」的消息就能到 60 分
   通过线 —— 它量的不是方案好坏，是有没有出现这几个词。留着它只会让人以为这里有评价。

数据库那几列（`current_phase` / `completed_phases` / `deliverable_state` /
`final_submission` / `evaluation`）**故意不动**：`completed_phases` 是 `NOT NULL` 且
没有默认值，从 model 里拿掉就会让 INSERT 直接报错，而删列必须先 `MODIFY ... NULL`
再 `DROP`、和代码发布错开。多几列没人读的空列，比一次要卡发布的 schema 变更便宜。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from tortoise.exceptions import IntegrityError

from backend.src.models.advanced_practice_model import AdvancedPracticeSession
from backend.src.models.path_model import LearningPath, PathNode

logger = logging.getLogger(__name__)

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


def practice_record_text(session: Any) -> str:
    """把服务端手里的会话记录拼成"本次对话总结"的输入。

    **不取客户端传来的文本**：那等于让调用方自己描述"我刚才学了什么"，总结就变成给
    自己的作文打分。消息在库里有权威版本，用它。
    """
    snapshot = getattr(session, "task_snapshot", None)
    if not isinstance(snapshot, dict):
        snapshot = {}
    lines = [f"任务：{_clip_text(snapshot.get('title'), 120) or '实践任务'}"]
    transcript = _transcript_text(getattr(session, "messages", None))
    if transcript:
        lines.append("对话记录：")
        lines.append(transcript)
    return "\n".join(lines)


def _transcript_text(messages: Any, *, limit: int = 20, item_limit: int = 260) -> str:
    """把对话记录拼成给模型看的一段文本，跳过坏行和空行。"""
    lines = [
        f"{'学生' if item.get('role') == 'user' else '教练'}：{_clip_text(item.get('text'), item_limit)}"
        for item in (messages if isinstance(messages, list) else [])[-limit:]
        if isinstance(item, dict) and _clip_text(item.get("text"), item_limit)
    ]
    return "\n".join(lines)


def _task_snapshot(task: Any) -> dict:
    """会话自己那份任务快照。

    只留**教练读得到的那几样**（见 `classroom_chat._render_task_block`）。以前还存
    `kind` / `support_level` / `stages`，那是给阶段机选词汇、定提示强度用的；阶段机
    没了，它们就只剩"看起来很像重要状态"的副作用 —— 谁读到都会以为会话记得自己的
    类型，从而去猜一套不存在的流程。不存了。
    """
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


def _welcome_message(snapshot: Any = None) -> dict[str, str]:
    """新建会话时种下的开场。

    这是学生进页面**立刻**能看到的那一句（教练那份开场是流式的，要等），所以它必须
    点出任务是什么：以前这里是一句跟任务无关的通用话术，学生看完不知道要回答什么，
    只能回一句"你在说啥"，要等第二轮模型才把任务讲清楚。

    以前还要在前面挂一句"我们从「XX」开始"（阶段名取该会话那套词汇的首个阶段）。
    阶段没了，那句话就成了**凭空出现的术语** —— 学生看到的第一个词是个他从没听过的
    阶段名，而任务说明在后面。直接讲任务。
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    title = _clip_text(snapshot.get("title"), 120)
    if title:
        text = (
            f"这个任务要你产出的是「{title}」。"
            "先说说它要解决的核心问题，以及你准备依据哪些信息判断。"
        )
    else:
        text = "先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。"
    return {"role": "assistant", "text": text}


# 改动之前种下的那两句开场。留着它们是为了**认得老会话**，不是为了让新代码再产生
# 它们：`_opening_pending` 要靠它判断"这个会话还没真正开过头"。
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


def _serialize(session: AdvancedPracticeSession) -> dict:
    return {
        "session_id": session.session_key,
        "task_id": session.task_key,
        "path_id": session.path_id,
        "node_id": session.node_id,
        "status": session.status,
        "messages": session.messages or [],
        # 前端据此决定要不要让教练生成开场（见 _opening_pending）。种下的那句开场
        # 是同步的、通用的；教练那份是流式的、读得到任务的。
        "opening_pending": _opening_pending(session),
        "confirmed_facts": session.confirmed_facts or [],
        "assumptions": session.assumptions or [],
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
                    messages=[_welcome_message(snapshot)],
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

        # 打开任务即恢复会话：`paused` 和 `completed` 都算。
        #
        # `completed` 以前是"已提交、判过分"，不复活是为了别让改过的对话和定稿的分数对不上。
        # 现在前端已经没有提交入口了（阶段机和判分整个删掉，只留会话账本），
        # 于是 `completed` 变成一个**进去不、也出不来**的死状态：页面照样把旧对话读出来显示，
        # 可之后每一次发言都被 `_practice_session_blocked` 顶回来"会话不存在、无权访问或已经完成"，
        # 而界面上再没有任何按钮能解除它。老会话（提交功能还在时留下的那批）全是这样。
        # 判分没了，这个保护就没有要保护的东西了，恢复它。
        if session.status != "active":
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
        messages: Any,
        confirmed_facts: Any = None,
        assumptions: Any = None,
    ) -> dict:
        """保存对话状态。**只保存，不参与任何判断。**

        `messages` 由客户端提交 —— 这是这里唯一采信客户端的地方，因为消息流本来就
        由前端驱动，服务端只负责存储和回放。它不换算成任何进度或分数，所以"客户端
        说了算"在这里没有代价（以前不是：`completed_phase_ids` 也是客户端传的，而它
        直接进分数）。

        `confirmed_facts` / `assumptions` 已经没有任何读者（既不进提示词也不进界面），
        留着是为了不改库表；不要往它们里面加新语义。
        """
        session = await AdvancedPracticeSession.filter(user_id=user_id, session_key=session_key).first()
        if not session:
            raise ValueError("巩固会话不存在")
        session.status = "active"
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
