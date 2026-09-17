# -*- coding: utf-8 -*-
"""目标节点数必须真的被执行，而不是当"建议"。

改之前，节点数在**四个地方连续被削弱**，而且每一处都不留痕迹：

1. `leader.yaml` 措辞是"建议节点数"，且"3-6 个模块、每个模块 2-6 个节点"把下限压到 6
2. `_normalize_topic_outline` 到 `node_count` 就 break —— 大纲短了就短了，不补
3. `node_count = max(1, min(node_count, len(topic_outline)))` —— **取 min**，只能缩
4. executor 只判"返回的是不是非空列表"，一组要 4 个只回 1 个会被直接采纳

库里因此同时存在 6 节点和 18 节点的路径。这个文件钉住"补足"和"少给要重试"两条。
"""

import json
from types import SimpleNamespace

import pytest

from backend.src.ai_core import path_graph


def _topic(name: str) -> dict:
    return {
        "topic": name,
        "module": "模块",
        "cognitive_level": "理解",
        "learning_goal": f"掌握{name}",
        "key_points": [name],
        "micro_example": f"{name} 的小例子",
    }


def _outline(count: int, prefix: str = "T") -> list[dict]:
    return [path_graph._normalize_topic_outline([_topic(f"{prefix}{i}") for i in range(1, count + 1)], "测试")[i - 1]
            for i in range(1, count + 1)]


def _node(topic: str, order: int) -> dict:
    return {
        "topic": topic,
        "order_index": order,
        "knowledge_tags": [topic],
        "prerequisites": [],
        "resource_types": ["document"],
        "quiz_config": {"count": 5, "threshold": 0.7},
        "description": f"{topic} 的说明",
    }


class _FakeLlm:
    """按顺序吐出预设内容；用完了就一直重复最后一条。"""

    def __init__(self, *responses):
        self._responses = list(responses) or ["[]"]
        self.prompts: list[str] = []

    async def ainvoke(self, prompt, **kwargs):
        self.prompts.append(prompt)
        content = self._responses[0] if len(self._responses) == 1 else self._responses.pop(0)
        return SimpleNamespace(content=content)


