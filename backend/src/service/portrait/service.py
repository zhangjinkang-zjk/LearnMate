"""画像服务 — 初始化、读取、格式化、置信度计算、再生"""

import json
import logging
import os
import re
import asyncio
import time as _time
from datetime import datetime
from backend.src.models.usermodel import User
from backend.src.models.portraitmodel import User_picture
from backend.src.models.study_model import LearningEvent

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


_last_extraction: dict[int, float] = {}

# ═══════════════════════════════════════
#  维度与标签映射（原 portrait_utils）
# ═══════════════════════════════════════

_EXTRACTION_INTERVAL = _env_int("PORTRAIT_EXTRACTION_INTERVAL_SECONDS", 20, minimum=5)

# 画像分析（访谈成稿、画像总结）的模型调用上限。超了就降级，不把用户卡在 500 上。
_PORTRAIT_LLM_TIMEOUT = _env_int("PORTRAIT_LLM_TIMEOUT_SECONDS", 40, minimum=5)

# 访谈下一问单独一档，比 _PORTRAIT_LLM_TIMEOUT 宽松：这一问实测要 ~50 秒
# （提示词 1662 字、输出只有一行 JSON，慢在模型本身，不是提示词长度）。
# 原来这里写死 10 秒，等于每一问都必然超时、全部落到兜底模板上，而失败只记在
# debug 级别，所以"五个问题过于生硬"看了很久都没人发现是超时。
# 前端不等这一问（先显示本地兜底题，模型赶在用户动笔前回来才替换），
# 所以这里的宽限不会让用户干等，只决定"能不能拿到模型那一版"。
_INTERVIEW_LLM_TIMEOUT = _env_int("INTERVIEW_LLM_TIMEOUT_SECONDS", 75, minimum=10)

TRAIT_KEYS = [
    "knowbase",
    "commonmis",
    "learning_pace",
    "interest",
    "strengths",
    "weaknesses",
]

LABEL_MAP = {
    "knowbase":      "知识掌握程度(1-5)",
    "commonmis":     "易错点",
    "learning_pace": "学习节奏偏好",
    "interest":      "兴趣方向",
    "strengths":     "学习强项",
    "weaknesses":    "学习弱项",
}

CONFIDENCE_FLOOR = {"popup": 0.75, "user_stated": 0.65, "agent_inferred": 0.30}
CONFIDENCE_CEIL  = {"popup": 0.95, "user_stated": 0.95, "agent_inferred": 0.60}
CONFIDENCE_BOOST = {"popup": 0.08, "user_stated": 0.10, "agent_inferred": 0.10}
CONFIDENCE_MAX = 0.95


