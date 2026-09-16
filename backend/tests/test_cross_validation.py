# -*- coding: utf-8 -*-
"""跨章节交叉验证（ConsistencyReviewer）。

补的是 reviewer_node 结构上看不到的那一层：它是**逐章节**审的
（generate_document_parallel 内部就是生成→审核→重生成），单节自洽但节与节
矛盾的内容，只有成稿级的交叉验证能发现。而"前后矛盾"正是幻觉最典型的表征。

编排上的关键约束（也是它从图末端节点搬进生成器内部的原因）：交叉验证必须跑在
文档被推送/落库**之前**。挂在图末端时，文档早已通过 resource_complete 交付并入库，
再修也改不了用户手里那一版 —— 检查跑了、产物没变，等于空转。现在它是
generate_document_parallel 收尾的一段：发现问题 → 带意见整章重修 → 复检。
"""

import json
import re
from types import SimpleNamespace

import pytest

from backend.src.ai_core import agent_names, resource_graph

TITLES = ("语义边界", "窗口重叠", "召回精度")

# 一致性审查提示词的固定抬头，用来把审查调用和正文调用分开。
CONSISTENCY_MARKER = "课程一致性审查专家"
CLEAN = '{"has_issues": false, "issues": []}'


def _document(*sections: tuple[str, str]) -> str:
    """按真实成稿的约定拼文档：# {topic} 作文档标题、## {小节} 作章节。"""
    body = "\n\n".join(f"## {title}\n\n{text}" for title, text in sections)
    return f"# 项目验证智能体的基础概念\n\n{body}\n"


def _two_sections() -> list[tuple[str, str]]:
    return resource_graph.split_document_sections(_document(("甲", "A。"), ("乙", "B。")))


class _FakeLlm:
    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    async def ainvoke(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.content)


class _BoomLlm:
    async def ainvoke(self, prompt, **_kwargs):
        raise RuntimeError("401 invalid api_key=secret-provider-detail")


