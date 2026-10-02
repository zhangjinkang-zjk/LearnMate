"""学习统计服务 — 心跳、汇总、资源已读"""

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone

from tortoise.expressions import Q

from backend.src.models.study_model import StudySession, ResourceReadStatus, ResourceCollection, LearningEvent
from backend.src.models.exam_model import KnowledgeMastery, ExamRecord
from backend.src.models.resource_model import GeneratedResource
from backend.src.models.path_model import LearningPath, PathNode, UserPathProgress
from backend.src.service.portrait.service import (
    PortraitChatHistory_Service,
    PortraitRadarService,
    active_day,
    build_learning_guidance,
    build_learning_guidance_from_radar,
    record_learning_event,
)
from backend.src.service.notification.service import check_and_create_weekly_report
from backend.src.service.path.helpers import reconcile_completed_prerequisites
from backend.src.service.path.difficulty import (
    clamp_difficulty_score,
    derive_difficulty_score,
    normalize_relative_difficulty,
)
from backend.src.service.resource.matching import build_resource_difficulty_match

logger = logging.getLogger(__name__)


def _node_title(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("title") or node.get("topic") or "").strip()


def _non_negative_int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


async def _path_last_active_map(user_id: int) -> dict[int, str]:
    """每条路径最近一次动过是哪天（UTC 日，和「本周来了 N 天」共用同一个 `active_day`）。

    **取的是 `user_path_progress` 的 `started_at` / `completed_at`，不是
    `learning_events.path_id`。** 后者是稀疏的：`mark_read` 记 `resource_read` 时压根不传
    `path_id`，`assessment` 也显式传 `None` —— 只看事件的话，"这条路径我一直在读资料、
    只是还没做测验"会被显示成从没学过，正好把「哪条路径在养老」答反。

    `started_at` 在节点被打开时写（`helpers.py` 绑定资源、`service.py` 启动节点两处），
    `completed_at` 在通过时写，两者取最大就是"最后一次在这条路径上动过"。

    一次查询取回全部路径，不是每条路径查一遍。
    """
    rows = await UserPathProgress.filter(user_id=user_id).values_list("path_id", "started_at", "completed_at")
    latest: dict[int, date] = {}
    for path_id, started_at, completed_at in rows:
        for value in (started_at, completed_at):
            day = active_day(value)
            if day and (path_id not in latest or day > latest[path_id]):
                latest[path_id] = day
    return {path_id: str(day) for path_id, day in latest.items()}


async def _build_path_summaries(
    user_id: int,
    path_stats: dict,
    *,
    current_path: dict | None,
    last_active: dict[int, str] | None = None,
) -> list[dict]:
    """右栏「我的学习方向」：每条路径一行 —— 名称、完成度、当前节点、节点状态序列。

    **当前路径之外的那几条，走一次 `get_current_path(user_id, path_id=…)`。** 路径读的
    唯一入口就是它（节点顺序、状态修复、资源绑定、测验进度都在里面），自己另写一套轻量
    查询等于把业务规则复制一份 —— 以后再改一处、漏一处。当前那条已经在 `get_overview`
    里取过了，直接复用，不重复取。

    只往外带页面要用的四样：名称、完成度、当前节点标题、按顺序的状态序列（画迷你轨道）。
    """
    from backend.src.service.path.service import PathService

    current_path_id = (current_path or {}).get("path_id")
    # 「上次学到哪天」由调用方一次取齐传进来，不在这里查 —— 它是一次真实查询，
    # 而这个函数在单元测试里是脱离数据库跑的（`tests/test_study_overview_focus.py`）。
    last_active = last_active or {}
    summaries: list[dict] = []
    for item in path_stats.get("paths", []):
        path_id = item.get("path_id")
        name = str(item.get("subject") or "").strip()
        if not path_id or not name:
            continue
        if path_id == current_path_id:
            nodes = (current_path or {}).get("nodes", [])
        else:
            other = await PathService.get_current_path(user_id, path_id)
            nodes = (other or {}).get("nodes", [])
        progress = item.get("progress") or {}
        current_node = next(
            (node for node in nodes if node.get("status") in ("in_progress", "unlocked")),
            None,
        )
        summaries.append({
            "id": path_id,
            "name": name,
            "is_current": path_id == current_path_id,
            "progress": _non_negative_int(progress.get("percentage")),
            "completed_nodes": _non_negative_int(progress.get("completed_nodes")),
            "total_nodes": _non_negative_int(progress.get("total_nodes")) or len(nodes),
            "current_node": (
                {"id": current_node.get("id"), "title": _node_title(current_node), "status": current_node.get("status") or ""}
                if current_node else None
            ),
            # 日期字符串或 null（null = 这条路径一个节点都没打开过）。给日期不给时间戳，
            # 理由同 `last_active_date`：库里是 naive 时间，序列化后浏览器按本地时区解析会偏。
            "last_active_date": last_active.get(path_id),
            # 整条路径的节点，按顺序。**给 id 不是给状态字符串** —— 页面要把每一站画成
            # 可点的站点，点一下进那个节点的学习界面；只有状态的话这个交互做不出来。
            # 标题顺带带上，鼠标停在站点上就能显示学的是什么，不用回查。
            "nodes": [
                {
                    "id": node.get("id"),
                    "title": _node_title(node),
                    "status": node.get("status") or "locked",
                }
                for node in nodes
            ],
        })
    # 当前那条排最前，其余按完成度降序 —— 页面右栏从上往下就是"先看这条、再看那条"。
    summaries.sort(key=lambda item: (not item["is_current"], -item["progress"]))
    return summaries


def _build_recommendation_reason(
    weak_tag: str,
    weak_accuracy: object,
    node_title: str,
    *,
    completed_nodes: int,
    total_nodes: int,
    node_tags=(),
) -> str:
    """主行动卡的「为什么是它」。**必须引用可证实的事实**，不能是"AI 智能推荐"。

    三条分支按证据强弱排：薄弱知识点**正好在这张卡指向的节点里**就用它的正确率；否则说清
    "它是路径上的下一个"并带上已完成进度；连节点都没有才承认判断不了。

    原来只有第 1、3 两条，于是**已经把 11/13 个节点学完的账号**看到的理由是
    「完成一次学习节点后，系统才能给出更精确的下一步判断」—— 一句和学生现状直接矛盾的话
    （实测于 learner_llm_agent，2026-10-01）。推荐理由是这一页的命门，自相矛盾比空着更糟。

    **第 1 条带 `node_tags` 这个门槛，不是随手加的。** 它原来无条件优先，但
    `target_id` 永远是 `current_node`（路径上的下一站），跟薄弱点所在的章节没关系 ——
    于是卡片会写着「向量检索当前正确率约 44%，先补强该知识点」，按钮却带你去
    「Agentic RAG 的迭代与自我纠正」。**理由说去 A、按钮带你去 B**，是这一页最不该出的错。
    现在只有那个薄弱点确实属于这一站时才这么说，否则老实讲路径进度。

    薄弱点本身不会因此丢掉：它一直有自己的入口 —— 卡片右下角那条
    「这章有 N 个知识点该复习」，`blind_spots[0]` 带着 `path_id` / `node_id`，
    落点正是覆盖该知识点的章节。所以这里收回来的不是信息，是一句不成立的因果。
    """
    tag = str(weak_tag or "").strip()
    if tag and _knowledge_tag_key(tag) in {_knowledge_tag_key(item) for item in node_tags}:
        accuracy = _non_negative_int(weak_accuracy)
        if accuracy:
            return f"{tag} 当前正确率约 {accuracy}%，先补强该知识点能减少后续反复。"
        return f"{tag} 是你目前最薄弱的知识点，先补强它能减少后续反复。"
    if str(node_title or "").strip():
        if total_nodes > 0:
            return f"路径上已完成 {completed_nodes} / {total_nodes} 个节点，这是下一个待学节点。"
        return "这是你的学习路径上的下一个待学节点。"
    return "完成一次学习节点后，系统才能给出更精确的下一步判断。"


