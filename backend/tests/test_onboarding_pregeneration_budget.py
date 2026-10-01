# -*- coding: utf-8 -*-
"""确认画像前后，后端到底自己生成了多少东西 —— 把这三条口径钉住。

起因：诊断一结束（不是点「确认画像」那一刻，那条入口要早几十秒）后端就会排一批生成，
量出来是这样的：

    4 条路径的规划      约 15-30 次模型调用（Leader 那条单次实测 105-185 秒）
    4 个首节点的内容    每个节点"资料 3 种 + 检测题 + 互动课堂"约 16-28 次 → 约 65-110 次
    雷达全量重算        16 次（每次资源生成 2 次、每条路径 2 次）
    合计                约 80-140 次模型调用，其中约四分之三服务于三条学生大概率不会
                        点开的路径

三处是结构性浪费，不是量的问题，所以各自留一条测试：

1. **四条路径都预热首节点。** 学生一次只学一条路径 —— 一个学生不该拿到四份"第一章"。
2. **互动课堂的产物没有消费者。** 它由 `GET /path/{id}/node/{id}/classroom` 读出，前端
   一处都没调过（进阶学习走的是另一条链 `/path/classroom/chat`）。而它是最贵的一块：
   四幕剧本 + 逐幕审核 + 四段讲解音频。现在默认不预热，开关是
   `PATH_AUTO_PREGENERATE_CLASSROOM`（代码和路由都留着，接上前端就能恢复）。
3. **同一个请求里算两遍雷达。** `PortraitRadarService.get` 没有缓存分支，每次都是六维
   全量重算 + 落库；而 `make_generation_state` / `generate_path` 既要指导文本又要雷达
   本体去拼 portrait_context —— 以前各取一次，同一用户同一时刻的数据算了两遍。
"""

import pytest

from backend.src.service.path import classroom as classroom_module
from backend.src.service.path import service as path_service
from backend.src.service.portrait import service as portrait_service
from backend.src.service.resource import generation_context


# ── 1. 互动课堂默认不预热 ────────────────────────────────

@pytest.mark.asyncio
async def test_classroom_pregeneration_is_off_by_default(monkeypatch):
    """默认不排课堂 —— 它的产物现在没有任何前端入口。"""
    generated: list[tuple] = []

    async def fake_generate_classroom_lesson(*args, **kwargs):
        generated.append(args)
        return {"lesson": {}}

    monkeypatch.setattr(classroom_module, "generate_classroom_lesson", fake_generate_classroom_lesson)
    monkeypatch.delenv("PATH_AUTO_PREGENERATE_CLASSROOM", raising=False)

    assert await path_service.PathService.generate_node_classroom(1, 2, 3) is None
    assert generated == [], "课堂默认还在预热"


@pytest.mark.asyncio
async def test_the_classroom_switch_still_works_when_turned_on(monkeypatch):
    """开关两个方向都要成立，否则"默认关闭"和"功能坏了"在测试里长得一样。

    前端接上课堂页时（或需要一个"立刻可开"的演示时）只改环境变量就该恢复原样。
    """
    generated: list[tuple] = []

    async def fake_generate_classroom_lesson(*args, **kwargs):
        generated.append(args)
        return {"lesson": {"scenes": []}}

    monkeypatch.setattr(classroom_module, "generate_classroom_lesson", fake_generate_classroom_lesson)
    monkeypatch.setenv("PATH_AUTO_PREGENERATE_CLASSROOM", "true")

    result = await path_service.PathService.generate_node_classroom(4, 5, 6)

    assert result == {"lesson": {"scenes": []}}
    assert generated == [(4, 5, 6)]


# ── 3. 一次请求只算一次雷达 ──────────────────────────────

class _Awaitable:
    """`user.picture` 是关系字段，真实代码里被 await —— 假用户也得能 await。"""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _resolve():
            return self._value

        return _resolve().__await__()


def _fake_radar(radar_calls: list[int]):
    class _Radar:
        @staticmethod
        async def get(user_id):
            radar_calls.append(user_id)
            return {
                "radar_id": 1,
                "user_id": user_id,
                "answered_count": 3,
                "dimensions": [
                    {"key": key, "label": key, "score": 40, "desc": ""}
                    for key in ("memory", "understanding", "application", "analysis", "breadth", "persistence")
                ],
                "updated_at": "2026-09-30 00:00:00",
            }

    return _Radar


