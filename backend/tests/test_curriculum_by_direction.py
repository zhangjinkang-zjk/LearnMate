# -*- coding: utf-8 -*-
"""课程表按"方向"建、去掉年级，并且真的被用上。

改动前那张表是 专业×年级 → 课程：`sys_user.major` / `grade` 全为 NULL、表里 0 行，
`get_courses` 从来没被触发过；而新手引导那条路（方向 → 科目）用的是另一个函数
`get_direction_subjects`，**从不查表**，每次让模型现编 —— 同一个方向两次跑出两批不同的
名字，`learning_paths` 上又是 `unique_together=[("user_id","subject")]`，同一门课会攒成
好几条路径。科目名"是乱编的"就是这么来的。

这里钉三件事：查表优先（命中就不调模型）、生成后写回（第二次就稳定）、以及拿不到能用的
方向时绝不编名字。
"""

import inspect
import json

import pytest

from backend.src.models.curriculum_model import CurriculumCourse
from backend.src.service.curriculum import service as curriculum


class FakeQuery:
    def __init__(self, row=None):
        self.row = row
        self.filters = []

    def filter(self, **filters):
        self.filters.append(filters)
        return self

    async def first(self):
        return self.row


class _DeadLlm:
    """任何一次调用都算失败 —— 用它来证明"命中缓存时不会去调模型"。"""

    async def ainvoke(self, *_args, **_kwargs):
        raise AssertionError("命中课程表时不该再调模型")