def _node_knowledge_tags(node: dict) -> list[str]:
    """节点的知识点名。字符串和字符串数组之外一律当没有 —— 别在裸串上按长度数。
    """
    tags = node.get("knowledge_tags")
    if not isinstance(tags, list):
        return []
    # 只认字符串：`str(None)` 会得到 "None" 这么个知识点，`str(3)` 更离谱。
    # 列里本来存的就是 JSON 字符串数组，出现别的类型是脏数据，丢掉而不是硬转。
    return [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]


def _build_focus_target(node: dict | None) -> dict | None:
    """把「当前该学哪个节点」压成主行动卡要用的元信息。

    **这里一个数都不新算**：知识点数来自节点的 `knowledge_tags`，资料数和任务进度来自
    `get_current_path` 已经算好的 `garden_progress`。概览页以前把整份节点丢掉、只留一个
    标题，于是主按钮上写不出"点下去要花什么代价"——学生只能盲点。

    没有 `garden_progress` 时给 0，**不编一个预计时长**：系统里没有任何时长预估的来源，
    编一个就是伪造精度（和已经删掉的 `masteryScore - 60` 同类）。
    """
    if not isinstance(node, dict):
        return None
    title = _node_title(node)
    if not title:
        return None
    tags = _node_knowledge_tags(node)
    progress = node.get("garden_progress") if isinstance(node.get("garden_progress"), dict) else {}
    return {
        "id": node.get("id"),
        "title": title,
        "action_label": str(node.get("action_label") or "开始学习"),
        "knowledge_points": len(tags),
        # 光有「3 个知识点」这种计数，卡片上就只有数字、没有内容 —— 学生看不出这一章
        # 到底要学什么。标签名本来就是现成的，带上。
        # **纯增量**：`knowledge_points` 那个计数一个字没改，老的消费方按原样读。
        "knowledge_tags": tags,
        "resources": _non_negative_int(progress.get("resource_total")),
        "resources_done": _non_negative_int(progress.get("resource_completed")),
        # **这里有过 `tasks_done` / `tasks_total`，已删除。** 它们透出的是
        # `path/service.py` 里一对**派生计数**：`total = 资料数 + (有测验 ? 1 : 0)`，
        # `completed = 已读资料数 + (测验全答完 ? 1 : 0)`。也就是说「任务 2 / 5」
        # 只是「资料 1 / 4」+「测验 1 / 1」的和，不是学生能去做的一件独立的事 ——
        # 概览页照着它渲染出第三行「任务」，读的人找不到那是什么。
        # （`garden_progress` 里那对字段本身**没删也不能删**：`StudyGarden.vue` /
        #  `TreeReviewScene.vue` 拿它挑树的生长阶段。是不能把它当"要做的事"透出来。）
        # 测验进度与本章累计阅读时长。「接着上次」那张卡要说清"还剩什么"，
        # 就得知道测验做没做完；时长来自 `ResourceReadStatus.duration_seconds`，
        # **是真的**（基础讲解页在文档可见时上报秒数），不是那个恒为 0 的 heartbeat。
        "quiz_total": _non_negative_int(progress.get("quiz_total")),
        "quiz_answered": _non_negative_int(progress.get("quiz_answered")),
        "time_spent_seconds": _non_negative_int(node.get("time_spent")),
    }


def _build_path_difficulty_trend(nodes: list[dict]) -> list[dict]:
    """为当前路径生成难度折线数据；高度只表达路径内难度，不混入完成状态。"""
    ordered_nodes = sorted(
        (node for node in nodes if _node_title(node)),
        key=lambda item: item.get("order_index", 0),
    )
    raw_scores: list[float] = []
    for index, node in enumerate(ordered_nodes, 1):
        if index == 1:
            score = 1.0
        else:
            spec = node.get("teaching_spec") if isinstance(node.get("teaching_spec"), dict) else {}
            tags = node.get("knowledge_tags") if isinstance(node.get("knowledge_tags"), list) else []
            prerequisites = node.get("prerequisites") if isinstance(node.get("prerequisites"), list) else []
            score = clamp_difficulty_score(node.get("difficulty_score"))
            if score is None:
                score = derive_difficulty_score(
                    order_index=index,
                    total_nodes=len(ordered_nodes),
                    cognitive_level=str(spec.get("cognitive_level") or ""),
                    module=str(spec.get("module") or ""),
                    key_points_count=len(spec.get("key_points") or tags),
                    prerequisite_count=len(prerequisites),
                )
        raw_scores.append(score)

    relative_scores = normalize_relative_difficulty(raw_scores)
    return [
        {
            "id": node.get("id"),
            "order_index": node.get("order_index", index),
            "title": _node_title(node),
            "status": node.get("status") or "",
            "difficulty_score": round(raw_scores[index], 2),
            "relative_difficulty": relative_scores[index],
        }
        for index, node in enumerate(ordered_nodes)
    ]


# 活跃度的查询边界。「本周」是报给学生的那个数（见 _week_start），「30 天」是查询边界 ——
# 超出边界的记录连 last_active_date 都不参与，于是它的 None 有确切含义：这个人已经
# 30 天没来过了，而不是"最后一次来是三个月前"。
_ACTIVITY_WINDOW_DAYS = 30

# 趋势图取几周。6 是柱状图还读得出走势的下限：4 根以下看不出"变多还是变少"，
# 但也别贪多 —— 这套系统的数据本身只有几周，画 12 周会有半张图是空的，
# 看着像坏了，而不是像"你才刚开始"。
_TREND_WEEKS = 6

# `learning_events` 的**取数**窗口，比 `_ACTIVITY_WINDOW_DAYS` 宽：趋势图最早那一周的
# 周一最多在 7 * 6 = 42 天前，只取 30 天会少半根柱子。多取一段只多几行，一条查询。
# **它不替代 `_ACTIVITY_WINDOW_DAYS`** —— 那个 30 天仍然定义 `last_active_date` 的语义
# （None = 30 天内没来过）。两个窗口各管各的：一个管"取多少行进来"，一个管"哪些行算数"。
_EVENT_QUERY_DAYS = _TREND_WEEKS * 7 + 7


