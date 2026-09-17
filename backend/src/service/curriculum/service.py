"""课程体系服务 — 学习方向 → 要学的课程/知识单元清单（查表 + LLM 回退）

这张表是"这个方向要学什么"的缓存，也是**名字稳定的唯一保证**：同一个方向第二次进来直接
读表，不再让模型重新编一遍。`learning_paths` 上有 `unique_together=[("user_id","subject")]`，
名字每次都不一样的话，同一门课会攒成好几条路径。

以前它按 专业×年级 建，还分了一整套 `_GRADE_CONFIG`：但 `sys_user.major` / `grade` 全是
NULL、表里一行都没有，`get_courses` 从来没被真正触发过；而方向拆解那边
（`get_direction_subjects`，新手引导走的就是这条）**根本不查表**，每次现编 —— 于是
"科目名是乱编的"。

**这里不校验"方向是否可用"以外的东西**：拿不到能用的方向就返回空列表，绝不用
「{direction}基础」这类模板名凑一份出来（那正是当初长出一堆假课程名的做法）。
"""

import json
import logging

from backend.src.models.curriculum_model import CurriculumCourse

logger = logging.getLogger(__name__)

# 表里存"这个方向的完整清单"，比任何调用方的 limit 都宽，免得第一个调用方用 limit=4
# 把清单缩到 4 条之后就定死了。
_MAX_CACHED_COURSES = 10


def _normalise_direction(direction) -> str:
    """缓存键的归一化：空白折叠 + 按模型长度截断。所有读写都走它，否则同一方向会存成两行。"""
    return " ".join(str(direction or "").split())[:128]


async def _query_from_db(direction: str) -> list[str]:
    """读缓存。表没有、JSON 坏了、不是数组，都当没缓存。"""
    row = await CurriculumCourse.filter(direction=direction).first()
    if not row:
        return []
    try:
        cached = json.loads(row.courses)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(cached, list):
        return []
    courses = []
    for item in cached:
        value = str(item or "").strip()
        if value and value not in courses:
            courses.append(value)
    return courses


async def _remember(direction: str, courses: list[str]) -> None:
    """把清单写回表。写失败不影响这次调用（下一次再生成一遍就是了）。"""
    try:
        await CurriculumCourse.update_or_create(
            direction=direction,
            defaults={"courses": json.dumps(courses, ensure_ascii=False)},
        )
    except Exception:
        logger.exception("写入课程表失败 direction=%s", direction)


async def _infer_by_llm(direction: str, goal: str = "", limit: int = _MAX_CACHED_COURSES) -> list[str]:
    """让模型列出这个方向要学的课程名，成功则写回表。

    提示词的重点是**要真实存在的名字**：课程名、教材章节名、行业标准里的叫法。
    以前这里写的是"你是一位大学教务老师，按年级列核心课程"，而方向拆解那边写的是
    "拆成能力模块" —— 两种说法都放任模型现编，「XX基础 / XX核心方法」就是这么来的。
    """
    from backend.src.ai_core.llm_config import llm
    from backend.src.utils.json_parser import parse_llm_json

    prompt = (
        "你是一名课程架构师。请列出学习下面这个方向需要依次掌握的课程或知识单元。\n"
        f"学习方向：{direction}\n"
        f"学习目标：{goal or '建立系统能力'}\n"
        f"请输出 {limit} 条以内，按学习依赖从基础到综合排序。\n"
        "要求：\n"
        "1. 用真实存在的课程名、教材章节名或行业标准里的通用叫法（例如「画法几何与机械制图」"
        "「三视图与投影规律」），不要自造「XX基础」「XX核心方法」「XX应用实践」这类模板名。\n"
        "2. 每条 4 到 20 个字，是一个可以独立学习、边界清晰的单元。\n"
        "3. 方向本身如果就是一门课，就给出这门课的标准章节。\n"
        "严格只输出 JSON：{\"subjects\":[\"第一条\",\"第二条\"]}"
    )
    try:
        response = await llm.ainvoke(prompt, user_id=0, pool="path")
        parsed = parse_llm_json(str(getattr(response, "content", "") or ""))
        raw_subjects = parsed.get("subjects", []) if isinstance(parsed, dict) else []
    except Exception:
        logger.exception("学习方向拆解失败 direction=%s", direction)
        return []

    courses: list[str] = []
    for item in raw_subjects:
        value = str(item or "").strip()
        # 方向自己不算一条（"机械制图" 下面再列一条 "机械制图" 没有意义），
        # 泛泛的收尾项也不要。
        if value and value not in courses and value != direction and value not in {"其他", "综合实践"}:
            courses.append(value[:128])
        if len(courses) >= limit:
            break
    return courses