# ═══════════════════════════════════════
#  executor：一组该给几个就必须给几个
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_a_short_group_is_retried_first(monkeypatch):
    """一组要 4 个只回 1 个是"没完成"，不是"完成" —— 原来会被直接采纳。"""
    llm = _FakeLlm(json.dumps([_node("T1", 1)], ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.executor_node({
        "subject": "测试", "topic_outline": _outline(4), "user_id": "1",
    })

    assert len(llm.prompts) == 2, "少于应得数量必须重试一次"
    assert len(result["nodes"]) == 4, "重试后仍不足，要补足到计划的数量"


@pytest.mark.asyncio
async def test_a_short_group_keeps_what_the_agent_did_give(monkeypatch):
    """补的是"计划里有、它没给"的那些主题，不是把它的产出整组丢掉。"""
    llm = _FakeLlm(json.dumps([_node("T2", 2)], ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.executor_node({
        "subject": "测试", "topic_outline": _outline(4), "user_id": "1",
    })

    by_topic = {node["topic"]: node for node in result["nodes"]}
    assert set(by_topic) == {"T1", "T2", "T3", "T4"}
    assert by_topic["T2"]["description"] == "T2 的说明", "智能体给的那条要保留原样"


@pytest.mark.asyncio
async def test_a_complete_group_is_accepted_without_retrying(monkeypatch):
    llm = _FakeLlm(json.dumps([_node(f"T{i}", i) for i in range(1, 5)], ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.executor_node({
        "subject": "测试", "topic_outline": _outline(4), "user_id": "1",
    })

    assert len(llm.prompts) == 1
    assert len(result["nodes"]) == 4


# ── 合并规则本身 ──────────────────────────────────────

def test_merging_keeps_everything_the_agent_produced():
    group = _outline(4)

    merged = path_graph._merge_with_fallback(group, [_node("T1", 1), _node("T2", 2)], 1)

    assert [node["topic"] for node in merged] == ["T1", "T2", "T3", "T4"]
    assert merged[0]["description"] == "T1 的说明"


def test_merging_nothing_produced_equals_the_plain_fallback():
    group = _outline(3)

    assert path_graph._merge_with_fallback(group, [], 1) == path_graph._fallback_group_nodes(group, 1)


def test_merging_never_truncates_a_longer_answer():
    """智能体多给了不该被砍 —— 它可能确实多规划出了内容。"""
    group = _outline(2)

    merged = path_graph._merge_with_fallback(group, [_node("T1", 1), _node("T2", 2), _node("T3", 3)], 1)

    assert len(merged) == 3


def test_merging_matches_by_topic_not_by_position():
    """智能体可能重排顺序，靠 topic 判断"哪些还没有"，不能靠下标。"""
    group = _outline(3)

    merged = path_graph._merge_with_fallback(group, [_node("T3", 3)], 1)

    assert sorted(node["topic"] for node in merged) == ["T1", "T2", "T3"]
    assert [node["order_index"] for node in merged] == [1, 2, 3], "合并后要按 order_index 排回来"


# ═══════════════════════════════════════
#  leader：大纲不足目标数要补
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_a_short_outline_is_expanded_to_the_target(monkeypatch):
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("C"), _topic("D")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")], "node_count": 2}, ensure_ascii=False),
        {"subject": "测试", "node_count": 4, "user_id": "1"},
    )

    assert result["node_count"] == 4
    assert [item["topic"] for item in result["topic_outline"]] == ["A", "B", "C", "D"]


@pytest.mark.asyncio
async def test_the_expansion_prompt_lists_the_topics_it_must_not_repeat(monkeypatch):
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("C")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 3, "user_id": "1"},
    )

    assert "A" in llm.prompts[0] and "B" in llm.prompts[0], "要把已有的主题给它，否则会补重复的"
    assert "不要重复" in llm.prompts[0]


@pytest.mark.asyncio
async def test_expansion_does_not_duplicate_topics(monkeypatch):
    """补全又给了已有的主题：去重之后仍然不足，但不能出现重复节点。"""
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("A")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 4, "user_id": "1"},
    )

    topics = [item["topic"] for item in result["topic_outline"]]
    assert topics == ["A", "B"], "补不动就按实际长度收，但不能重复"
    assert result["node_count"] == 2


@pytest.mark.asyncio
async def test_a_failed_expansion_still_returns_the_outline(monkeypatch):
    class _Boom:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("补全调用失败")

    monkeypatch.setattr(path_graph, "llm", _Boom())

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 6, "user_id": "1"},
    )

    assert [item["topic"] for item in result["topic_outline"]] == ["A", "B"], "补不动也不能把已有大纲弄丢"


@pytest.mark.asyncio
async def test_a_completed_outline_is_not_expanded(monkeypatch):
    """大纲已经够了就不该多打一次 LLM。"""
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("C")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 2, "user_id": "1"},
    )

    assert llm.prompts == []


@pytest.mark.asyncio
async def test_a_longer_outline_is_truncated_to_the_target(monkeypatch):
    llm = _FakeLlm("[]")
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic(name) for name in "ABCDE"]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 3, "user_id": "1"},
    )

    assert result["node_count"] == 3
    assert [item["topic"] for item in result["topic_outline"]] == ["A", "B", "C"]


# ═══════════════════════════════════════
#  自动模式（没有服务端目标）保持原语义
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_auto_mode_still_trusts_the_models_own_count(monkeypatch):
    """目标为 0 时由模型自报，再按大纲长度夹紧 —— 这条老行为不能被顺手改掉。"""
    llm = _FakeLlm("[]")
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A"), _topic("B")], "node_count": 15}, ensure_ascii=False),
        {"subject": "测试", "node_count": 0, "user_id": "1"},
    )

    assert result["node_count"] == 2, "自报 15 但大纲只有 2 个 → 夹到 2"
    assert llm.prompts == [], "自动模式不该触发补全"