class _DocLlm:
    """按 prompt 分流：一致性审查吃 JSON 脚本，正文吃章节内容。

    初稿和修订稿用不同措辞，这样"修复后的正文真的进了成稿"是可验证的，
    而不是只看事件流说了什么。
    """

    def __init__(self, consistency, *, boom: bool = False):
        self.consistency = [consistency] if isinstance(consistency, str) else list(consistency)
        self.boom = boom
        self.prompts: list[str] = []
        self.consistency_prompts: list[str] = []

    async def ainvoke(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        if CONSISTENCY_MARKER in prompt:
            self.consistency_prompts.append(prompt)
            if self.boom:
                raise RuntimeError("401 invalid api_key=secret-provider-detail")
            return SimpleNamespace(content=self.consistency.pop(0) if self.consistency else CLEAN)
        match = re.search(r"当前章节\n第 \d+/\d+ 章「([^」]+)」", prompt)
        assert match, "正文 prompt 应明确标识当前章节"
        title = match.group(1)
        draft = "修订稿" if "跨章节一致性检查发现以下问题" in prompt else "初稿"
        return SimpleNamespace(content=f"## {title}\n\n{draft}：{title}的正文。")


def _install(monkeypatch, llm):
    async def no_kb(*_args, **_kwargs):
        return "暂无相关知识库资料"

    monkeypatch.setattr(resource_graph, "llm", llm)
    monkeypatch.setattr(resource_graph, "kb_search", no_kb)


async def _generate(llm, monkeypatch, events=None, **kwargs):
    _install(monkeypatch, llm)
    return await resource_graph.generate_document_parallel(
        "文档切分",
        sections=list(TITLES),
        section_count=len(TITLES),
        user_id=7,
        stream_writer=events.append if events is not None else None,
        **kwargs,
    )


def _cross_events(events) -> list[dict]:
    return [event for event in events if event.get("agent_id") == "cross_validator"]


# ── 分节 ──────────────────────────────────────────────

def test_splits_real_document_into_sections():
    doc = _document(("语义边界", "按语义切。"), ("窗口重叠", "留重叠区。"), ("召回精度", "看召回。"))
    sections = resource_graph.split_document_sections(doc)
    assert [title for title, _ in sections] == ["语义边界", "窗口重叠", "召回精度"]
    assert sections[0][1] == "按语义切。"


def test_single_section_and_empty_documents_have_nothing_to_cross_check():
    assert resource_graph.split_document_sections("") == []
    assert resource_graph.split_document_sections("   ") == []
    # 真实成稿只有一个小节时，H1 标题不该被当成第二个"章节"
    assert resource_graph.split_document_sections("# 主题\n\n## 唯一小节\n正文。") == []


def test_preamble_before_the_first_section_is_kept():
    """H1 标题后面若还跟着成段正文，那是一段没有小标题的前言，不能丢。"""
    doc = "# 标题\n\n" + ("前言正文。" * 30) + "\n\n## 第一节\n甲。\n\n## 第二节\n乙。\n"
    sections = resource_graph.split_document_sections(doc)
    assert sections[0][0] == "前言"
    assert [title for title, _ in sections[1:]] == ["第一节", "第二节"]


# ── 审查器本体 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_reports_cross_section_issues(monkeypatch):
    payload = {
        "has_issues": True,
        "issues": [
            {"type": "符号", "sections": "第1节和第3节", "detail": "逆矩阵符号不一致"},
            {"type": "矛盾", "sections": "第2节和第4节", "detail": "对切分粒度说法相反"},
        ],
    }
    fake = _FakeLlm(json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(resource_graph, "llm", fake)

    issues = await resource_graph.review_cross_section_consistency(
        resource_graph.split_document_sections(_document(("甲", "A。"), ("乙", "B。"), ("丙", "C。"))),
        topic="文档切分",
        user_id=7,
    )

    assert [item["type"] for item in issues] == ["符号", "矛盾"]
    # 摘要要真的进了提示词，否则等于没查
    assert "甲" in fake.prompts[0] and "丙" in fake.prompts[0]


@pytest.mark.asyncio
async def test_clean_document_reports_no_issues(monkeypatch):
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm(CLEAN))

    assert await resource_graph.review_cross_section_consistency(_two_sections(), topic="t") == []


@pytest.mark.asyncio
async def test_model_failure_returns_none_instead_of_empty(monkeypatch):
    """None 和 [] 必须分得开：一次超时被当成"没问题"就等于静默漏检。"""
    monkeypatch.setattr(resource_graph, "llm", _BoomLlm())

    assert await resource_graph.review_cross_section_consistency(_two_sections(), topic="t") is None


@pytest.mark.asyncio
async def test_non_json_response_is_a_failure_not_a_pass(monkeypatch):
    """模型回一段散文（没按格式给 JSON）时，同样不能当成"通过"。"""
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm("抱歉，我无法完成这个任务。"))

    assert await resource_graph.review_cross_section_consistency(_two_sections(), topic="t") is None


@pytest.mark.asyncio
async def test_malformed_issues_payload_is_tolerated(monkeypatch):
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm('{"has_issues": true, "issues": "不是数组"}'))

    assert await resource_graph.review_cross_section_consistency(_two_sections(), topic="t") == []


@pytest.mark.asyncio
async def test_non_dict_issues_are_dropped(monkeypatch):
    """列表里混进字符串/数字时，过滤掉而不是让它们流到下游去拼反馈。"""
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm(json.dumps(
        {"has_issues": True, "issues": ["问题一", {"type": "矛盾", "detail": "说法相反"}, 7]},
        ensure_ascii=False,
    )))

    issues = await resource_graph.review_cross_section_consistency(_two_sections(), topic="t")

    assert issues == [{"type": "矛盾", "detail": "说法相反"}]