async def _subjects_for(direction: str, goal: str, limit: int, refresh: bool = False) -> list[str]:
    """方向 → 清单：先查表，没有（或 refresh）才生成，生成成功就写回。"""
    from backend.src.service.portrait.service import is_usable_direction

    key = _normalise_direction(direction)
    # 没有可用的方向就不要拆科目。这里返回空列表，调用方据此不生成任何路径 ——
    # 比照着「不知道」编一整套课程要好，那套课学生一门都用不上。
    if not is_usable_direction(key):
        logger.warning("学习方向不可用，不拆科目 direction=%r", direction)
        return []

    if not refresh:
        cached = await _query_from_db(key)
        if cached:
            return cached[:limit]

    generated = await _infer_by_llm(key, goal)
    if generated:
        await _remember(key, generated)
        return generated[:limit]
    # 模型不可用时不要编名字：把方向本身当成唯一一门课交给上层（路径名就是方向名）。
    return [key]


async def get_courses(direction: str, goal: str = "", limit: int = 7, refresh: bool = False) -> list[str]:
    """这个方向要学的课程清单。专业（`user.major`）那条路也走这里 —— 对这张表来说
    "专业"和"方向"是同一件事。"""
    return await _subjects_for(direction, goal, limit, refresh=refresh)


async def get_direction_subjects(direction: str, goal: str = "", limit: int = 4, refresh: bool = False) -> list[str]:
    """把学习方向拆成可独立学习的科目（每个科目会变成一条学习路径）。

    以前这个名字叫"拆成能力模块"，而且从不查表；现在和 `get_courses` 共用同一张表和
    同一份生成逻辑，只是调用方的 limit 不同。
    """
    return await _subjects_for(direction, goal, limit, refresh=refresh)


async def sync_to_portrait(user_id: int, direction: str, goal: str = "") -> list[str] | None:
    """同步课程到用户画像 traits.curriculum_courses"""
    courses = await get_courses(direction, goal)
    if not courses:
        return None

    from backend.src.models.usermodel import User
    from backend.src.models.portraitmodel import User_picture
    from backend.src.service.portrait.service import dump_traits, parse_traits

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
    traits["curriculum_direction"] = _normalise_direction(direction)
    picture.traits = dump_traits(traits)
    await picture.save()
    return courses


async def sync_direction_subjects(
    user_id: int,
    direction: str,
    goal: str = "",
    limit: int = 4,
    force_regenerate: bool = False,
) -> list[str]:
    """读取或生成方向科目并写入画像；普通进入优先复用已保存结果。"""
    from backend.src.models.usermodel import User
    from backend.src.models.portraitmodel import User_picture
    from backend.src.service.portrait.service import dump_traits, is_usable_direction, parse_traits

    if not is_usable_direction(direction):
        # 同上：不写画像、不返回清单。写进去的话下一个读 traits 的地方又会拿它当方向用。
        logger.warning("学习方向不可用，跳过方向科目同步 direction=%r", direction)
        return []

    user = await User.filter(id=user_id).first()
    picture = await user.picture if user else None
    traits = parse_traits(picture.traits if picture else None)
    cached_direction = str(traits.get("learning_direction") or "").strip()
    cached_goal = str(traits.get("learning_direction_goal") or "").strip()
    cached_subjects = traits.get("learning_direction_subjects")
    if (
        not force_regenerate
        and cached_direction == str(direction or "").strip()
        and isinstance(cached_subjects, list)
        and cached_subjects
        and (not cached_goal or not goal or cached_goal == str(goal).strip())
    ):
        return [item.strip() for item in cached_subjects if isinstance(item, str) and item.strip()][:limit]

    # force_regenerate 要能穿透两层缓存：traits 那份（上面的早退）和课程表那份。
    subjects = await get_direction_subjects(direction, goal, limit, refresh=force_regenerate)
    if not subjects:
        return []
    if not user:
        return subjects
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()
        traits = parse_traits(picture.traits)
    traits["learning_direction_subjects"] = subjects
    traits["learning_direction"] = direction[:120]
    traits["learning_direction_goal"] = goal[:160]
    picture.traits = dump_traits(traits)
    await picture.save()
    return subjects