@pytest.mark.asyncio
async def test_auto_mode_does_not_expand_even_when_short(monkeypatch):
    """没有目标数就没有"不足"可言 —— 不该凭空多打一轮 LLM。"""
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("C")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A")]}, ensure_ascii=False),
        {"subject": "测试", "node_count": 0, "user_id": "1"},
    )

    assert llm.prompts == []
    assert result["node_count"] == 1


@pytest.mark.asyncio
async def test_an_empty_outline_still_uses_the_local_fallback(monkeypatch):
    llm = _FakeLlm("[]")
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.parse_or_repair_leader_result(
        "完全不是 JSON",
        {"subject": "测试", "node_count": 12, "user_id": "1"},
        retry_llm=False,
    )

    assert result["node_count"] == 12, "兜底大纲本来就会凑到目标数"


# ═══════════════════════════════════════
#  模型偏离 schema 时不能把内容丢掉
# ═══════════════════════════════════════

def test_a_string_array_is_recovered_instead_of_thrown_away():
    """模型有时直接给主题名数组。

    原来 `isinstance(item, dict)` 一票否决，整份大纲归零 → 换成本地模板 ——
    模型明明给了能用的主题，用户拿到的却是一条模板路径。实测 65 条路径里 11 条
    的节点主题就是模板货，但当时没法知道是哪一种丢法。
    """
    outline = path_graph._normalize_topic_outline(["梯度下降", "反向传播"], "深度学习", 2)

    assert [item["topic"] for item in outline] == ["梯度下降", "反向传播"]


def test_broken_items_do_not_sink_the_whole_outline():
    outline = path_graph._normalize_topic_outline(
        [{"topic": "好的主题"}, "字符串主题", 123, None, {"no_topic_field": 1}], "测试", 0
    )

    assert [item["topic"] for item in outline] == ["好的主题", "字符串主题"]


@pytest.mark.parametrize("raw, expected_fragment", [
    (None, "调用失败"),
    ("不是数组", "不是数组"),
    ([], "空数组"),
    ([123, None], "无法识别的类型"),
    ([{"module": "只有模块名"}], "没有 topic/title"),
    ([{"topic": "A"}, {"topic": "A"}], "全部重复或为空"),
])
def test_the_rejection_reason_says_which_case_it_was(raw, expected_fragment):
    """原来只有一句"topic_outline 为空"，四种丢法长得一模一样。"""
    assert expected_fragment in path_graph._outline_rejection_reason(raw)


@pytest.mark.asyncio
async def test_the_fallback_log_says_why_and_shows_the_raw_value(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(path_graph, "llm", _FakeLlm("[]"))
    with caplog.at_level(logging.WARNING):
        await path_graph.parse_or_repair_leader_result(
            json.dumps({"topic_outline": [{"module": "模型只给了模块名"}]}, ensure_ascii=False),
            {"subject": "测试", "node_count": 8, "user_id": "1"},
        )

    message = next(r.getMessage() for r in caplog.records if "兜底大纲" in r.getMessage())
    assert "没有 topic/title" in message, message
    assert "模型只给了模块名" in message, "要带上原始片段，否则下次还是只能靠查库反推"


@pytest.mark.asyncio
async def test_the_result_says_whether_the_outline_came_from_the_agent(monkeypatch):
    monkeypatch.setattr(path_graph, "llm", _FakeLlm("[]"))

    degraded = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": []}), {"subject": "测试", "node_count": 8, "user_id": "1"}
    )
    healthy = await path_graph.parse_or_repair_leader_result(
        json.dumps({"topic_outline": [_topic("A")]}), {"subject": "测试", "node_count": 1, "user_id": "1"}
    )

    assert degraded["outline_source"] == "fallback"
    assert healthy["outline_source"] == "agent"