def _week_start(today: date) -> date:
    """本周第一天，周一。

    **不数「近 7 天」那种滚动窗口**：滚动窗口的起点每天都在动，学生没有哪一天是对齐它的，
    「近 7 天来了 4 天」既不是"这周"也不是"上周"，读完不知道该干什么。日历周是学生真的会
    用来给自己记账的单位 ——「这周来了 3 天」是能对上计划的。
    """
    return today - timedelta(days=today.weekday())


def _metadata_duration(metadata) -> int:
    """从事件的 `metadata` 里取 `duration_seconds`。

    `metadata` 是 JSON **文本**列，不是 dict —— 脏数据（坏 JSON、不是对象、值是字符串）
    一律当 0，不该让整个总览接口 500。
    """
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            return 0
    if not isinstance(metadata, dict):
        return 0
    return _non_negative_int(metadata.get("duration_seconds"))


def _read_seconds_in_week(events, *, today: date) -> int:
    """本周花在**读资料**上的秒数。`events` 是 `(created_at, event_type, metadata)` 三元组。

    这是系统里**唯一**带真实时间戳的时长。别拿 `StudySession.total_seconds` 来回答这个问题：
    它唯一的写入方是 `StudyService.heartbeat`，而前端从来没调用过 `/study/heartbeat`，
    所以那个数结构性恒为 0（见 `get_stats` 里的注释），页面拿它渲染出的"学习 0 小时"是错的。

    基础讲解页在文档可见时每 30 秒上报一次**距上次上报的增量**（`FundamentalsPage.vue`
    的 `reportReadDuration`），所以这里累加增量不会重复计数。

    口径上是「读了多久」，不是「学了多久」：测验、课堂、普通对话都没有记时。只做测验不读
    资料的人这里就是 0，页面写成"学习了 0 小时"会和同一行的"本周来了 N 天"直接打架。
    """
    week_start = _week_start(today)
    total = 0
    for created_at, event_type, metadata in events:
        if event_type != "resource_read":
            continue
        day = active_day(created_at)
        # 上界同样要挡：时钟偏移混进来的未来时间不算进本周。
        if day is None or day < week_start or day > today:
            continue
        total += _metadata_duration(metadata)
    return total


def _summarize_week_work(exam_records, events, *, today: date) -> dict:
    """本周**做了多少**：答了几题、通过了几次节点测验。

    两张表在 `get_stats` 里早就整个读进内存了（`exam_records` 全表、`learning_events`
    近 30 天带 `metadata`），所以这里一个额外查询都不发。

    收的是**全表**，不是调用方筛好的：`is_correct` 非空这个条件由这里自己判 —— 它是
    "答了 N 题"这个数的定义的一部分（简答题没判分时 `is_correct` 是 None，算进去会和
    正确率的分母对不上），留在调用方就迟早有一条路径忘了筛。

    `quizzes_passed_this_week` 数的是 `node_quiz` 事件里 `metadata.passed` 为真的次数。
    交卷、诊断这些事件不参与 —— 它们不是"过了一关"。
    """
    week_start = _week_start(today)

    def in_week(value) -> bool:
        day = active_day(value)
        # 上界要挡：时钟偏移混进来的未来时间不算进本周（同 `_read_seconds_in_week`）。
        return day is not None and week_start <= day <= today

    questions = sum(
        1 for record in exam_records
        if record.is_correct is not None and in_week(record.created_at)
    )
    passed = 0
    for created_at, event_type, metadata in events:
        if event_type != "node_quiz" or not in_week(created_at):
            continue
        try:
            payload = json.loads(metadata) if metadata else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict) and payload.get("passed"):
            passed += 1
    return {"questions_this_week": questions, "quizzes_passed_this_week": passed}


def _summarize_week_trend(timestamps, *, today: date) -> list[dict]:
    """最近 `_TREND_WEEKS` 个日历周，每周**有几天在学习**。返回从早到晚的一串桶。

    数的是"天数"而不是"答了几题"或"学完几个节点"，三个原因：

    1. **只有它有可信的时间戳。** 节点完成时间（`user_path_progress.completed_at`）不能用来
       画走势 —— `reconcile_completed_prerequisites` 会给补记的记录写上 `datetime.now()`，
       于是几个月前学完的节点会被盖成"今天"，图上凭空多出一根高柱。而
       `learning_events`（交卷 / 节点小测 / 资料读完 / 课堂对话）和 `ExamRecord` 是当场写的。
    2. **任何形式的学都算，不只是答题。** 只读资料、只在课堂上提问的人，用"答题量"画出来是
       一片空白，那是在说他没学 —— 假话。天数只要那天动过就算，和上面「本周来了几天」同源。
    3. **值域固定 0-7**，不会被某一周突击刷出来的量压扁其余几周。

    口径与 `_summarize_learning_activity` 完全一致（同一批时间戳、同一个 `active_day`、
    同一个周一为界的 `_week_start`），所以**最右边那根柱子的高度 == 上面那排七格里点亮的
    格数**。两个地方对同一周给不出不同的答案。

    没有来的那几周给 0 而不是跳过：那几根空柱正是这张图要说的事（哪一周断了），
    缺桶会让横轴撒谎 —— 相邻两根柱子看起来挨着，中间其实隔了好几周。
    """
    days = {
        day for day in (active_day(ts) for ts in timestamps)
        # 上界要挡：时钟偏移混进来的未来日期不算（同 `_read_seconds_in_week`）。
        if day and day <= today
    }
    this_week = _week_start(today)
    buckets = {
        str(this_week - timedelta(weeks=offset)): 0
        for offset in range(_TREND_WEEKS - 1, -1, -1)
    }
    for day in days:
        key = str(day - timedelta(days=day.weekday()))
        if key in buckets:
            buckets[key] += 1
    # 键是 ISO 日期，字典序就是时间序；仍然显式排序，别去依赖 dict 的插入顺序。
    return [{"week_start": key, "active_days": count} for key, count in sorted(buckets.items())]


