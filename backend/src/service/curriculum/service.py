"""课程体系服务 — 专业×年级 → 核心课程（查表 + LLM 回退）"""

import json
import logging

from backend.src.models.curriculum_model import CurriculumCourse

logger = logging.getLogger(__name__)

# 年级策略：(查询优先级, 总上限)
_GRADE_CONFIG = {
    "大一": (["大一", "大二"], 7),
    "大二": (["大二", "大一"], 7),
    "大三": (["大三", "大二", "大一"], 7),
    "大四": (["大四", "大三", "大二"], 7),
}
_DEFAULT = (["大一", "大二"], 7)


async def get_courses(major: str, grade: str) -> list[str]:
    """查表获取课程，未命中则走 LLM 推理写入"""
    if not major:
        return []
    grade_priority, total_limit = _GRADE_CONFIG.get(grade, _DEFAULT)
    courses = await _query_from_db(major, grade_priority, total_limit)
    if courses:
        return courses
    courses = await _infer_by_llm(major, grade, grade_priority, total_limit)
    return courses


async def sync_to_portrait(user_id: int, major: str, grade: str) -> list[str] | None:
    """同步课程到用户画像 traits.curriculum_courses"""
    courses = await get_courses(major, grade)
    if not courses:
        return None

    from backend.src.models.usermodel import User
    from backend.src.models.portraitmodel import User_picture
    from backend.src.service.portrait.service import parse_traits, dump_traits

    user = await User.filter(id=user_id).first()
    if not user:
        return None
    picture = await user.picture
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()

    traits = parse_traits(picture.traits)
    traits["curriculum_courses"] = courses
    traits["curriculum_major"] = major
    traits["curriculum_grade"] = grade
    picture.traits = dump_traits(traits)
    await picture.save()
    return courses


async def get_direction_subjects(direction: str, goal: str = "", limit: int = 4) -> list[str]:
    """将宽泛学习方向拆解为可独立学习的科目/能力模块。"""
    from backend.src.ai_core.llm_config import llm
    from backend.src.utils.json_parser import parse_llm_json

    direction = str(direction or "").strip()
    goal = str(goal or "").strip()
    if not direction:
        return []
    limit = max(2, min(int(limit or 4), 6))
    prompt = (
        "你是一名课程架构师。请把用户的学习方向拆解为可独立学习、边界清晰的相关科目或能力模块。\n"
        f"学习方向：{direction}\n学习目标：{goal or '建立系统能力'}\n"
        f"请输出 {limit} 个模块，按学习依赖从基础到综合排序。不要输出泛泛的‘综合实践’或‘其他’，"
        "每个名称应是 4-20 字的具体知识领域或方法。严格只输出 JSON："
        '{"subjects":["模块1","模块2"]}'
    )
    try:
        response = await llm.ainvoke(prompt, user_id=0, pool="path")
        parsed = parse_llm_json(str(getattr(response, "content", "") or ""))
        raw_subjects = parsed.get("subjects", []) if isinstance(parsed, dict) else []
    except Exception:
        logger.exception("学习方向拆解失败 direction=%s", direction)
        raw_subjects = []

    subjects = []
    seen = set()
    for item in raw_subjects:
        value = str(item or "").strip()
        if value and value not in seen and value not in {direction, "其他", "综合实践"}:
            seen.add(value)
            subjects.append(value[:128])
        if len(subjects) >= limit:
            break
    if subjects:
        return subjects
    # LLM 不可用时仍保留可执行的分层入口，避免方向拆解失败导致学习空间为空。
    return [f"{direction}基础", f"{direction}核心方法", f"{direction}应用实践"][:limit]


async def sync_direction_subjects(user_id: int, direction: str, goal: str = "", limit: int = 4) -> list[str]:
    """生成方向科目并写入用户画像，便于概览和后续路径复用。"""
    from backend.src.models.usermodel import User
    from backend.src.models.portraitmodel import User_picture
    from backend.src.service.portrait.service import parse_traits, dump_traits

    subjects = await get_direction_subjects(direction, goal, limit)
    user = await User.filter(id=user_id).first()
    if not user:
        return subjects
    picture = await user.picture
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()
    traits = parse_traits(picture.traits)
    traits["learning_direction_subjects"] = subjects
    traits["learning_direction"] = direction[:120]
    picture.traits = dump_traits(traits)
    await picture.save()
    return subjects


async def _query_from_db(major: str, grade_priority: list[str], total_limit: int) -> list[str]:
    """按年级优先级从表查询课程，上限 total_limit 门"""
    result: list[str] = []
    seen: set[str] = set()
    for g in grade_priority:
        if len(result) >= total_limit:
            break
        row = await CurriculumCourse.filter(major=major, grade=g).first()
        if not row:
            continue
        try:
            grade_courses = json.loads(row.courses)
        except (json.JSONDecodeError, TypeError):
            continue
        for c in grade_courses:
            if c not in seen and len(result) < total_limit:
                seen.add(c)
                result.append(c)
    return result


async def _infer_by_llm(major: str, grade: str, grade_priority: list[str], total_limit: int) -> list[str]:
    """LLM 按年级推理课程并写入表，失败返回空列表"""
    from backend.src.ai_core.llm_config import llm

    try:
        resp = await llm.ainvoke(
            f"你是一位大学教务老师。请列出「{major}」专业以下年级的核心课程：{'、'.join(grade_priority)}。\n"
            f"要求：每个年级列出该学年最核心的课程名称。\n"
            f"请严格按 JSON 格式输出，不要加任何额外文字：\n"
            f'{{"{grade_priority[0]}": ["课程1", "课程2", ...], ...}}'
        )
        raw = resp.content.strip()
        from backend.src.utils.json_parser import parse_llm_json
        data = parse_llm_json(raw)
    except Exception:
        logger.exception("LLM 课程推理失败 major=%s grade=%s", major, grade)
        return []

    if not isinstance(data, dict):
        return []

    all_courses: list[str] = []
    for g in grade_priority:
        courses = data.get(g, [])
        if isinstance(courses, list):
            for c in courses:
                if isinstance(c, str) and c not in all_courses and len(all_courses) < total_limit:
                    all_courses.append(c)
            # 写入表
            try:
                await CurriculumCourse.update_or_create(
                    defaults={"courses": json.dumps(courses, ensure_ascii=False)},
                    major=major, grade=g,
                )
            except Exception:
                logger.exception("写入课程表失败 major=%s grade=%s", major, g)

    return all_courses