class _ScriptedLlm:
    def __init__(self, subjects):
        self.subjects = subjects
        self.prompts = []

    async def ainvoke(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return type("R", (), {"content": json.dumps({"subjects": self.subjects}, ensure_ascii=False)})()


def _row(courses):
    return type("Row", (), {"courses": json.dumps(courses, ensure_ascii=False)})()


def _install(monkeypatch, *, row=None, llm=None, written=None):
    from backend.src.ai_core import llm_config

    if llm is not None:
        monkeypatch.setattr(llm_config, "llm", llm)
    monkeypatch.setattr(CurriculumCourse, "filter", lambda **filters: FakeQuery(row))

    async def fake_upsert(**kwargs):
        written.append(kwargs)

    monkeypatch.setattr(CurriculumCourse, "update_or_create", fake_upsert)


# ── 查表优先 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_cached_direction_does_not_call_the_model(monkeypatch):
    """第二次进来直接读表。这是"同一个方向每次给同一批科目"的唯一保证。"""
    written = []
    _install(
        monkeypatch,
        row=_row(["画法几何与机械制图", "三视图与投影规律"]),
        llm=_DeadLlm(),
        written=written,
    )

    subjects = await curriculum.get_direction_subjects("机械制图", "做出一个零件图", 4)

    assert subjects == ["画法几何与机械制图", "三视图与投影规律"]
    assert written == [], "命中缓存还写了一次表"


@pytest.mark.asyncio
async def test_the_same_direction_twice_gives_the_same_list(monkeypatch):
    """第一次生成并写回，第二次从表里拿 —— 两次必须一模一样。"""
    written = []
    llm = _ScriptedLlm(["画法几何与机械制图", "三视图与投影规律", "剖视图与断面图"])
    _install(monkeypatch, row=None, llm=llm, written=written)

    first = await curriculum.get_direction_subjects("机械制图", "", 4)
    assert first == ["画法几何与机械制图", "三视图与投影规律", "剖视图与断面图"]
    assert written and written[0]["direction"] == "机械制图"
    assert json.loads(written[0]["defaults"]["courses"]) == first

    # 写回了什么，下一次就读到什么
    _install(monkeypatch, row=_row(first), llm=_DeadLlm(), written=[])
    second = await curriculum.get_direction_subjects("机械制图", "", 4)
    assert second == first


@pytest.mark.asyncio
async def test_the_prompt_demands_real_course_names(monkeypatch):
    """名字要有出处：提示词必须明确禁止"XX基础/XX核心方法"这类自造模板名。"""
    written = []
    llm = _ScriptedLlm(["画法几何与机械制图"])
    _install(monkeypatch, row=None, llm=llm, written=written)

    await curriculum.get_direction_subjects("机械制图", "做出一个零件图", 4)

    prompt = llm.prompts[0]
    assert "机械制图" in prompt
    assert "做出一个零件图" in prompt
    assert "XX基础" in prompt and "模板名" in prompt, "没有明确禁止自造名字"
    assert "年级" not in prompt, "这一版提示词里不该再出现年级"


@pytest.mark.asyncio
async def test_a_generated_list_is_trimmed_to_the_caller_limit(monkeypatch):
    """表里存完整清单，调用方按自己的 limit 截取。"""
    written = []
    llm = _ScriptedLlm([f"课程{i}" for i in range(1, 8)])
    _install(monkeypatch, row=None, llm=llm, written=written)

    subjects = await curriculum.get_direction_subjects("机械制图", "", 3)

    assert subjects == ["课程1", "课程2", "课程3"]


class _BrokenLlm:
    async def ainvoke(self, *_args, **_kwargs):
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_a_model_failure_does_not_invent_course_names(monkeypatch):
    """模型不可用时不要编名字：宁可把方向本身当成唯一一门课。

    以前这里是 `[f"{direction}基础", f"{direction}核心方法", f"{direction}应用实践"]` ——
    那正是"科目名是乱编的"的另一半。
    """
    written = []
    _install(monkeypatch, row=None, llm=_BrokenLlm(), written=written)

    subjects = await curriculum.get_direction_subjects("机械制图", "", 4)

    assert subjects == ["机械制图"], f"编出了假课程名：{subjects}"
    assert written == [], "没生成出内容也往表里写了"


# ── 方向不可用就别拆 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["不知道", "还没想好", "1", "。", "", "   "])
async def test_an_unusable_direction_yields_no_subjects(monkeypatch, direction):
    """「不知道」拆不出课程来 —— 拿它去问模型只会得到一整套用不上的课。"""
    written = []
    _install(monkeypatch, row=None, llm=_DeadLlm(), written=written)

    assert await curriculum.get_direction_subjects(direction, "用来就业", 4) == []
    assert await curriculum.get_courses(direction) == []
    assert written == [], "不可用的方向也被写进了课程表"


@pytest.mark.asyncio
async def test_the_subject_sync_refuses_an_unusable_direction(monkeypatch):
    """同步到画像那条路同样要挡住：写进去的话，下一个读 traits 的地方又会拿它当方向用。"""
    written = []
    _install(monkeypatch, row=None, llm=_DeadLlm(), written=written)

    assert await curriculum.sync_direction_subjects(9, "不知道", "用来就业", 4) == []
    assert written == []


# ── 年级这一维真的没有了 ─────────────────────────────────────────────────

def test_the_grade_dimension_is_gone():
    """用户明确要求：这里不用看年级。"""
    assert not hasattr(curriculum, "_GRADE_CONFIG")
    assert not hasattr(curriculum, "_DEFAULT")

    fields = set(CurriculumCourse._meta.db_fields)
    assert "grade" not in fields, "模型上还留着 grade"
    assert "direction" in fields


def test_no_service_signature_asks_for_a_grade():
    """签名断言：留一个 grade 参数在那儿，下一个调用方又会把年级传进来。"""
    for func in (curriculum.get_courses, curriculum.sync_to_portrait,
                 curriculum.get_direction_subjects, curriculum.sync_direction_subjects):
        assert "grade" not in inspect.signature(func).parameters, func.__name__


@pytest.mark.asyncio
async def test_the_curriculum_snapshot_no_longer_stores_a_grade(monkeypatch):
    from backend.src.models.usermodel import User
    from backend.src.models.portraitmodel import User_picture

    class _Picture:
        traits = None
        saved = 0

        async def save(self):
            self.saved += 1

    picture = _Picture()
    user = type("U", (), {"picture": _Async(picture)})()
    monkeypatch.setattr(User, "filter", lambda **_f: _Q(user))

    written = []
    _install(monkeypatch, row=_row(["画法几何与机械制图"]), llm=_DeadLlm(), written=written)

    courses = await curriculum.sync_to_portrait(9, "机械制图")

    assert courses == ["画法几何与机械制图"]
    stored = json.loads(picture.traits)
    assert stored["curriculum_courses"] == ["画法几何与机械制图"]
    assert stored["curriculum_direction"] == "机械制图"
    assert "curriculum_grade" not in stored
    assert "curriculum_major" not in stored


class _Async:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _get():
            return self._value

        return _get().__await__()


class _Q:
    def __init__(self, value):
        self._value = value

    async def first(self):
        return self._value