def _summarize_learning_activity(timestamps, *, today: date) -> dict:
    """把时间戳归到天，给出「本周活跃了几天」和「最后一次学习是哪天」。

    口径与雷达的「坚持」维度同源（同一个 active_day、同样是答题记录与 learning_events
    的**并集**）：只数答题会把"看资料 / 做节点测验 / 课堂对话但没考试"的人算成没来过。

    last_active_date 是**日期**不是时间戳，这是刻意的：库里存的是 naive 时间，按时间戳
    序列化会不带偏移量，浏览器 `new Date()` 按本地时区解析会比 UTC 实际晚一个时区；只回
    一个日期就不存在这个陷阱，而页面要的也只是"几天前"。
    """
    days = {day for day in (active_day(ts) for ts in timestamps) if day}
    window_start = today - timedelta(days=_ACTIVITY_WINDOW_DAYS - 1)
    recent = [day for day in days if day >= window_start]
    week_start = _week_start(today)
    base = {
        "active_days_this_week": 0,
        "week_start_date": str(week_start),
        "last_active_date": None,
        "window_days": _ACTIVITY_WINDOW_DAYS,
        # 本周七格。**连着七天一起给，不给"活跃的那几天"** —— 页面要画的是
        # 周一→周日的日历，缺掉的那几天正是它要说的信息（哪一天断了）。
        # 后半周还没到的日子也在里面，`active` 为 false，页面照画。
        "weekly_days": [
            {
                "date": str(day),
                "active": day in days and day <= today,
                "is_today": day == today,
            }
            for day in (week_start + timedelta(days=offset) for offset in range(7))
        ],
    }
    if not recent:
        return base
    # 上界写 `<= today` 是防时钟偏移带来的未来日期混进来 —— 那会把本周的天数算超。
    return {
        **base,
        "active_days_this_week": sum(1 for day in recent if week_start <= day <= today),
        "last_active_date": str(max(recent)),
    }