@pytest.mark.asyncio
async def test_issue_list_is_capped(monkeypatch):
    payload = {"has_issues": True, "issues": [{"type": "重复", "detail": f"第{i}条"} for i in range(12)]}
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm(json.dumps(payload, ensure_ascii=False)))

    issues = await resource_graph.review_cross_section_consistency(_two_sections(), topic="t")

    assert len(issues) == 5, "提示词要求最多 5 条，超出的要截掉"


@pytest.mark.asyncio
async def test_digest_is_truncated_so_a_huge_document_cannot_blow_up_the_prompt(monkeypatch):
    """成稿可能上万字，不能整篇塞进审查提示词。"""
    fake = _FakeLlm(CLEAN)
    monkeypatch.setattr(resource_graph, "llm", fake)

    sections = [(f"第{i}节", "长" * 5000) for i in range(20)]
    await resource_graph.review_cross_section_consistency(sections, topic="t")

    prompt = fake.prompts[0]
    # 每节只截前 N 字
    assert "长" * resource_graph._CONSISTENCY_SECTION_CHARS in prompt
    assert "长" * (resource_graph._CONSISTENCY_SECTION_CHARS + 1) not in prompt
    # 章节数封顶
    assert "第11节" in prompt
    assert "第12节" not in prompt, "超出上限的章节不该进提示词"
    # 标题必须留着：审查结论要能指名"第几节和第几节"，只给正文没法定位
    assert "### 第0节" in prompt


def test_consistency_feedback_names_the_problem_and_the_sections():
    feedback = resource_graph._consistency_feedback([
        {"type": "矛盾", "sections": "第1节和第3节", "detail": "对切分粒度说法相反"},
        {"sections": "第2节", "detail": "引用了未定义的符号"},
    ])

    assert "第1节和第3节" in feedback and "对切分粒度说法相反" in feedback
    assert "矛盾" in feedback
    assert "引用了未定义的符号" in feedback, "缺失 type 的问题也要带上正文"
    assert "重写本小节" in feedback, "要明确要求重写，不然模型只会回一句'已知悉'"


# ── 接入生成器：发现问题要真的改变产物 ────────────────