def parse_traits(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def dump_traits(traits: dict) -> str:
    return json.dumps(traits, ensure_ascii=False)


def _normalise_learning_score(score: float | int | None) -> float | None:
    """Normalize an optional activity score to the persisted 0-100 range."""
    if score is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value <= 1:
        value *= 100
    return round(max(0.0, min(100.0, value)), 1)


async def record_learning_event(
    user_id: int,
    event_type: str,
    *,
    path_id: int | None = None,
    node_id: int | None = None,
    knowledge_tags: list[str] | None = None,
    score: float | int | None = None,
    evidence: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Persist one learning action and update the dynamic portrait snapshot.

    The event table is the durable audit trail; ``traits.learning_signals`` is a
    compact read model consumed by overview and prompt builders.  Keeping both
    means a failed LLM enrichment cannot erase the fact that the learner acted.
    """
    user = await User.filter(id=user_id).prefetch_related("picture").first()
    if not user:
        raise ValueError("用户不存在")

    clean_type = " ".join(str(event_type or "learning").split())[:32] or "learning"
    clean_tags = []
    for tag in knowledge_tags or []:
        value = " ".join(str(tag or "").split())[:128]
        if value and value not in clean_tags:
            clean_tags.append(value)
    clean_tags = clean_tags[:12]
    clean_evidence = " ".join(str(evidence or "").split())[:500] or None
    clean_metadata = metadata if isinstance(metadata, dict) else {}
    normalised_score = _normalise_learning_score(score)

    event = await LearningEvent.create(
        user_id=user_id,
        event_type=clean_type,
        path_id=path_id,
        node_id=node_id,
        knowledge_tags=json.dumps(clean_tags, ensure_ascii=False) if clean_tags else None,
        score=normalised_score,
        evidence=clean_evidence,
        metadata=json.dumps(clean_metadata, ensure_ascii=False) if clean_metadata else None,
    )

    picture = await user.picture
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()

    traits = parse_traits(picture.traits)
    signals = traits.get("learning_signals")
    if not isinstance(signals, dict):
        signals = {}
    activity_counts = signals.get("activity_counts")
    if not isinstance(activity_counts, dict):
        activity_counts = {}
    activity_counts[clean_type] = int(activity_counts.get(clean_type, 0) or 0) + 1

    recent = signals.get("recent_scores")
    if not isinstance(recent, list):
        recent = []
    if normalised_score is not None:
        recent.append({
            "score": normalised_score,
            "event_type": clean_type,
            "node_id": node_id,
            "created_at": str(event.created_at or datetime.now()),
        })
    recent = recent[-20:]
    scored = [item for item in recent if isinstance(item, dict) and isinstance(item.get("score"), (int, float))]
    average_score = round(sum(float(item["score"]) for item in scored) / len(scored), 1) if scored else None
    signals.update({
        "total_events": int(signals.get("total_events", 0) or 0) + 1,
        "activity_counts": activity_counts,
        "recent_scores": recent,
        "average_score": average_score,
        "last_event": {
            "type": clean_type,
            "path_id": path_id,
            "node_id": node_id,
            "knowledge_tags": clean_tags,
            "score": normalised_score,
            "created_at": str(event.created_at or datetime.now()),
        },
    })
    traits["learning_signals"] = signals
    traits["updated_at"] = str(datetime.now())
    picture.traits = dump_traits(traits)
    await picture.save()

    try:
        from backend.src.service.chat.service import invalidate_portrait_cache
        invalidate_portrait_cache(user_id)
    except Exception:
        logger.debug("画像缓存刷新失败 user_id=%s", user_id, exc_info=True)

    return {
        "event_id": event.id,
        "event_type": clean_type,
        "total_events": signals["total_events"],
        "average_score": average_score,
    }


def trait_display(traits: dict, key: str) -> str | None:
    data = traits.get(key)
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get("value", "")
    return str(data)


def trait_confident(traits: dict, key: str) -> bool:
    data = traits.get(key)
    if not isinstance(data, dict):
        return False
    return data.get("confidence", 0) >= CONFIDENCE_MAX


def build_trait_entry(value: str, source: str, existing: dict | None = None) -> dict:
    old_conf = existing.get("confidence", 0) if existing else 0
    old_source = existing.get("source", "")    if existing else ""

    floor = CONFIDENCE_FLOOR.get(source, 0.30)
    boost = CONFIDENCE_BOOST.get(source, 0.10)
    ceil  = CONFIDENCE_CEIL.get(source, 0.95)

    if source == old_source:
        new_conf = min(ceil, max(old_conf, floor) + boost)
    else:
        new_conf = min(ceil, max(old_conf, floor))

    return {
        "value": value,
        "confidence": round(new_conf, 2),
        "source": source,
    }


def _unpack(data) -> tuple:
    if isinstance(data, dict):
        return data.get("value"), data.get("confidence", 0)
    return data, 0


def format_portrait(picture, show_missing: bool = False, radar_data: dict | None = None) -> list[str]:
    lines = ["【用户画像】"]

    # 六维雷达（如有）
    if radar_data and radar_data.get("dimensions"):
        lines.append(PortraitRadarService.format_for_prompt(radar_data))

    if picture.cognition:
        lines.append(f"认知风格：{picture.cognition}")
    if picture.learning_goal:
        lines.append(f"学习目标：{picture.learning_goal}")
    if picture.personality_tags:
        try:
            tags = json.loads(picture.personality_tags)
            lines.append(f"性格标签：{'、'.join(tags)}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"性格标签：{picture.personality_tags}")

    traits = parse_traits(picture.traits)
    onboarding = traits.get("onboarding")
    if isinstance(onboarding, dict):
        if onboarding.get("identity"):
            lines.append(f"学习者身份：{onboarding['identity']}")
        if onboarding.get("direction"):
            lines.append(f"学习方向：{onboarding['direction']}")
        if onboarding.get("goal"):
            lines.append(f"学习目标原文：{onboarding['goal']}")
    filled_keys = []
    for key in TRAIT_KEYS:
        data = traits.get(key)
        if not data:
            continue
        val, conf = _unpack(data)
        if val is None or val == "":
            continue
        filled_keys.append(key)
        label = LABEL_MAP.get(key, key)
        marker = " ✓" if conf >= CONFIDENCE_MAX else ""
        lines.append(f"{label}：{val}（置信度 {conf}）{marker}")

    # 知识点掌握度（给智能体出题/推荐用）
    mastery = traits.get("knowledge_mastery")
    if mastery and isinstance(mastery, list) and len(mastery) > 0:
        lines.append("\n【知识点掌握度】")
        for m in mastery:
            level_cn = {"beginner": "入门", "learning": "学习中", "proficient": "熟练", "mastered": "已掌握"}.get(m.get("level"), m.get("level"))
            lines.append(f"  - {m.get('tag')}：{level_cn}（正确率 {m.get('accuracy', 0)}）")

    # 学习行为读模型：供路径、资源和课堂智能体感知画像的持续变化。
    signals = traits.get("learning_signals")
    if isinstance(signals, dict) and signals.get("total_events"):
        counts = signals.get("activity_counts") if isinstance(signals.get("activity_counts"), dict) else {}
        count_text = "、".join(f"{key}:{value}" for key, value in list(counts.items())[:5])
        last = signals.get("last_event") if isinstance(signals.get("last_event"), dict) else {}
        last_score = last.get("score")
        score_text = f"，最近一次得分 {last_score}" if isinstance(last_score, (int, float)) else ""
        lines.append(
            f"学习行为：累计 {signals.get('total_events', 0)} 次"
            f"（{count_text or '暂无分类'}），近期平均得分 {signals.get('average_score') or '暂无'}{score_text}"
        )

    if picture.profile_summary:
        lines.append(f"画像总结：{picture.profile_summary}")

    if show_missing:
        missing = [k for k in TRAIT_KEYS if k not in filled_keys]
        if missing:
            lines.append(f"\n【待补充维度】：{'、'.join(missing)}")
        else:
            lines.append("\n【画像状态】：全部维度已完善")

    return lines


def _format_dialogue(dialogue: list[dict]) -> str:
    lines = []
    for i, turn in enumerate(dialogue or [], 1):
        q = str(turn.get("question", "") or "").strip()
        a = str(turn.get("answer", "") or "").strip()
        if q:
            lines.append(f"AI第{i}问：{q}")
        if a:
            lines.append(f"用户回答：{a}")
    return "\n".join(lines)


def _format_assessment(assessment: dict | None) -> str:
    """把基础测评（诊断）的结果压成一句给提示词；没有就明说没有。

    不能返回空串：提示词那一段在讲"有测评时怎么用、没有时别乱提测评"，空串会让模型
    对着一片空白猜自己是不是漏了什么。
    """
    data = assessment if isinstance(assessment, dict) else {}
    try:
        percentage = float(data.get("percentage"))
    except (TypeError, ValueError):
        return "本次没有基础测评结果，只按访谈记录判断。"

    parts = [f"正确率 {round(percentage)}%"]
    correct, total = data.get("correct_count"), data.get("total_questions")
    if isinstance(correct, int) and isinstance(total, int) and total > 0:
        parts.append(f"答对 {correct}/{total} 题")
    message = str(data.get("message") or "").strip()
    if message:
        # 后端那句评语本身就带句号（diagnosis 的 _result_message），这里再补一个会变成"。。"
        parts.append(f"系统评语：{message[:120].rstrip('。.!！?？')}")
    return "；".join(parts) + "。"


def _clean_assessment(assessment: dict | None) -> dict | None:
    """落库用的那一份：只留已知字段，越界的丢掉。取不到有效正确率就当没有。"""
    data = assessment if isinstance(assessment, dict) else {}
    try:
        percentage = round(float(data.get("percentage")), 1)
    except (TypeError, ValueError):
        return None
    cleaned = {"percentage": percentage}
    for key in ("correct_count", "total_questions"):
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            cleaned[key] = value
    message = str(data.get("message") or "").strip()
    if message:
        cleaned["message"] = message[:120]
    return cleaned


def _answer_excerpt(dialogue: list[dict], index: int = -1, fallback: str = "这个方向") -> str:
    try:
        answer = str((dialogue or [])[index].get("answer", "") or "").strip()
    except (IndexError, AttributeError):
        answer = ""
    answer = " ".join(answer.split())
    if not answer:
        return fallback
    return answer[:24] + ("..." if len(answer) > 24 else "")


# 第 1 题答成这些时，"答案"里没有可用的方向。模板里的「如果把「{first}」做好了」
# 会把它原样嵌进去，于是"这句回答没有信息量"被后面几问各复读一遍 —— 用户看到的
# "五个问题过于生硬"有一半来自这里（第 1 问的提示词明确允许回答"还没想好"）。
_NON_DIRECTION_ANSWERS = {
    "无", "没有", "暂无", "不知道", "还不知道", "不知道学什么", "不清楚", "不确定",
    "不明白", "随便", "都行", "都可以", "什么都行", "还没想好", "没想好",
    "嗯", "哦", "好的", "好", "是", "否", "test", "测试",
    "1", "2", "3", "4", "5", "0", "。", "？", "?", ".", "无。", "不知道。", "还没想好。",
}

# 拿不到可用的方向时改问这些：不引用用户的回答，也就不会把一句无意义的话放大。
_GENERIC_QUESTION_VARIANTS = [
    [],  # 第 1 问本来就不引用回答
    [
        "你希望把想学的这件事用在什么地方？可以是课程作业、实习任务、竞赛项目，或者工作里的某件事。",
        "你打算先拿它做成点什么？说一个你希望看到的结果就够了。",
    ],
    [
        "你以前试过这个方向吗？可以从最近一次尝试说起，照着教程做一遍也算。",
        "现在把这个方向交给你，你能先自己做完哪一步？说个具体动作就好。",
    ],
    [
        "做这件事的时候，哪个动作最容易让你停住或者返工？比如拆需求、选方案、调试、检查结果。",
        "从开始到交付，中间哪一段你最没把握？比如判断方向、动手实现，或者确认效果。",
    ],
    [],  # 第 5 问不引用回答
]


# 访谈的五个阶段。服务端按 step 决定这一问属于哪一段，并且**只把这一段的要求**
# 交给模型 —— 模型看不到后面要问什么，也就跳不了阶段、跑不了题。这是换更快（更弱）
# 的模型之后仍然能守住"问题不偏"的关键：约束在服务端，不在提示词的说服力上。
_INTERVIEW_STAGES = (
    "确认学习方向或主题：一门学科、一个技术领域、一项工作技能，或一个想系统弄懂的主题。"
    "允许用户只说关键词或回答「还没想好」，用 1 到 3 个具体例子告诉他可以怎么答。"
    "举例要写成陈述，不要把例子也写成一问 —— 整句只能有一个问号，"
    "两个问号会被当成「一次问了多件事」拦掉，那一问就白出了。"
    "这一问不要追问项目、交付物、工作场景或学习方式。",
    "接住第 1 问问到的方向，问用户准备怎么用它、希望达成什么结果：可以问会用到的人、"
    "场景、作品或时间节点，也可以问为什么现在值得学。必须引用用户说过的方向原话。"
    "不要问起点，不要问技能缺口，不要问练习条件。",
    "了解用户的起点：以前试过什么、能独立完成到哪一步、哪一步还要照着示例做、"
    "有没有做出过一个小成果。必须引用用户说过的方向原话。不要要求他自评几分，"
    "不要问技能缺口，不要问练习条件。",
    "定位技能缺口：最耗时间的动作、最难做判断的地方、最常返工的环节、失败后不会检查什么、"
    "或哪一步无法迁移到新情况。只挑一个角度。不要问练习条件，不要要求他自评几分。",
    "了解练习条件：什么时候必须用上、每周能稳定投入多少时间、有没有现成的材料或设备限制、"
    "希望先练一个多大的最小任务。只问一个条件，不要再回到前面几段问过的内容。",
)

# 长度闸门比提示词里的要求（20 到 90 字）宽一圈：提示词负责引导，这里只拦真异常，
# 免得把一句好问题因为差几个字丢掉。
_INTERVIEW_QUESTION_MIN = 8
_INTERVIEW_QUESTION_MAX = 100
# "A、B、C" / "A/B/C" 这种是选择题写法，访谈明确不要。
_FORM_QUESTION_PATTERN = re.compile(r"[A-DＡ-Ｄ]\s*[、/／,，]\s*[A-DＡ-Ｄ]")


def _normalise_question(text) -> str:
    """比对重复用的归一化：去掉空白、标点和引号，只留字。"""
    return re.sub(r"[\s\W_]+", "", str(text or ""))


def _question_rejection_reason(question, dialogue: list[dict], step: int) -> str:
    """模型写的这一问能不能用：能用返回空串，不能用返回原因（拿去记日志）。

    只管那些"一眼就不对"的情况。判断不了的一律放行 —— 与其用一堆似是而非的规则
    拦掉好问题，不如只拦确定坏的，剩下的交给服务端锁住的阶段本身。
    """
    text = " ".join(str(question or "").split())
    if not text:
        return "空问题"
    if len(text) < _INTERVIEW_QUESTION_MIN:
        return f"太短（{len(text)} 字）"
    if len(text) > _INTERVIEW_QUESTION_MAX:
        return f"太长（{len(text)} 字）"
    if text.count("？") + text.count("?") > 1:
        return "一次问了多件事"
    if _FORM_QUESTION_PATTERN.search(text):
        return "问成了选择题"
    asked = {
        _normalise_question(turn.get("question"))
        for turn in (dialogue or [])
        if isinstance(turn, dict) and turn.get("question")
    }
    if _normalise_question(text) in asked:
        return "和已经问过的一问重复"
    return ""


def _usable_direction(dialogue: list[dict]) -> str:
    """第 1 题的答案能不能当成"想学的方向"引用进后面的问题；不能就返回空串。"""
    answer = _answer_excerpt(dialogue, 0, "")
    if not answer or answer.lower() in _NON_DIRECTION_ANSWERS:
        return ""
    # 单个数字或符号（"1"、"？"）不是方向；单个汉字或字母（"学"、"a"）可能是。
    if len(answer) < 2 and not answer.isalpha():
        return ""
    return answer


def _fallback_interview_question(step: int, dialogue: list[dict], max_steps: int = 5) -> dict:
    first = _usable_direction(dialogue)
    # Keep the learning progression stable, while varying the conversational angle
    # so a fallback response does not sound like a repeated questionnaire.
    seed_text = " ".join(str(item.get("answer", "") or "") for item in (dialogue or []))
    seed = sum(ord(char) for char in seed_text)
    question_variants = [
        [
            "你现在最想系统学哪一个方向或主题？可以说一门学科、一个技术领域或一项工作技能，比如 Python 数据分析、智能体应用开发、机械制图。",
            "如果先选一个方向开始学，你会选什么？说关键词就可以，比如前端开发、产品设计、数据分析；还没想好也可以直接说。",
            "最近最想弄懂哪一类知识或技能？不用想得很完整，先告诉我一个方向，例如编程、项目管理或知识库应用。",
        ],
        [
            f"如果把「{first}」做好了，你最想拿它解决什么？可以说会用到的人、场景，或你希望看到的结果。",
            f"你为什么现在想把「{first}」学会？是要交付一个东西、应对一项工作，还是想先做出自己的作品？",
            f"想象一下「{first}」真正派上用场的那天：你希望它替你完成哪件事？",
        ],
        [
            f"你以前试过「{first}」吗？可以从最近一次尝试说起，不管是照着教程做，还是只看懂了一部分。",
            f"现在把「{first}」交给你，你能先自己完成哪一步？说到具体动作就好。",
            f"关于「{first}」，有没有一个小成果是你已经做出来的？哪怕只是跟着示例跑通也算。",
            f"上次做「{first}」时，你实际先做了什么？可以从打开资料、准备数据或动手写第一步说起。",
        ],
        [
            f"做「{first}」时，哪一个动作最容易让你停住或返工？比如拆需求、选方案、调试、检查结果。",
            f"「{first}」第一次没做好时，你最不知道该看哪里？可以说一个具体场面。",
            f"从「{first}」的开始到交付，中间哪一段你最没把握？比如判断方向、动手实现，或确认效果。",
            f"如果把「{first}」换一个相近场景，你最担心哪一步不会迁移？可以说一个你遇到过的变化。",
        ],
        [
            "你希望什么时候能真正用上这项能力？可以说一个日期、一个项目节点，或大概的时间范围。",
            "为了把这件事练到能用，你每周能稳定留出多少时间？比如零散的几次半小时，或周末集中练。",
            "你想先练一个多大的小任务？比如先做一个最小版本，再逐步加功能。",
        ],
    ]
    idx = max(0, min(step, len(question_variants) - 1))
    # 方向不可用时换成不引用回答的那一套，而不是把「1」嵌进模板
    variants = question_variants[idx] if first else (_GENERIC_QUESTION_VARIANTS[idx] or question_variants[idx])
    question = variants[(seed + step) % len(variants)]
    return {"question": question, "finish": step >= max_steps - 1}


# ═══════════════════════════════════════
#  Service 方法
# ═══════════════════════════════════════

class PortraitChatHistory_Service:

    @staticmethod
    async def init_portrait(user_id: int, cognition: str | None,
                            learning_goal: str | None, personality_tags: str | None):
        user = await User.filter(id=user_id).first()
        if not user:
            return None, "未查找到该用户"

        picture = None
        picture_id = getattr(user, "picture_id", None)

        if picture_id:
            picture = await User_picture.filter(id=picture_id).first()

        if not picture:
            try:
                picture = await user.picture
            except Exception:
                picture = None
        if not picture:
            picture = await User_picture.create()
            user.picture = picture
            await user.save()

        if cognition:
            picture.cognition = cognition
        if learning_goal:
            picture.learning_goal = learning_goal
        if personality_tags is not None:
            if isinstance(personality_tags, list):
                picture.personality_tags = json.dumps(personality_tags, ensure_ascii=False)
            else:
                picture.personality_tags = personality_tags

        await picture.save()
        try:
            from backend.src.service.chat.service import invalidate_portrait_cache
            invalidate_portrait_cache(user_id)
        except Exception:
            logger.debug("初始画像缓存刷新失败 user_id=%s", user_id, exc_info=True)
        return user, "画像初始化成功"

    @staticmethod
    async def read_portrait(user_id: int):
        user = await User.filter(id=user_id).first()
        if not user:
            return None, "未查找到该用户"

        picture = await user.picture
        if not picture:
            return None, "该用户暂无画像"

        data = {
            "cognition": picture.cognition,
            "learning_goal": picture.learning_goal,
            "personality_tags": picture.personality_tags,
            "traits": parse_traits(picture.traits),
            "profile_summary": picture.profile_summary,
        }
        data["learning_signals"] = data["traits"].get("learning_signals", {})
        return data, "获取画像成功"

    @staticmethod
    async def regenerate_portrait(user_id: int) -> dict:
        """调用 LLM 生成画像自然语言摘要，并推断认知风格/学习目标"""
        user = await User.filter(id=user_id).first()
        if not user:
            raise ValueError("用户不存在")
        picture = await user.picture
        if not picture:
            raise ValueError("画像不存在，请先初始化")

        portrait_lines = format_portrait(picture, show_missing=True)
        portrait_text = "\n".join(portrait_lines)

        from backend.src.ai_core.llm_config import llm

        prompt = f"""你是一个学习画像分析师。根据以下用户画像数据，完成两件事：

1. 用一段流畅的中文（80-150字）总结该学习者的整体情况，包括知识水平、学习特点、待提升方向。
2. 推断最可能的学习目标(learning_goal)：exam/competition/certification/interest/job 之一。
3. 推断最可能的认知风格(cognition)：visual/auditory/read-write/practical 之一。

{portrait_text}

请严格按JSON格式输出，不要加任何额外文字：
{{"profile_summary": "...", "learning_goal": "...", "cognition": "..."}}"""

        try:
            response = await asyncio.wait_for(
                llm.ainvoke(prompt),
                timeout=_PORTRAIT_LLM_TIMEOUT,
            )
            raw = response.content.strip()
            from backend.src.utils.json_parser import parse_llm_json
            result = parse_llm_json(raw)
        except Exception:
            # 摘要只是锦上添花：模型挂了就保留已有摘要，不要把 /regenerate 变成 500。
            logger.warning("LLM 画像摘要生成失败，保留已有摘要 user_id=%s", user_id, exc_info=True)
            return {
                "cognition": picture.cognition,
                "learning_goal": picture.learning_goal,
                "personality_tags": picture.personality_tags,
                "traits": parse_traits(picture.traits),
                "profile_summary": picture.profile_summary,
            }

        summary = result.get("profile_summary", "")
        learning_goal = result.get("learning_goal", "")
        cognition = result.get("cognition", "")

        if summary:
            picture.profile_summary = summary
        if learning_goal and not picture.learning_goal:
            picture.learning_goal = learning_goal
        if cognition and not picture.cognition:
            picture.cognition = cognition
        await picture.save()
        try:
            from backend.src.service.chat.service import invalidate_portrait_cache
            invalidate_portrait_cache(user_id)
        except Exception:
            logger.debug("画像摘要缓存刷新失败 user_id=%s", user_id, exc_info=True)

        data = {
            "cognition": picture.cognition,
            "learning_goal": picture.learning_goal,
            "personality_tags": picture.personality_tags,
            "traits": parse_traits(picture.traits),
            "profile_summary": picture.profile_summary,
        }
        return data


    @staticmethod
    async def next_interview_question(
        user_id: int,
        dialogue: list[dict],
        step: int = 0,
        max_steps: int = 5,
    ) -> dict:
        """Generate the next student-profile onboarding question."""
        step = max(0, int(step or 0))
        max_steps = max(3, min(int(max_steps or 5), 5))
        if step >= max_steps:
            return {"question": "", "finish": True}

        dialogue_text = _format_dialogue(dialogue)
        # 第 1 问以前在这里直接返回兜底题，理由是"没有对话可依据，不值得等一次 ~50 秒的
        # 调用"。代价是**每个学生的第一问都是同一句模板**：前端靠 source === 'agent'
        # 决定要不要把屏幕上的题面换成模型那一版（LearnmateChatView 的 upgradeQuestion），
        # 而兜底题的 source 是 'fallback' —— 于是模型版永远换不上去，它写得再好也轮不到它。
        # 现在照常交给模型，"第一问不能干等"改由前端负责：它本来就先显示本地题面、等
        # 模型版本回来再替换，第 2 到第 5 问走的一直是这条路。
        # 提示词那边早就准备好了这种情形（{dialogue_text} 会填成"暂无，准备提出第一问"，
        # {stage_instruction} 是第 1 段的"确认学习方向"）。

        try:
            from backend.src.ai_core.llm_config import llm
            from backend.src.utils.prompt_loader import load_prompt, fill_prompt
            from backend.src.utils.json_parser import parse_llm_json

            template = load_prompt("portrait/interview_next")
            # 只把"这一问属于哪一段"的要求交给模型。它看不到后面的阶段，
            # 所以跳阶段/跑题在提示词层面就没有落点。
            stage_instruction = _INTERVIEW_STAGES[min(step, len(_INTERVIEW_STAGES) - 1)]
            prompt = fill_prompt(
                template,
                step=str(step + 1),
                max_steps=str(max_steps),
                stage_instruction=stage_instruction,
                dialogue_text=dialogue_text or "暂无，准备提出第一问",
            )
            response = await asyncio.wait_for(
                llm.ainvoke(prompt, priority="low", user_id=int(user_id), pool="portrait"),
                timeout=_INTERVIEW_LLM_TIMEOUT,
            )
            result = parse_llm_json(response.content.strip())
            question = str(result.get("question", "") if isinstance(result, dict) else "").strip()
            finish = bool(result.get("finish", False)) if isinstance(result, dict) else False
            reason = _question_rejection_reason(question, dialogue, step)
            if not reason:
                # source 是给前端用的：它先显示本地兜底题、只在模型版本回来时替换，
                # 必须能区分"这是模型写的"和"这是兜底"，否则会把一句模板题换成另一句。
                return {"question": question, "finish": finish or step >= max_steps - 1, "source": "agent"}
            logger.warning(
                "画像访谈下一问不合用（%s），使用兜底问题 user_id=%s step=%s 内容=%r",
                reason, user_id, step, question[:60],
            )
        except Exception:
            logger.warning("画像访谈下一问生成失败，使用兜底问题 user_id=%s step=%s", user_id, step, exc_info=True)

        return {**_fallback_interview_question(step, dialogue, max_steps), "source": "fallback"}

    @staticmethod
    async def init_from_dialogue(
        user_id: int,
        dialogue: list[dict],
        onboarding_context: dict | None = None,
        assessment: dict | None = None,
    ) -> dict:
        """通过多轮问答对话让 LLM 提取并初始化用户画像。

        assessment 是访谈之后那次基础测评（诊断）的结果。它以前只被前端当门槛用 ——
        前端发了、接口没这个字段，Pydantic 静默丢掉，于是"正在结合访谈与基础测评生成
        综合画像"那句文案是假的：测评分数从来没进过画像。
        """
        user = await User.filter(id=user_id).first()
        if not user:
            raise ValueError("用户不存在")

        picture = await user.picture
        if not picture:
            picture = await User_picture.create()
            user.picture = picture
            await user.save()

        # 格式化对话文本
        lines = []
        for i, turn in enumerate(dialogue):
            q = turn.get("question", "").strip()
            a = turn.get("answer", "").strip()
            if q:
                lines.append(f"AI 第{i+1}问：{q}")
            if a:
                lines.append(f"用户回答：{a}")
        dialogue_text = "\n".join(lines)

        if not dialogue_text.strip():
            raise ValueError("对话内容为空，无法提取画像")

        from backend.src.ai_core.llm_config import llm
        from backend.src.utils.prompt_loader import load_prompt, fill_prompt
        from backend.src.utils.json_parser import parse_llm_json

        template = load_prompt("portrait/init_from_dialogue")
        prompt = fill_prompt(
            template,
            dialogue_text=dialogue_text,
            assessment_text=_format_assessment(assessment),
        )

        # 模型挂了不能把整个"访谈收尾"变成 500：这一步真正不能丢的是 identity/direction/goal，
        # 它们是请求里带过来的，不经过模型；模型只负责推断认知风格、标签和摘要。
        # 前端 PortraitSummaryPage 本来就准备好了"画像分析没有完成，以下是你在访谈中的原始回答"
        # 的展示分支，抛异常等于把那条分支废掉，用户只能卡在总结页反复点重试。
        result: dict = {}
        try:
            response = await asyncio.wait_for(
                llm.ainvoke(prompt),
                timeout=_PORTRAIT_LLM_TIMEOUT,
            )
            parsed = parse_llm_json(response.content.strip())
            if isinstance(parsed, dict):
                result = parsed
            else:
                logger.warning("对话画像提取返回非对象 user_id=%s type=%s", user_id, type(parsed).__name__)
        except asyncio.TimeoutError:
            logger.warning("对话画像提取超时，降级为只保存访谈上下文 user_id=%s timeout=%ss", user_id, _PORTRAIT_LLM_TIMEOUT)
        except Exception:
            logger.warning("对话画像提取失败，降级为只保存访谈上下文 user_id=%s", user_id, exc_info=True)

        learning_direction = str(result.get("learning_direction", "") or "").strip()
        learning_goal_text = str(result.get("learning_goal_text", "") or "").strip()
        onboarding_context = onboarding_context if isinstance(onboarding_context, dict) else {}
        selected_identity = str(onboarding_context.get("identity") or "").strip()
        selected_direction = str(onboarding_context.get("direction") or "").strip()
        selected_goal = str(onboarding_context.get("goal") or "").strip()
        learning_direction = selected_direction or learning_direction
        learning_goal_text = selected_goal or learning_goal_text
        cognition = result.get("cognition", "") or ""
        learning_goal = result.get("learning_goal", "") or ""
        tags = result.get("personality_tags") or []
        profile_summary = str(result.get("profile_summary", "") or "").strip()
        extracted_traits = result.get("traits") if isinstance(result.get("traits"), dict) else {}

        # 只写非空值
        if cognition:
            picture.cognition = cognition
        if learning_goal:
            picture.learning_goal = learning_goal
        if isinstance(tags, list) and tags:
            import json
            picture.personality_tags = json.dumps(tags, ensure_ascii=False)
        if profile_summary:
            picture.profile_summary = profile_summary[:240]

        # 同步写入 traits 的 interest 维度（如果有对话提取的兴趣信息）
        traits = parse_traits(picture.traits)
        if learning_direction or learning_goal_text or selected_identity:
            onboarding = traits.get("onboarding") if isinstance(traits.get("onboarding"), dict) else {}
            if learning_direction:
                onboarding["direction"] = learning_direction[:120]
            if learning_goal_text:
                onboarding["goal"] = learning_goal_text[:160]
            if selected_identity:
                onboarding["identity"] = selected_identity[:80]
            traits["onboarding"] = onboarding
            if learning_direction:
                traits["learning_direction"] = learning_direction[:120]
            if learning_goal_text:
                traits["learning_direction_goal"] = learning_goal_text[:160]
        # 把测评结果和访谈结论存在一起：画像之外的地方（路径生成、学情页）要回答
        # "这个起点是怎么来的"时，得能查到当时那次测评。
        assessment_record = _clean_assessment(assessment)
        if assessment_record:
            onboarding = traits.get("onboarding") if isinstance(traits.get("onboarding"), dict) else {}
            onboarding["assessment"] = assessment_record
            traits["onboarding"] = onboarding
        if tags:
            traits["interest"] = build_trait_entry(
                "、".join(tags[:3]), "user_stated", traits.get("interest")
            )

            # 从标签中推断 strengths
            ability_keywords = ["逻辑", "分析", "表达", "动手", "创意", "记忆", "专注", "思维"]
            strength_tags = [t for t in tags if any(kw in t for kw in ability_keywords)]
            if strength_tags:
                traits["strengths"] = build_trait_entry(
                    "、".join(strength_tags), "user_stated", traits.get("strengths")
                )

        for key in TRAIT_KEYS:
            value = extracted_traits.get(key) or result.get(key)
            if isinstance(value, list):
                value = "、".join(str(item).strip() for item in value if str(item).strip())
            value = str(value or "").strip()
            if value:
                traits[key] = build_trait_entry(value[:120], "user_stated", traits.get(key))

        picture.traits = dump_traits(traits)
        await picture.save()
        try:
            from backend.src.service.chat.service import invalidate_portrait_cache
            invalidate_portrait_cache(user_id)
        except Exception:
            logger.debug("已忽略异常 backend/src/service/portrait/service.py:449", exc_info=True)

        # 只记长度，不记内容：cognition / learning_goal / tags 都是用户画像数据，
        # 属于个人信息，不该进日志。
        logger.info(
            "对话画像初始化成功 user_id=%s cognition_len=%s goal_len=%s tags=%s",
            user_id,
            len(cognition or ""),
            len(learning_goal or ""),
            len(tags) if isinstance(tags, list) else 0,
        )

        return {
            "cognition": picture.cognition,
            "learning_goal": picture.learning_goal,
            "personality_tags": picture.personality_tags,
            "traits": parse_traits(picture.traits),
            "profile_summary": picture.profile_summary,
        }


# ═══════════════════════════════════════
#  六维雷达 Service
# ═══════════════════════════════════════

RADAR_DIMENSIONS = [
    {"key": "memory",        "label": "记忆",   "desc": "基础回忆与知识提取表现"},
    {"key": "understanding", "label": "理解",   "desc": "概念理解与知识关联表现"},
    {"key": "application",   "label": "应用",   "desc": "场景迁移与实际应用表现"},
    {"key": "analysis",      "label": "分析",   "desc": "问题拆解与综合判断表现"},
    {"key": "breadth",       "label": "广度",   "desc": "知识覆盖与探索范围"},
    {"key": "persistence",   "label": "坚持",   "desc": "学习投入与持续参与"},
]

# 同一进程内同一用户的雷达重算只允许一个请求进入写入阶段，避免首次创建时
# 多个画像/学习接口同时执行 get_or_create 导致 MySQL 唯一外键死锁。
_RADAR_COMPUTE_LOCKS: dict[int, asyncio.Lock] = {}


def _radar_compute_lock(user_id: int) -> asyncio.Lock:
    lock = _RADAR_COMPUTE_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _RADAR_COMPUTE_LOCKS[user_id] = lock
    return lock


def _is_retryable_radar_write_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in ("1213", "deadlock", "1062", "duplicate"))


class PortraitRadarService:

    @staticmethod
    async def compute(user_id: int) -> dict:
        async with _radar_compute_lock(user_id):
            return await PortraitRadarService._compute_locked(user_id)

    @staticmethod
    async def _compute_locked(user_id: int) -> dict:
        """从答题数据实时计算六维雷达分数并写入 PortraitRadar 表"""
        from datetime import datetime, timedelta
        from backend.src.models.exam_model import ExamRecord, ExamQuestion, KnowledgeMastery
        from backend.src.models.portrait_radar_model import PortraitRadar

        user = await User.filter(id=user_id).first()
        if not user:
            raise ValueError("用户不存在")

        # 所有已判分的答题记录（join 题目表拿 difficulty/question_type）
        records = await ExamRecord.filter(
            user_id=user_id, is_correct__not_isnull=True
        ).prefetch_related("question").all()

        def _accuracy(questions) -> int:
            """给定题目列表，算正确率百分比整数"""
            if not questions:
                return 0
            scored = [(r.is_correct, r.question) for r in records if r.question in questions]
            if not scored:
                return 0
            correct = sum(1 for ok, _ in scored if ok)
            return round(correct / len(scored) * 100)

        # 按难度分组
        easy_qs = [r.question for r in records if r.question and r.question.difficulty == "easy"]
        medium_qs = [r.question for r in records if r.question and r.question.difficulty == "medium"]
        hard_qs = [r.question for r in records if r.question and r.question.difficulty == "hard"]

        memory = _accuracy(easy_qs)
        understanding = _accuracy(medium_qs)
        application = _accuracy(hard_qs)

        # 分析 — multi_choice 题型正确率
        multi_qs = [r.question for r in records if r.question and r.question.question_type == "multi_choice"]
        analysis = _accuracy(multi_qs)

        # 广度 — 已覆盖知识标签种类数（50 种 = 100 分）
        mastery_records = await KnowledgeMastery.filter(user_id=user_id).all()
        tag_count = len(mastery_records)
        breadth = min(100, round(tag_count / 50 * 100))

        # 坚持 — 近 30 天活跃天数占比
        from datetime import timezone as tz
        cutoff = datetime.now(tz.utc) - timedelta(days=30)
        recent_dates = set()
        for r in records:
            ct = r.created_at
            if not ct:
                continue
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=tz.utc)
            if ct >= cutoff:
                recent_dates.add(ct.date())
        persistence = min(100, round(len(recent_dates) / 30 * 100))

        # 写入/更新 Radar 表。不要使用 Tortoise 的 select_for_update + create：
        # 首次并发请求在 MySQL 上可能对用户外键和唯一索引形成死锁。
        radar = await PortraitRadar.filter(user_id=user_id).first()
        if not radar:
            from tortoise.exceptions import IntegrityError, OperationalError

            for attempt in range(3):
                try:
                    radar = await PortraitRadar.create(user_id=user_id)
                    break
                except (IntegrityError, OperationalError) as error:
                    if not _is_retryable_radar_write_error(error) or attempt == 2:
                        raise
                    await asyncio.sleep(0.05 * (2 ** attempt))
                    radar = await PortraitRadar.filter(user_id=user_id).first()
                    if radar:
                        break
            if not radar:
                raise RuntimeError(f"无法创建用户 {user_id} 的画像雷达记录")

        radar.memory = memory
        radar.understanding = understanding
        radar.application = application
        radar.analysis = analysis
        radar.breadth = breadth
        radar.persistence = persistence
        await radar.save()

        return PortraitRadarService._format(radar)

    @staticmethod
    async def get(user_id: int) -> dict | None:
        """获取最新雷达数据，不存在则自动计算"""
        from backend.src.models.portrait_radar_model import PortraitRadar

        radar = await PortraitRadar.filter(user_id=user_id).first()
        try:
            return await PortraitRadarService.compute(user_id)
        except ValueError:
            return PortraitRadarService._format(radar) if radar else None
        except Exception:
            logger.exception("画像雷达重算失败 user_id=%s", user_id)
            return PortraitRadarService._format(radar) if radar else None

    @staticmethod
    def _format(radar) -> dict:
        return {
            "radar_id": radar.id,
            "user_id": radar.user_id,
            "dimensions": [
                {"key": "memory",        "label": "记忆",   "score": radar.memory,        "desc": "基础回忆与知识提取表现"},
                {"key": "understanding", "label": "理解",   "score": radar.understanding, "desc": "概念理解与知识关联表现"},
                {"key": "application",   "label": "应用",   "score": radar.application,   "desc": "场景迁移与实际应用表现"},
                {"key": "analysis",      "label": "分析",   "score": radar.analysis,      "desc": "问题拆解与综合判断表现"},
                {"key": "breadth",       "label": "广度",   "score": radar.breadth,       "desc": "知识覆盖与探索范围"},
                {"key": "persistence",   "label": "坚持",   "score": radar.persistence,   "desc": "学习投入与持续参与"},
            ],
            "updated_at": str(radar.updated_at),
        }

    @staticmethod
    def format_for_prompt(radar: dict) -> str:
        """格式化为 agent prompt 可用的文本"""
        if not radar or not radar.get("dimensions"):
            return "暂无六维雷达数据"
        lines = ["【六维能力雷达】"]
        for d in radar["dimensions"]:
            bar = "█" * (d["score"] // 10) + "░" * (10 - d["score"] // 10)
            lines.append(f"  {d['label']}：{bar} {d['score']}")
        return "\n".join(lines)

    @staticmethod
    async def sync_to_portrait(user_id: int) -> None:
        """雷达分数反哺画像 traits（strengths/weaknesses）"""
        from backend.src.models.portrait_radar_model import PortraitRadar

        radar = await PortraitRadar.filter(user_id=user_id).first()
        if not radar:
            return

        user = await User.filter(id=user_id).first()
        if not user:
            return
        picture = await user.picture
        if not picture:
            picture = await User_picture.create()
            user.picture = picture
            await user.save()

        traits = parse_traits(picture.traits)
        scores = {
            "记忆": radar.memory, "理解": radar.understanding, "应用": radar.application,
            "分析": radar.analysis, "广度": radar.breadth, "坚持": radar.persistence,
        }

        strengths = [f"{k}({v})" for k, v in scores.items() if v >= 70]
        weaknesses = [f"{k}({v})" for k, v in scores.items() if v < 50]

        if strengths:
            traits["strengths"] = build_trait_entry(
                "、".join(strengths), "agent_inferred", traits.get("strengths")
            )
        if weaknesses:
            traits["weaknesses"] = build_trait_entry(
                "、".join(weaknesses), "agent_inferred", traits.get("weaknesses")
            )

        picture.traits = dump_traits(traits)
        await picture.save()
        try:
            from backend.src.service.chat.service import invalidate_portrait_cache
            invalidate_portrait_cache(user_id)
        except Exception:
            logger.debug("雷达画像缓存刷新失败 user_id=%s", user_id, exc_info=True)


async def build_learning_guidance(user_id: int) -> str:
    """读雷达+画像+掌握度，输出显式的 LLM 学习指导文本"""
    try:
        radar_data = await PortraitRadarService.get(user_id)
    except Exception:
        return ""
    if not radar_data or not radar_data.get("dimensions"):
        return ""

    dims = {d["key"]: d["score"] for d in radar_data["dimensions"]}
    levels = {}
    for key, score in dims.items():
        if score >= 80:
            levels[key] = "优秀"
        elif score >= 60:
            levels[key] = "尚可"
        elif score >= 40:
            levels[key] = "薄弱，需重点训练"
        else:
            levels[key] = "严重不足"

    labels = {"memory": "记忆(简单题)", "understanding": "理解(中等题)", "application": "应用(困难题)",
              "analysis": "分析(多选题)", "breadth": "广度(知识覆盖)", "persistence": "坚持(活跃度)"}

    lines = []
    # 一、能力分析
    lines.append("## 学习者能力分析")
    for key, label in labels.items():
        score = dims.get(key, 0)
        level = levels.get(key, "未知")
        lines.append(f"- {label}: {score}分 — {level}")

    # 二、学习策略建议
    lines.append("\n## 学习策略建议")
    weak = [(k, v) for k, v in dims.items() if v < 50]
    moderate = [(k, v) for k, v in dims.items() if 50 <= v < 70]
    strong = [(k, v) for k, v in dims.items() if v >= 70]
    if weak:
        w_labels = [labels.get(k, k) for k, _ in weak]
        lines.append(f"- 薄弱环节：{'、'.join(w_labels)} → 优先分配学习资源")
    if moderate:
        m_labels = [labels.get(k, k) for k, _ in moderate]
        lines.append(f"- 巩固方向：{'、'.join(m_labels)} → 保持练习频率")
    if strong:
        s_labels = [labels.get(k, k) for k, _ in strong]
        lines.append(f"- 优势利用：{'、'.join(s_labels)} → 可作为学习加速器")

    # 三、出题指导
    lines.append("\n## 出题指导")
    mem, und, app = dims.get("memory", 50), dims.get("understanding", 50), dims.get("application", 50)
    total_gap = max((100 - mem) + (100 - und) + (100 - app), 1)
    easy_pct = max(15, round((100 - mem) / total_gap * 100))
    medium_pct = round((100 - und) / total_gap * 100)
    hard_pct = min(50, 100 - easy_pct - medium_pct)
    medium_pct = 100 - easy_pct - hard_pct  # 确保加起来 = 100
    lines.append(f"- 建议难度配比：easy {easy_pct}% / medium {medium_pct}% / hard {hard_pct}%")
    if dims.get("analysis", 50) < 60:
        lines.append("- 分析能力不足：增加多选题比例")
    if dims.get("application", 50) < 50:
        lines.append("- 应用能力薄弱：每道困难题附带详细解析")

    # 弱项知识点
    from backend.src.models.exam_model import KnowledgeMastery
    mastery_records = await KnowledgeMastery.filter(user_id=user_id).all()
    weak_tags = [m.knowledge_tag for m in mastery_records if m.correct_count / max(m.total_attempts, 1) < 0.5]
    if weak_tags:
        lines.append(f"- 弱项知识点优先出题：{'、'.join(weak_tags[:8])}")

    # 四、学习资料指导
    lines.append("\n## 学习资料指导")
    if dims.get("memory", 50) < 60:
        lines.append("- 从基础概念讲起，循序渐进，每节附小结")
    if dims.get("understanding", 50) < 60:
        lines.append("- 增加对比分析和概念辨析内容")
    if dims.get("application", 50) < 50:
        lines.append("- 每节附实践练习和例题讲解")
    if dims.get("analysis", 50) < 60:
        lines.append("- 增加案例分析和归纳总结模块")
    if dims.get("breadth", 50) < 50:
        lines.append("- 引入跨领域连接和拓展阅读")
    if dims.get("persistence", 50) < 30:
        lines.append("- 内容拆分为小块，降低单次学习时长")

    return "\n".join(lines)


async def extract_portrait_from_chat(
    user_id: int,
    chat_group_id: int,
    *,
    minimum_records: int = 2,
) -> None:
    """每次对话后异步调用，从最近聊天记录中提取画像特征。

    普通聊天默认积累两轮再提取；互动课堂按节点隔离聊天组，一问一答本身就是
    完整观察样本，因此调用方可显式传入 ``minimum_records=1``。
    """
    now = _time.time()
    elapsed = now - _last_extraction.get(user_id, 0)
    if elapsed < _EXTRACTION_INTERVAL:
        logger.debug(f"画像提取冷却中 user_id={user_id} 距上次={elapsed:.0f}s")
        return

    try:
        from backend.src.models.chat_history_model import ChatHistory
        from backend.src.ai_core.llm_config import llm
        from backend.src.utils.prompt_loader import load_prompt, fill_prompt
        from backend.src.utils.json_parser import parse_llm_json

        user = await User.filter(id=user_id).first()
        if not user:
            return

        # 确保画像存在
        picture = await user.picture
        if not picture:
            picture = await User_picture.create()
            user.picture = picture
            await user.save()

        # 取最近 10 条消息
        records = await ChatHistory.filter(
            user_id=user_id, chat_group_id=chat_group_id
        ).order_by("-created_at").limit(10).all()

        required_records = max(1, int(minimum_records))
        if len(records) < required_records:
            logger.debug(
                "画像提取跳过：消息数不足 user_id=%s records=%s required=%s group=%s",
                user_id,
                len(records),
                required_records,
                chat_group_id,
            )
            return

        _last_extraction[user_id] = now

        messages = []
        for r in reversed(records):
            if r.req:
                messages.append(f"用户：{r.req}")
            if r.res:
                res_short = r.res[:200]
                messages.append(f"AI：{res_short}")

        recent_text = "\n".join(messages)

        # 已有画像
        traits = parse_traits(picture.traits)
        existing = {}
        for key in TRAIT_KEYS:
            entry = traits.get(key)
            if isinstance(entry, dict) and entry.get("confidence", 0) >= 0.95:
                existing[key] = f"{entry['value']}（置信度已满，勿覆盖）"
            elif isinstance(entry, dict) and entry.get("value"):
                existing[key] = entry["value"]
        existing_text = json.dumps(existing, ensure_ascii=False) if existing else "暂无"

        template = load_prompt("portrait/extract")
        prompt = fill_prompt(template, existing_portrait=existing_text, recent_messages=recent_text)

        response = await llm.ainvoke(prompt)
        result = parse_llm_json(response.content.strip())

        if not result or not isinstance(result, dict):
            # 不记 response.content：那是模型对用户访谈原文的抽取结果，含画像数据。
            logger.info(
                "画像提取无结果 user_id=%s content_len=%s",
                user_id,
                len(str(response.content or "")),
            )
            return

        updated = False
        for key in TRAIT_KEYS:
            value = result.get(key)
            if not value or not isinstance(value, str) or len(value) > 80:
                continue
            entry = traits.get(key) if isinstance(traits.get(key), dict) else None
            if entry and entry.get("confidence", 0) >= 0.95:
                continue
            traits[key] = build_trait_entry(value, "agent_inferred", entry)
            updated = True

        if updated:
            picture.traits = dump_traits(traits)
            await picture.save()
            logger.info(f"画像提取成功 user_id={user_id} 更新维度={[k for k in result if k in TRAIT_KEYS]}")

            # 自动刷新画像总结
            try:
                await PortraitChatHistory_Service.regenerate_portrait(user_id)
            except Exception:
                logger.exception(f"画像总结刷新失败 user_id={user_id}")

    except Exception:
        logger.exception(f"画像提取失败 user_id={user_id}")