class StudyService:

    @staticmethod
    async def get_overview(user_id: int) -> dict:
        """返回学习概览所需的结构化数据，页面只消费这一份快照。"""
        from backend.src.service.path.service import PathService

        portrait_result = await PortraitChatHistory_Service.read_portrait(user_id)
        portrait = portrait_result[0] if isinstance(portrait_result, tuple) else portrait_result
        portrait = portrait or {}
        traits = portrait.get("traits") if isinstance(portrait.get("traits"), dict) else {}
        onboarding = traits.get("onboarding") if isinstance(traits.get("onboarding"), dict) else {}

        current_path = await PathService.get_current_path(user_id)
        path_stats = await StudyService.get_path_stats(user_id)
        stats = await StudyService.get_stats(user_id)
        radar = await PortraitRadarService.get(user_id)
        mastery_records = await KnowledgeMastery.filter(user_id=user_id).all()

        subjects = []
        for item in path_stats.get("paths", []):
            progress = item.get("progress", {})
            study_time = item.get("study_time", {})
            subject_name = str(item.get("subject") or "").strip()
            if not subject_name:
                continue
            subjects.append({
                "id": item.get("path_id"),
                "name": subject_name,
                "progress": progress.get("percentage", 0),
                "completed_nodes": progress.get("completed_nodes", 0),
                "total_nodes": progress.get("total_nodes", 0),
                "study_seconds": study_time.get("total_seconds", 0),
            })

        nodes = (current_path or {}).get("nodes", [])
        difficulty_trend = _build_path_difficulty_trend(nodes)
        goals = []
        for node in nodes[:6]:
            title = _node_title(node)
            if not title:
                continue
            status = node.get("status") or ""
            goals.append({
                "id": node.get("id"),
                "title": title,
                "status": status,
                "progress": 100 if status == "completed" else 0,
            })
        next_content = []
        for node in nodes:
            title = _node_title(node)
            if not title or node.get("status") not in ("in_progress", "unlocked"):
                continue
            next_content.append({
                "id": node.get("id"),
                "title": title,
                "status": node.get("status") or "",
            })
            if len(next_content) >= 3:
                break

        weak_points = []
        seen_tags = set()
        for point in stats.get("weak_points", []):
            if not isinstance(point, dict):
                continue
            tag = str(point.get("tag") or point.get("knowledge_tag") or "").strip()
            if not tag or tag in seen_tags:
                continue
            try:
                accuracy_value = float(point.get("accuracy"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(accuracy_value):
                continue
            if 0 <= accuracy_value <= 1:
                accuracy = round(accuracy_value * 100)
            elif 0 <= accuracy_value <= 100:
                accuracy = round(accuracy_value)
            else:
                continue
            seen_tags.add(tag)
            weak_points.append({
                "tag": tag,
                "accuracy": accuracy,
                "level": point.get("level") or "",
            })
        weak_points = weak_points[:6]

        mastery_values = []
        mastery_bars = []
        for record in mastery_records:
            attempts = max(record.total_attempts or 0, 0)
            if attempts <= 0:
                continue
            score = round((record.correct_count or 0) / attempts * 100)
            mastery_values.append(score)
            mastery_bars.append({
                "label": record.knowledge_tag,
                "score": score,
                "type": "knowledge",
                "attempts": attempts,
                "correct_count": record.correct_count or 0,
            })
        mastery_bars.sort(key=lambda item: (-item["attempts"], item["score"]))
        mastery_bars = mastery_bars[:8]
        if not mastery_bars and radar:
            mastery_bars = [
                {"label": item.get("label", item.get("key", "能力")), "score": item.get("score", 0), "type": "ability"}
                for item in radar.get("dimensions", [])
            ]

        sessions = await StudySession.filter(user_id=user_id).all()
        today = date.today()
        history = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            seconds = sum(s.total_seconds or 0 for s in sessions if s.date == day)
            history.append({"date": str(day), "study_seconds": seconds})

        completed_nodes = sum(1 for node in nodes if node.get("status") == "completed")
        total_nodes = len(nodes)
        diagnosis = (current_path or {}).get("diagnosis") or {}
        exam_summary = stats.get("exam_summary") or {}
        answered_questions = exam_summary.get("completed_questions", 0)
        # 一题没答时给 None 而不是 0：`correct_rate` 在服务端是
        # `correct / max(completed, 1)`，没答过题的账号会拿到 0.0，直接渲染就是
        # 「正确率 0%」——把"还没测过"说成"全错"。
        correct_rate = exam_summary.get("correct_rate") if answered_questions else None
        diagnosis_score = diagnosis.get("latest_score")
        latest_score = round(sum(mastery_values) / len(mastery_values)) if mastery_values else (
            diagnosis_score if diagnosis_score is not None and answered_questions > 0 else None
        )
        if not mastery_values and latest_score is None and radar and radar.get("dimensions"):
            latest_score = round(sum(item.get("score", 0) for item in radar["dimensions"]) / len(radar["dimensions"]))
        resource_difficulty_match = build_resource_difficulty_match(nodes, latest_score)
        stage = "正在生成"
        if latest_score is not None:
            stage = "应用进阶期" if latest_score >= 85 else "基础巩固期" if latest_score >= 60 else "基础建立期"

        current_node = next((node for node in nodes if node.get("id") == (current_path or {}).get("current_node_id")), None)
        if not current_node:
            current_node = next((node for node in nodes if node.get("status") in ("in_progress", "unlocked")), None)
        weak_tag = weak_points[0]["tag"] if weak_points else ""
        weak_accuracy = weak_points[0].get("accuracy") if weak_points else None
        recommendation = {
            # judgement 和 reason 是同一类东西（都是要说给学生听的一句判断），所以
            # "有当前节点"这一档也要给，不能一没有薄弱点就退回"数据不足"。
            "judgement": (
                f"当前主要短板是 {weak_tag} 能力" if weak_tag
                else (f"已经完成 {completed_nodes} / {total_nodes} 个节点，继续往后学" if current_node else "当前还缺少足够练习数据")
            ),
            "action": current_node.get("title") if current_node else None,
            "reason": _build_recommendation_reason(
                weak_tag,
                weak_accuracy,
                current_node.get("title") if current_node else "",
                completed_nodes=completed_nodes,
                total_nodes=total_nodes,
                # 这一站的标签。理由里那句"先补强 X"只有 X 属于这一站时才成立 ——
                # 判据必须和 `target_id` 用的是同一个节点，所以在这里传进去。
                node_tags=_node_knowledge_tags(current_node) if current_node else (),
            ),
            "criteria": f"能够解释“{current_node.get('title')}”的关键方法，并通过节点测验。" if current_node else None,
            "target_id": current_node.get("id") if current_node else None,
            # `next_action` 这个键**一定存在**，没有当前节点时它的值是 None
            # （path/service.py 里 `next_action = None`），所以 `.get(k, {})` 的默认值
            # 永远不生效，会直接在 None 上再 .get 一次 —— 路径学完 / 没有已解锁节点时
            # 整个学习总览 500。默认值要用 `or {}` 兜。
            "action_type": ((current_path or {}).get("next_action") or {}).get("type") if current_path else None,
            "status": "ready" if current_node or weak_tag else "generating",
            # 推荐指向的那个节点本身（知识点数 / 资料数 / 任务进度）。
            # 这是**纯增量**：`action` / `reason` / `criteria` / `target_id` 一个没动，
            # 老的消费方按原样读不会受影响。
            "target": _build_focus_target(current_node),
        }
        summary_text = ""
        if latest_score is not None:
            summary_text = f"已记录 {len(mastery_values)} 个知识点的练习，综合掌握度为 {latest_score}%。"
            if weak_tag:
                summary_text += f" 当前优先关注“{weak_tag}”，先补强后再进入下一步。"
        elif stats.get("study_time", {}).get("total_seconds", 0) > 0:
            summary_text = "已有学习记录，完成练习后会形成更准确的掌握度总结。"

        return {
            "profile": {
                "identity": onboarding.get("identity", ""),
                "direction": onboarding.get("direction") or traits.get("learning_direction", ""),
                "goal": onboarding.get("goal") or portrait.get("learning_goal", ""),
                "learning_signals": traits.get("learning_signals", {}) if isinstance(traits.get("learning_signals"), dict) else {},
            },
            "path": {
                "id": (current_path or {}).get("path_id"),
                "progress": (current_path or {}).get("progress", 0),
                "completed_nodes": completed_nodes,
                "total_nodes": total_nodes,
                # 全部节点学完时 next_content 必然是空的 —— 那是正常终态，不是"还在生成"。
                # 前端以前只有"正在生成下一步学习内容…"这一个分支，学完的人会一直看它转。
                "completed": bool(total_nodes) and completed_nodes >= total_nodes,
                "difficulty_trend": difficulty_trend,
                "resource_difficulty_match": resource_difficulty_match,
            },
            "subjects": subjects,
            # 右栏「我的学习方向」：每条路径的当前节点 + 节点状态序列。
            # **纯增量** —— `subjects` 一个字没动，老的消费方按原样读。
            "paths": await _build_path_summaries(
                user_id,
                path_stats,
                current_path=current_path,
                last_active=await _path_last_active_map(user_id),
            ),
            "goals": goals,
            "next_content": next_content,
            "blind_spots": weak_points,
            "diagnosis": {
                "score": latest_score,
                "stage": stage,
                "answered": stats.get("exam_summary", {}).get("completed_questions", 0),
            },
            "mastery_bars": mastery_bars,
            "radar": radar or {"dimensions": []},
            "study_history": history,
            "summary": {
                "total_study_seconds": stats.get("study_time", {}).get("total_seconds", 0),
                "active_days": stats.get("study_time", {}).get("active_days", 0),
                "completed_nodes": completed_nodes,
                "total_nodes": total_nodes,
                "mastery_score": latest_score,
                # 0–1 的小数（和历史口径一致），一题没答过时是 None。页面拿它渲染
                # 「答题正确率 N%」；**这个数是真的**，不像 total_study_seconds。
                "correct_rate": correct_rate,
                "text": summary_text,
            },
            # 活跃度与 summary 平级，而不是塞进 summary 里：summary 那几个数是"学到什么程度"，
            # 这一项是"最近来没来"，两件事。summary.total_study_seconds 恒为 0 是真的 0
            # （见 get_stats 里的注释），所以页面上回答"多久没来"的只能是这一项。
            "activity": stats.get("activity") or {
                "active_days_this_week": 0,
                "read_seconds_this_week": 0,
                "questions_this_week": 0,
                "quizzes_passed_this_week": 0,
                "weekly_days": [],
                "week_trend": [],
                "week_start_date": None,
                "last_active_date": None,
                "window_days": _ACTIVITY_WINDOW_DAYS,
            },
            "recommendation": recommendation,
            # 资料库那一块的三个数。**纯转手，一个新数都不算**：`get_stats` 为了算
            # `open_rate` 早就把 `GeneratedResource` / `ResourceReadStatus` /
            # `ResourceCollection` 三张表整个读进内存了，这里只是把同一份结果透出去。
            # 页面以前一个字都没读它。
            "resources": stats.get("resources") or {
                "total": 0,
                "read_count": 0,
                "unread_count": 0,
                "collected_count": 0,
            },
        }

    @staticmethod
    async def heartbeat(user_id: int, path_id: int | None = None) -> dict:
        """前端每 30 秒调用一次，累计今日学习时长。path_id 可选，用于分路径统计"""
        today = date.today()
        try:
            session, _ = await StudySession.get_or_create(
                user_id=user_id, date=today,
                defaults={"total_seconds": 0, "last_heartbeat_at": datetime.now()},
            )
        except Exception:
            session = await StudySession.filter(user_id=user_id, date=today).first()
            if not session:
                raise
        session.total_seconds += 30
        session.last_heartbeat_at = datetime.now()
        if path_id is not None:
            session.path_id = path_id
        await session.save()
        return {"today_seconds": session.total_seconds}

    @staticmethod
    async def mark_read(user_id: int, resource_id: int, duration_seconds: int = 0) -> dict:
        """标记资源为已读，可选上报使用时长"""
        resource = await GeneratedResource.filter(
            Q(id=resource_id),
            Q(user_id=user_id) | Q(visibility="public"),
        ).first()
        if not resource:
            raise ValueError("资源不存在")
        status, created = await ResourceReadStatus.get_or_create(
            user_id=user_id, resource_id=resource_id,
            defaults={"is_read": True, "read_at": datetime.now(), "duration_seconds": max(duration_seconds, 0)},
        )
        if not created:
            if not status.is_read:
                status.is_read = True
                status.read_at = datetime.now()
            if duration_seconds > 0:
                status.duration_seconds += duration_seconds
            await status.save()
        # 首次打开或有实际阅读时长才记一次事件，避免页面轮询把画像事件刷爆。
        if created or duration_seconds >= 10:
            try:
                await record_learning_event(
                    user_id,
                    "resource_read",
                    evidence=f"阅读资源 {resource.topic or resource.id}",
                    metadata={"resource_id": resource.id, "duration_seconds": max(duration_seconds, 0)},
                )
            except Exception:
                logger.exception("资源学习事件记录失败 user_id=%s resource_id=%s", user_id, resource_id)
        return {"resource_id": resource_id, "is_read": True, "duration_seconds": status.duration_seconds}

    @staticmethod
    async def mark_unread(user_id: int, resource_id: int) -> dict:
        """标记资源为未读"""
        resource = await GeneratedResource.filter(
            Q(id=resource_id),
            Q(user_id=user_id) | Q(visibility="public"),
        ).first()
        if not resource:
            raise ValueError("资源不存在")
        status = await ResourceReadStatus.filter(user_id=user_id, resource_id=resource_id).first()
        if status:
            status.is_read = False
            status.read_at = None
            await status.save()
        return {"resource_id": resource_id, "is_read": False}

    @staticmethod
    async def get_stats(user_id: int) -> dict:
        """聚合学习统计"""

        # 检查并生成周报
        await check_and_create_weekly_report(user_id)

        # ── 学习时长 ──
        today = date.today()
        week_ago = today - timedelta(days=6)

        sessions = await StudySession.filter(user_id=user_id, date__gte=week_ago).all()
        today_session = next((s for s in sessions if s.date == today), None)
        today_seconds = today_session.total_seconds if today_session else 0
        week_seconds = sum(s.total_seconds for s in sessions)
        active_days = len({s.date for s in sessions if s.total_seconds > 0})

        all_sessions = await StudySession.filter(user_id=user_id).all()
        total_seconds = sum(s.total_seconds for s in all_sessions)

        # ── 薄弱点（知识点 + 雷达维度） ──
        mastery_records = await KnowledgeMastery.filter(user_id=user_id).order_by("-last_practiced_at").all()
        weak_points = [
            {
                "tag": r.knowledge_tag,
                "accuracy": round(r.correct_count / max(r.total_attempts, 1), 2),
                "level": r.mastery_level,
                "total_attempts": r.total_attempts,
                "source": "mastery",
            }
            for r in mastery_records
            if r.mastery_level in ("beginner", "learning")
        ]
        # 追加雷达弱项维度。这一次取数留在外层给下面的学习指导复用 —— 雷达每次都是六维全量
        # 重算 + 落库，而 `build_learning_guidance` 内部还会再取一次：不留下这一份，同一个请求
        # 里就会把同一个用户同一时刻的数据算两遍（`/study/overview` 另外还要自己取一次）。
        radar = None
        try:
            radar = await PortraitRadarService.get(user_id)
            if radar and radar.get("dimensions"):
                labels = {"memory": "记忆(简单题)", "understanding": "理解(中等题)", "application": "应用(困难题)",
                          "analysis": "分析(多选题)", "breadth": "广度(知识覆盖)", "persistence": "坚持(活跃度)"}
                for d in radar["dimensions"]:
                    if d["score"] < 50:
                        weak_points.append({
                            "tag": labels.get(d["key"], d["key"]),
                            "accuracy": round(d["score"] / 100, 2),
                            "level": "beginner" if d["score"] < 40 else "learning",
                            "total_attempts": 0,
                            "source": "radar",
                        })
        except Exception:
            logger.warning("已忽略异常 backend/src/service/study/service.py:119", exc_info=True)

        # ── 学习路径 ──
        paths = []
        all_progress_records = await UserPathProgress.filter(user_id=user_id).all()
        progress_by_path: dict[int, list] = {}
        for record in all_progress_records:
            progress_by_path.setdefault(record.path_id, []).append(record)

        path_ids = list(progress_by_path.keys())
        path_records = await LearningPath.filter(id__in=path_ids).prefetch_related("nodes").all() if path_ids else []
        for p in path_records:
            nodes = sorted(list(p.nodes or []), key=lambda n: n.order_index)
            node_order = {n.id: n.order_index for n in nodes}
            node_map = {n.id: n for n in nodes}
            progress_records = sorted(
                progress_by_path.get(p.id, []),
                key=lambda r: node_order.get(r.node_id, 10**9),
            )
            progress_records = await reconcile_completed_prerequisites(progress_records, node_order)
            total_nodes = len(nodes)
            completed_nodes = sum(1 for r in progress_records if r.node_status == "completed")
            current = None
            for r in progress_records:
                if r.node_status in ("unlocked", "in_progress"):
                    node = node_map.get(r.node_id)
                    current = node.topic if node else None
                    break
            paths.append({
                "path_id": p.id,
                "goal": p.subject or "",
                "progress": round(completed_nodes / max(total_nodes, 1), 2),
                "total_nodes": total_nodes,
                "completed_nodes": completed_nodes,
                "current_node": current,
            })

        # ── 资源已读 + 使用率 ──
        resources = await GeneratedResource.filter(user_id=user_id).all()
        read_statuses = await ResourceReadStatus.filter(user_id=user_id,
            resource_id__in=[r.id for r in resources]).all()
        read_map = {rs.resource_id: rs.is_read for rs in read_statuses}
        collections = await ResourceCollection.filter(user_id=user_id).all()
        collected_ids = {c.resource_id for c in collections}

        by_type: dict[str, dict] = {}
        total_read = 0
        total_views = 0
        total_downloads = 0
        for r in resources:
            rt = r.resource_type or "other"
            if rt not in by_type:
                by_type[rt] = {"total": 0, "read": 0}
            by_type[rt]["total"] += 1
            if read_map.get(r.id):
                by_type[rt]["read"] += 1
                total_read += 1
            total_views += (r.view_count or 0)
            total_downloads += (r.download_count or 0)

        # ── 答题汇总 ──
        exam_records = await ExamRecord.filter(user_id=user_id).all()
        total_questions = len(exam_records)
        judged_records = [r for r in exam_records if r.is_correct is not None]
        completed_questions = len(judged_records)
        correct_count = sum(1 for r in judged_records if r.is_correct)
        session_ids = {r.session_id for r in exam_records if r.session_id}
        # 练习完成率：judged > 0 的会话视为完成
        session_totals: dict[str, dict[str, int]] = {}
        for r in exam_records:
            sid = r.session_id
            if not sid:
                continue
            if sid not in session_totals:
                session_totals[sid] = {"total": 0, "judged": 0}
            session_totals[sid]["total"] += 1
            if r.is_correct is not None:
                session_totals[sid]["judged"] += 1
        completed_sessions = sum(
            1 for item in session_totals.values()
            if item["total"] > 0 and item["judged"] >= item["total"]
        )
        total_sessions = len(session_ids)

        # ── 活跃度 ──
        # 注意别用上面的 study_time 去回答"最近学过没有"：StudySession.total_seconds 的唯一
        # 写入方是 StudyService.heartbeat，而前端从来没调用过 /study/heartbeat，所以它恒为 0，
        # active_days 也跟着恒为 0。改用 learning_events + 答题记录 —— 这两张表有真实写入方
        # （assessment / node_quiz / resource_read / classroom_chat / chat）。
        # exam_records 上面已经整体读进内存了，并集不多花查询；只多一条 learning_events 查询。
        now_utc = datetime.now(timezone.utc)
        # 一次取齐三个字段：时间戳用来数"来了几天"，事件类型和 metadata 用来加"读了多久"。
        # 分两次查同一张表没有意义。
        event_rows = await LearningEvent.filter(
            user_id=user_id,
            created_at__gte=now_utc - timedelta(days=_EVENT_QUERY_DAYS),
        ).values_list("created_at", "event_type", "metadata")
        # 两张表的时间戳并成一份，下面三个汇总共用 —— "哪天来过"和"哪一周来过几天"必须是
        # 同一批数据算出来的，各拼一次迟早会走散。
        activity_timestamps = [r.created_at for r in exam_records] + [row[0] for row in event_rows]
        today = now_utc.date()
        activity = _summarize_learning_activity(activity_timestamps, today=today)
        activity["read_seconds_this_week"] = _read_seconds_in_week(event_rows, today=today)
        # 本周做了多少 —— 和上面那条一样，数据早就在内存里，不额外查库。
        activity.update(_summarize_week_work(exam_records, event_rows, today=today))
        activity["week_trend"] = _summarize_week_trend(activity_timestamps, today=today)

        # ── 学习指导 ──
        guidance = ""
        try:
            # 用上面已经取到的 radar，不再让 helper 自己算一遍。
            guidance = await build_learning_guidance_from_radar(user_id, radar)
        except Exception:
            logger.warning("已忽略异常 backend/src/service/study/service.py:207", exc_info=True)

        return {
            "study_time": {
                "today_seconds": today_seconds,
                "week_seconds": week_seconds,
                "total_seconds": total_seconds,
                "active_days": active_days,
            },
            "activity": activity,
            "weak_points": weak_points,
            "learning_paths": paths,
            "resources": {
                "total": len(resources),
                "read_count": total_read,
                "unread_count": len(resources) - total_read,
                "open_rate": round(total_read / max(len(resources), 1), 2),
                "total_views": total_views,
                "total_downloads": total_downloads,
                "collected_count": len(collections),
                "by_type": by_type,
            },
            "exam_summary": {
                "total_questions": total_questions,
                "completed_questions": completed_questions,
                "correct_questions": correct_count,
                "correct_rate": round(correct_count / max(completed_questions, 1), 2),
                "total_sessions": total_sessions,
                "completed_sessions": completed_sessions,
                "completion_rate": round(completed_questions / max(total_questions, 1), 2),
                "session_completion_rate": round(completed_sessions / max(total_sessions, 1), 2),
            },
            "learning_guidance": guidance,
        }

    @staticmethod
    async def get_path_stats(user_id: int) -> dict:
        """分路径统计：学习时长、进度、薄弱点"""
        paths_result = []

        # 用户已加入的路径
        enrolled_progress = await UserPathProgress.filter(user_id=user_id).values("path_id")
        path_ids = list({p["path_id"] for p in enrolled_progress})
        if not path_ids:
            return {"paths": [], "untracked_time": {}, "total_time": 0, "overall_weak_points": []}
        path_records = await LearningPath.filter(id__in=path_ids).prefetch_related("nodes").all()

        # ── 学习时长：按 path_id 分组 ──
        sessions = await StudySession.filter(user_id=user_id).all()
        path_time: dict[int, int] = {}
        total_time = 0
        today = date.today()
        today_path_time: dict[int, int] = {}
        week_ago = today - timedelta(days=6)
        week_path_time: dict[int, int] = {}

        for s in sessions:
            if s.total_seconds > 0:
                total_time += s.total_seconds
                pid = s.path_id or 0
                path_time[pid] = path_time.get(pid, 0) + s.total_seconds
                if s.date and s.date >= week_ago:
                    week_path_time[pid] = week_path_time.get(pid, 0) + s.total_seconds
                if s.date == today:
                    today_path_time[pid] = today_path_time.get(pid, 0) + s.total_seconds

        # ── 用户所有知识点掌握度（薄弱点用） ──
        mastery_all = await KnowledgeMastery.filter(user_id=user_id).all()
        mastery_map: dict[str, dict] = {}
        for m in mastery_all:
            mastery_map[m.knowledge_tag] = {
                "tag": m.knowledge_tag,
                "accuracy": round(m.correct_count / max(m.total_attempts, 1), 2),
                "level": m.mastery_level,
                "total_attempts": m.total_attempts,
            }

        # ── 资源使用数据：收集所有路径的资源 ID ──
        all_resource_ids: set[int] = set()
        path_resource_ids: dict[int, set[int]] = {}
        for p in path_records:
            progress_records = await UserPathProgress.filter(path_id=p.id, user_id=user_id).all()
            ids: set[int] = set()
            for r in progress_records:
                if r.resource_ids:
                    try:
                        ids.update(json.loads(r.resource_ids))
                    except Exception:
                        logger.warning("已忽略异常 backend/src/service/study/service.py:294", exc_info=True)
            path_resource_ids[p.id] = ids
            all_resource_ids.update(ids)

        # 批量查询已读状态
        read_statuses = await ResourceReadStatus.filter(
            user_id=user_id,
            resource_id__in=list(all_resource_ids),
        ).all() if all_resource_ids else []
        read_map: dict[int, dict] = {}
        for rs in read_statuses:
            read_map[rs.resource_id] = {"is_read": rs.is_read, "duration_seconds": rs.duration_seconds}

        # 批量查询资源基础数据
        resources = await GeneratedResource.filter(
            id__in=list(all_resource_ids),
            user_id=user_id,
        ).all() if all_resource_ids else []
        res_map: dict[int, dict] = {}
        for r in resources:
            res_map[r.id] = {
                "resource_id": r.id,
                "resource_type": r.resource_type,
                "topic": r.topic,
                "view_count": r.view_count or 0,
                "download_count": r.download_count or 0,
                "last_viewed_at": str(r.last_viewed_at) if r.last_viewed_at else None,
            }

        for p in path_records:
            # ── 进度 ──
            progress_records = await UserPathProgress.filter(path_id=p.id, user_id=user_id).all()
            nodes = sorted(list(p.nodes or []), key=lambda n: n.order_index)
            node_order = {n.id: n.order_index for n in nodes}
            node_map = {n.id: n for n in nodes}
            progress_records = sorted(progress_records, key=lambda r: node_order.get(r.node_id, 10**9))
            progress_records = await reconcile_completed_prerequisites(progress_records, node_order)
            total_nodes = len(nodes)
            completed_nodes = sum(1 for r in progress_records if r.node_status == "completed")
            in_progress = sum(1 for r in progress_records if r.node_status == "in_progress")
            unlocked = sum(1 for r in progress_records if r.node_status == "unlocked")

            current_node = None
            for r in progress_records:
                if r.node_status in ("unlocked", "in_progress"):
                    node = node_map.get(r.node_id)
                    current_node = node.topic if node else None
                    break

            # ── 路径薄弱点：匹配该路径节点的 knowledge_tags ──
            path_tags = set()
            for n in nodes:
                if n.knowledge_tags:
                    try:
                        tags = json.loads(n.knowledge_tags)
                        if isinstance(tags, list):
                            path_tags.update(tags)
                    except Exception:
                        logger.warning("已忽略异常 backend/src/service/study/service.py:351", exc_info=True)

            weak_points = []
            for tag in path_tags:
                if tag in mastery_map:
                    m = mastery_map[tag]
                    if m["level"] in ("beginner", "learning"):
                        weak_points.append({**m, "source": "mastery"})
                else:
                    # 路径中存在但未曾练习过的知识点
                    weak_points.append({
                        "tag": tag, "accuracy": 0, "level": "beginner",
                        "total_attempts": 0, "source": "untouched",
                    })

            # 按掌握度排序：beginner 优先
            weak_points.sort(key=lambda w: (0 if w["level"] == "beginner" else 1, w["accuracy"]))

            # ── 路径资源使用情况 ──
            resource_list = []
            read_count = 0
            total_resource_duration = 0
            for rid in path_resource_ids.get(p.id, set()):
                rinfo = res_map.get(rid, {})
                rstatus = read_map.get(rid, {})
                is_read = rstatus.get("is_read", False)
                duration = rstatus.get("duration_seconds", 0)
                if is_read:
                    read_count += 1
                total_resource_duration += duration
                resource_list.append({
                    "resource_id": rid,
                    "resource_type": rinfo.get("resource_type", ""),
                    "topic": rinfo.get("topic", ""),
                    "is_read": is_read,
                    "duration_seconds": duration,
                    "view_count": rinfo.get("view_count", 0),
                    "download_count": rinfo.get("download_count", 0),
                    "last_viewed_at": rinfo.get("last_viewed_at"),
                })
            resource_total = len(resource_list)

            paths_result.append({
                "path_id": p.id,
                "subject": p.subject or "",
                "difficulty": p.difficulty,
                "study_time": {
                    "total_seconds": path_time.get(p.id, 0),
                    "week_seconds": week_path_time.get(p.id, 0),
                    "today_seconds": today_path_time.get(p.id, 0),
                },
                "progress": {
                    "total_nodes": total_nodes,
                    "completed_nodes": completed_nodes,
                    "in_progress_nodes": in_progress,
                    "unlocked_nodes": unlocked,
                    "current_node": current_node,
                    "percentage": round(completed_nodes / max(total_nodes, 1) * 100),
                },
                "resources": {
                    "total": resource_total,
                    "read_count": read_count,
                    "unread_count": resource_total - read_count,
                    "total_duration_seconds": total_resource_duration,
                    "list": resource_list,
                },
                "weak_points": weak_points,
            })

        # 未绑定路径的学习时长汇总
        untracked_time = {
            "total_seconds": path_time.get(0, 0),
            "week_seconds": week_path_time.get(0, 0),
            "today_seconds": today_path_time.get(0, 0),
        }

        # ── 全局汇总 ──
        overall_weak = []
        for m in mastery_all:
            if m.mastery_level in ("beginner", "learning"):
                overall_weak.append({
                    "tag": m.knowledge_tag,
                    "accuracy": round(m.correct_count / max(m.total_attempts, 1), 2),
                    "level": m.mastery_level,
                    "total_attempts": m.total_attempts,
                })

        return {
            "paths": paths_result,
            "untracked_time": untracked_time,
            "total_time": total_time,
            "overall_weak_points": overall_weak,
        }

    @staticmethod
    async def get_exam_weekly(user_id: int) -> dict:
        """最近 7 天每日正确率"""
        today = date.today()
        week_ago = today - timedelta(days=6)

        records = await ExamRecord.filter(
            user_id=user_id,
            is_correct__not_isnull=True,
            created_at__gte=week_ago,
        ).all()

        daily_map: dict[str, dict] = {}
        for r in records:
            day = str(r.created_at.date()) if r.created_at else str(today)
            if day not in daily_map:
                daily_map[day] = {"total": 0, "correct": 0}
            daily_map[day]["total"] += 1
            if r.is_correct:
                daily_map[day]["correct"] += 1

        daily = [
            {
                "date": str(week_ago + timedelta(days=i)),
                "total": daily_map.get(str(week_ago + timedelta(days=i)), {}).get("total", 0),
                "correct": daily_map.get(str(week_ago + timedelta(days=i)), {}).get("correct", 0),
                "accuracy": round(
                    daily_map.get(str(week_ago + timedelta(days=i)), {}).get("correct", 0)
                    / max(daily_map.get(str(week_ago + timedelta(days=i)), {}).get("total", 0), 1),
                    2,
                ),
            }
            for i in range(7)
        ]

        week_total = sum(d["total"] for d in daily)
        week_correct = sum(d["correct"] for d in daily)

        return {
            "daily": daily,
            "week_total": week_total,
            "week_correct": week_correct,
            "week_accuracy": round(week_correct / max(week_total, 1), 2),
        }

    @staticmethod
    async def get_learning_guidance(user_id: int) -> dict:
        """返回个性化学习指导文本"""
        guidance = await build_learning_guidance(user_id)
        return {"guidance": guidance}

    @staticmethod
    async def collect_resource(user_id: int, resource_id: int) -> dict:
        """收藏资源（幂等）"""
        resource = await GeneratedResource.filter(id=resource_id, user_id=user_id).first()
        if not resource:
            raise ValueError("资源不存在")
        await ResourceCollection.get_or_create(user_id=user_id, resource_id=resource_id)
        return {"resource_id": resource_id, "collected": True}

    @staticmethod
    async def uncollect_resource(user_id: int, resource_id: int) -> dict:
        """取消收藏"""
        resource = await GeneratedResource.filter(id=resource_id).first()
        if not resource:
            raise ValueError("资源不存在")
        await ResourceCollection.filter(user_id=user_id, resource_id=resource_id).delete()
        return {"resource_id": resource_id, "collected": False}

    @staticmethod
    async def list_collections(user_id: int) -> list[dict]:
        """列出已收藏资源"""
        collections = await ResourceCollection.filter(user_id=user_id).prefetch_related("resource").order_by("-created_at").all()
        result = []
        for c in collections:
            r = c.resource
            ext_map = {"document": "md", "ppt": "pptx", "mindmap": "txt", "exercise": "md", "case": "md", "reading": "md", "slide_animation": "json", "audio": "mp3", "html": "html"}
            ext = ext_map.get(r.resource_type, "md")
            result.append({
                "resource_id": r.id,
                "topic": r.topic,
                "resource_type": r.resource_type,
                "filename": f"{r.topic}_{r.resource_type}.{ext}",
                "preview": (r.content or "")[:200],
                "download_url": f"/resource/{r.id}/download",
                "collected_at": str(c.created_at),
            })
        return result