# ═══════════════════════════════════════
#  规划器要重试，不能一次失败就接受模板
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_the_leader_retries_instead_of_accepting_the_template_outline(monkeypatch):
    """executor 一直有重试，规划器一次都没有 —— 一次瞬时失败 = 整条路径变模板。"""
    llm = _FakeLlm(
        json.dumps({"topic_outline": []}),  # 第 1 次：合法 JSON 但没大纲
        json.dumps({"topic_outline": [_topic("真实主题一"), _topic("真实主题二")]}, ensure_ascii=False),
    )
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.leader_node({
        "subject": "测试", "difficulty": "medium", "node_count": 2, "user_id": "1",
    })

    assert len(llm.prompts) == 2, "第一次退到模板就该重试"
    assert result["outline_source"] == "agent"
    assert result["topic_outline"][0]["topic"] == "真实主题一"


@pytest.mark.asyncio
async def test_the_leader_accepts_degrades_only_after_retrying(monkeypatch):
    """两次都拿不到就接受模板，但不能崩、也不能一直重试下去。"""
    llm = _FakeLlm(json.dumps({"topic_outline": []}))
    monkeypatch.setattr(path_graph, "llm", llm)

    result = await path_graph.leader_node({
        "subject": "测试", "difficulty": "medium", "node_count": 8, "user_id": "1",
    })

    assert len(llm.prompts) == path_graph._LEADER_ATTEMPTS
    assert result["outline_source"] == "fallback"
    assert result["topic_outline"], "退化也要给出可用的模板大纲"


@pytest.mark.asyncio
async def test_the_leader_does_not_retry_a_healthy_outline(monkeypatch):
    llm = _FakeLlm(json.dumps({"topic_outline": [_topic("A")]}, ensure_ascii=False))
    monkeypatch.setattr(path_graph, "llm", llm)

    await path_graph.leader_node({
        "subject": "测试", "difficulty": "medium", "node_count": 1, "user_id": "1",
    })

    assert len(llm.prompts) == 1


# ═══════════════════════════════════════
#  兜底大纲：不能出现重名节点
# ═══════════════════════════════════════

def test_the_fallback_outline_never_repeats_a_topic():
    """模板只有 12 条，循环时必须换名字。

    原来是 `templates[index % 12]`，目标 15-18 时后半段和前段**同名** —— 实测 65 条
    路径里有 10 条带着重复的节点主题（path 68：「LangChain 编排与服务部署：学习目标与
    知识地图」出现两次）。而 `_normalize_topic_outline` 是会去重的，兜底大纲却绕过了
    它直接入库，所以重复一路留到了用户面前。
    """
    topics = [item["topic"] for item in path_graph._fallback_topic_outline("测试", 18)]

    assert len(topics) == 18
    assert len(set(topics)) == 18, f"出现了重复主题：{[t for t in topics if topics.count(t) > 1]}"


def test_the_fallback_outline_stays_unique_well_past_its_templates():
    topics = [item["topic"] for item in path_graph._fallback_topic_outline("测试", 45)]

    assert len(topics) == len(set(topics))


def test_the_fallback_outline_caps_at_eighteen_and_says_so(caplog):
    """封顶本身是个一直存在但没人看见的天花板 —— 至少要在日志里说出来。"""
    import logging

    with caplog.at_level(logging.WARNING):
        outline = path_graph._fallback_topic_outline("测试", 40)

    assert len(outline) == 18
    assert any("封顶" in record.message for record in caplog.records), caplog.text


def test_the_fallback_outline_does_not_warn_when_it_fits(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        outline = path_graph._fallback_topic_outline("测试", 12)

    assert len(outline) == 12
    assert not [record for record in caplog.records if "封顶" in record.message]