FOUND_ISSUES = json.dumps(
    {"has_issues": True, "issues": [
        {"type": "矛盾", "sections": "第1节和第3节", "detail": "对切分粒度说法相反"},
    ]},
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_generation_repairs_what_cross_validation_found(monkeypatch):
    """发现问题 → 带意见整章重修 → 复检。只报不改等于没跑。"""
    llm = _DocLlm([FOUND_ISSUES, CLEAN])
    events: list[dict] = []

    content = await _generate(llm, monkeypatch, events)

    assert len(llm.consistency_prompts) == 2, "改完必须复检，否则不知道修没修好"
    assert content.count("修订稿") == len(TITLES), "修复后的正文必须真的进了成稿"
    assert "初稿" not in content
    repair_prompts = [p for p in llm.prompts if "跨章节一致性检查发现以下问题" in p]
    assert len(repair_prompts) == len(TITLES), "跨章节问题定不到单节，得整章都重写"
    assert all("对切分粒度说法相反" in p for p in repair_prompts), "意见要原样喂进 prompt，不然等于让模型猜"
    assert all(f"## {title}" in content for title in TITLES)


@pytest.mark.asyncio
async def test_repair_after_cross_validation_is_reported_as_an_event(monkeypatch):
    events: list[dict] = []

    await _generate(_DocLlm([FOUND_ISSUES, CLEAN]), monkeypatch, events)

    cross = _cross_events(events)
    assert [event["status"] for event in cross] == ["reviewing", "done"]
    assert all(event["agent_name"] == agent_names.CROSS_VALIDATOR_AGENT for event in cross)
    assert cross[0]["sections"] == len(TITLES)
    assert cross[-1]["issue_count"] == 0
    assert "未再发现" in cross[-1]["message"]


@pytest.mark.asyncio
async def test_remaining_issues_after_repair_are_reported_not_hidden(monkeypatch):
    """复检还有问题：照样交付，但把剩余数报出来（留痕，不作废）。"""
    events: list[dict] = []

    content = await _generate(_DocLlm([FOUND_ISSUES, FOUND_ISSUES]), monkeypatch, events)

    assert content.startswith("# 文档切分")
    final = _cross_events(events)[-1]
    assert final["status"] == "retrying"
    assert final["issue_count"] == 1
    assert "1 处" in final["message"]


@pytest.mark.asyncio
async def test_clean_cross_validation_costs_one_call_and_no_repair(monkeypatch):
    llm = _DocLlm(CLEAN)

    content = await _generate(llm, monkeypatch)

    assert len(llm.consistency_prompts) == 1
    assert len(llm.prompts) == len(TITLES) + 1, "达标时不该多花重修轮"
    assert "修订稿" not in content
    assert all(f"## {title}" in content for title in TITLES)


@pytest.mark.asyncio
async def test_cross_validation_failure_does_not_break_generation(monkeypatch):
    """审查调用失败：跳过并留痕，文档照样交付。"""
    llm = _DocLlm(CLEAN, boom=True)
    events: list[dict] = []

    content = await _generate(llm, monkeypatch, events)

    assert "初稿" in content, "审查失败不该连带作废已经写好的文档"
    assert len(llm.prompts) == len(TITLES) + 1, "失败时不该触发重修轮"
    failed = [event for event in _cross_events(events) if event["status"] == "failed"]
    assert failed and failed[0]["message"] == "交叉验证未能完成，已跳过"
    # 供应商报错里常带 key，绝不能顺着事件流漏到前端
    assert "secret-provider-detail" not in json.dumps(events, ensure_ascii=False)


@pytest.mark.asyncio
async def test_single_section_document_never_calls_the_cross_validator(monkeypatch):
    """只有一个章节就没有"跨章节"可言，不该白花一次 LLM 调用。"""
    llm = _DocLlm(CLEAN)
    _install(monkeypatch, llm)

    await resource_graph.generate_document_parallel(
        "文档切分", sections=["唯一小节"], section_count=1, user_id=1,
    )

    assert llm.consistency_prompts == []


@pytest.mark.asyncio
async def test_skip_review_bypasses_cross_validation_too(monkeypatch):
    """路径节点流用 skip_review=True：整段绕过审核，交叉验证也一起绕过。"""
    llm = _DocLlm(CLEAN)

    content = await _generate(llm, monkeypatch, skip_review=True)

    assert llm.consistency_prompts == []
    assert len(llm.prompts) == len(TITLES)
    assert all(f"## {title}" in content for title in TITLES)


# ── 编排层 ────────────────────────────────────────────

def test_cross_validation_is_not_a_graph_node_anymore():
    """它必须跑在文档交付之前，所以搬进了生成器内部；图末端不能再挂一个。"""
    graph = resource_graph.resource_graph.get_graph()

    assert "cross_validator" not in set(graph.nodes), "末端那一遍改不了产物，是空转"
    edges = {(edge.source, edge.target, bool(edge.conditional)) for edge in graph.edges}
    assert ("reviewer", "__end__", True) in edges
    assert ("reviewer", "executor", True) in edges


def test_should_continue_still_owns_the_retry_decision():
    assert resource_graph.should_continue({"review_passed": True}) == "end"
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 0}) == "executor"
    # 重试上限：到 2 次就收手，不会无限循环
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 2}) == "end"
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 5}) == "end"


def test_should_review_still_bypasses_the_whole_review_stage():
    assert resource_graph.should_review({"skip_review": True}) == "end"
    assert resource_graph.should_review({"skip_review": False}) == "reviewer"
    assert resource_graph.should_review({}) == "reviewer"