@pytest.mark.asyncio
async def test_guidance_and_radar_share_one_compute(monkeypatch):
    """指导文本和雷达本体来自同一次计算，而且指导是模板拼的（不调模型）。"""
    radar_calls: list[int] = []

    async def fake_weak_tags(user_id):
        return ["洛必达法则"]

    monkeypatch.setattr(portrait_service, "PortraitRadarService", _fake_radar(radar_calls))
    monkeypatch.setattr(portrait_service, "_load_weak_knowledge_tags", fake_weak_tags)

    guidance, radar_data = await portrait_service.build_learning_guidance_with_radar(7)

    assert radar_calls == [7], "雷达被算了不止一次"
    assert radar_data and radar_data["dimensions"], "雷达本体没有交出去，调用方只能自己再算一遍"
    assert "## 学习者能力分析" in guidance
    assert "洛必达法则" in guidance


@pytest.mark.asyncio
async def test_generating_resources_computes_the_radar_once(monkeypatch):
    """一次资源生成里，`make_generation_state` 只许取一次雷达。

    这里原来有两个取法：`build_learning_guidance` 里面的、和下面拼 portrait_context 的
    那个 —— 同一个用户同一时刻的同一份数据算了两遍，两遍还都落在同一把用户级锁上。
    """
    radar_calls: list[int] = []

    class _User:
        major = "机械工程"
        grade = "大二"
        picture = _Awaitable(object())

    class _FakeUser:
        @staticmethod
        def filter(**kwargs):
            return _FakeUser()

        async def first(self):
            return _User()

    class _FakeAgentSkill:
        @staticmethod
        def filter(**kwargs):
            return _FakeAgentSkill()

        async def all(self):
            return []

    async def fake_kb_search(topic, top_k=3, user_id=0):
        return "暂无相关知识库资料"

    async def fake_weak_tags(user_id):
        return []

    monkeypatch.setattr(generation_context, "User", _FakeUser)
    monkeypatch.setattr(generation_context, "AgentSkill", _FakeAgentSkill)
    monkeypatch.setattr(generation_context, "kb_search", fake_kb_search)
    monkeypatch.setattr(generation_context, "format_portrait", lambda *a, **k: ["【用户画像】机械工程"])
    monkeypatch.setattr(portrait_service, "PortraitRadarService", _fake_radar(radar_calls))
    monkeypatch.setattr(portrait_service, "_load_weak_knowledge_tags", fake_weak_tags)

    state = await generation_context.make_generation_state(
        topic="机械制图", user_id=8, resource_types=["document"],
    )

    assert radar_calls == [8], f"一次资源生成算了 {len(radar_calls)} 次雷达"
    assert state["portrait_context"] == "【用户画像】机械工程"
    assert "## 学习者能力分析" in state["learning_guidance"]


@pytest.mark.asyncio
async def test_no_radar_means_no_guidance_and_no_weak_tag_query(monkeypatch):
    """雷达取不到时给空文本 —— 和旧行为一致（不抛），而且不用再去查掌握度。"""
    radar_calls: list[int] = []
    weak_tag_queries: list[int] = []

    class _BrokenRadar:
        @staticmethod
        async def get(user_id):
            radar_calls.append(user_id)
            raise RuntimeError("雷达挂了")

    async def fake_weak_tags(user_id):
        weak_tag_queries.append(user_id)
        return []

    monkeypatch.setattr(portrait_service, "PortraitRadarService", _BrokenRadar)
    monkeypatch.setattr(portrait_service, "_load_weak_knowledge_tags", fake_weak_tags)

    assert await portrait_service.build_learning_guidance(9) == ""
    assert radar_calls == [9]
    assert weak_tag_queries == [], "雷达都没有，还去查了一遍弱项知识点"


def test_the_renderer_is_a_pure_template():
    """渲染器没有任何 IO：雷达为空就给空串，一次库都不查、一次模型都不调。"""
    assert portrait_service._render_learning_guidance(None, ["甲"]) == ""
    assert portrait_service._render_learning_guidance({"dimensions": []}, ["甲"]) == ""

    guidance = portrait_service._render_learning_guidance(
        {"dimensions": [{"key": "memory", "score": 30}]}, ["甲", "乙"],
    )
    assert "弱项知识点优先出题：甲、乙" in guidance
