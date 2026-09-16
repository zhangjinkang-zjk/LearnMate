# -*- coding: utf-8 -*-
"""跨章节交叉验证（ConsistencyReviewer）。

补的是 reviewer_node 结构上看不到的那一层：它是**逐章节**审的
（generate_document_parallel 内部就是生成→审核→重生成），单节自洽但节与节
矛盾的内容，只有成稿级的交叉验证能发现。

同时覆盖编排层：条件边的走向、以及 skip_review 仍然整段绕过审核 + 交叉验证。
"""

import json
from types import SimpleNamespace

import pytest

from backend.src.ai_core import resource_graph


def _document(*sections: tuple[str, str]) -> str:
    """按真实成稿的约定拼文档：# {topic} 作文档标题、## {小节} 作章节。"""
    body = "\n\n".join(f"## {title}\n\n{text}" for title, text in sections)
    return f"# 项目验证智能体的基础概念\n\n{body}\n"


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


def _capture_events(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(resource_graph, "_safe_stream_writer", lambda: events.append)
    return events


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


# ── 节点行为 ──────────────────────────────────────────

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
    events = _capture_events(monkeypatch)

    state = {
        "topic": "文档切分",
        "user_id": 7,
        "generated_resources": {
            "document": _document(("甲", "A。"), ("乙", "B。"), ("丙", "C。")),
        },
    }
    result = await resource_graph.cross_validator_node(state)

    assert len(result["consistency_issues"]) == 2
    assert result["consistency_issues"][0]["type"] == "符号"
    # 摘要要真的进了提示词，否则等于没查
    assert "甲" in fake.prompts[0] and "丙" in fake.prompts[0]
    done = [e for e in events if e["agent_id"] == "cross_validator" and e["status"] == "retrying"]
    assert done and done[0]["issue_count"] == 2


@pytest.mark.asyncio
async def test_clean_document_reports_no_issues(monkeypatch):
    fake = _FakeLlm('{"has_issues": false, "issues": []}')
    monkeypatch.setattr(resource_graph, "llm", fake)
    events = _capture_events(monkeypatch)

    result = await resource_graph.cross_validator_node({
        "topic": "t",
        "user_id": 1,
        "generated_resources": {"document": _document(("甲", "A。"), ("乙", "B。"))},
    })

    assert result["consistency_issues"] == []
    assert [e for e in events if e["status"] == "done"]


@pytest.mark.asyncio
async def test_skips_without_calling_the_model_when_there_is_one_section(monkeypatch):
    fake = _FakeLlm('{"has_issues": true, "issues": [{"type": "x"}]}')
    monkeypatch.setattr(resource_graph, "llm", fake)
    events = _capture_events(monkeypatch)

    result = await resource_graph.cross_validator_node({
        "topic": "t",
        "user_id": 1,
        "generated_resources": {"document": "# 主题\n\n## 唯一小节\n正文。"},
    })

    assert result["consistency_issues"] == []
    assert fake.prompts == [], "章节不足时不该花一次 LLM 调用"
    assert [e for e in events if e["status"] == "skipped"]


@pytest.mark.asyncio
async def test_missing_or_empty_document_is_safe(monkeypatch):
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm("{}"))
    _capture_events(monkeypatch)

    for state in ({"topic": "t"}, {"topic": "t", "generated_resources": {}},
                  {"topic": "t", "generated_resources": {"document": None}}):
        assert (await resource_graph.cross_validator_node(state))["consistency_issues"] == []


@pytest.mark.asyncio
async def test_model_failure_does_not_break_generation_or_leak_details(monkeypatch):
    monkeypatch.setattr(resource_graph, "llm", _BoomLlm())
    events = _capture_events(monkeypatch)

    result = await resource_graph.cross_validator_node({
        "topic": "t",
        "user_id": 1,
        "generated_resources": {"document": _document(("甲", "A。"), ("乙", "B。"))},
    })

    assert result["consistency_issues"] == []
    failed = [e for e in events if e["status"] == "failed"]
    assert failed and "secret-provider-detail" not in json.dumps(failed, ensure_ascii=False)


@pytest.mark.asyncio
async def test_malformed_issues_payload_is_tolerated(monkeypatch):
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm('{"has_issues": true, "issues": "不是数组"}'))
    _capture_events(monkeypatch)

    result = await resource_graph.cross_validator_node({
        "topic": "t",
        "user_id": 1,
        "generated_resources": {"document": _document(("甲", "A。"), ("乙", "B。"))},
    })
    assert result["consistency_issues"] == []


@pytest.mark.asyncio
async def test_issue_list_is_capped(monkeypatch):
    payload = {"has_issues": True, "issues": [{"type": "重复", "detail": f"第{i}条"} for i in range(12)]}
    monkeypatch.setattr(resource_graph, "llm", _FakeLlm(json.dumps(payload, ensure_ascii=False)))
    _capture_events(monkeypatch)

    result = await resource_graph.cross_validator_node({
        "topic": "t",
        "user_id": 1,
        "generated_resources": {"document": _document(("甲", "A。"), ("乙", "B。"))},
    })
    assert len(result["consistency_issues"]) == 5, "提示词要求最多 5 条，超出的要截掉"


# ── 编排层 ────────────────────────────────────────────

def _edges() -> set[tuple[str, str, bool]]:
    graph = resource_graph.resource_graph.get_graph()
    return {(e.source, e.target, bool(e.conditional)) for e in graph.edges}


def test_cross_validator_is_wired_after_the_review_stage():
    edges = _edges()
    assert ("reviewer", "cross_validator", True) in edges, "审核判定结束后应进入交叉验证"
    assert ("cross_validator", "__end__", False) in edges, "交叉验证之后应结束"
    # 还要重生成时不该先做交叉验证（校验的是将被替换的内容）
    assert ("reviewer", "executor", True) in edges


def test_should_continue_still_owns_the_retry_decision():
    assert resource_graph.should_continue({"review_passed": True}) == "end"
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 0}) == "executor"
    # 重试上限：到 2 次就收手，不会无限循环
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 2}) == "end"
    assert resource_graph.should_continue({"review_passed": False, "retry_count": 5}) == "end"


def test_skip_review_still_bypasses_review_and_cross_validation():
    """路径节点流用的就是 skip_review=True —— 本次改动不改变它的行为。"""
    assert resource_graph.should_review({"skip_review": True}) == "end"
    assert resource_graph.should_review({"skip_review": False}) == "reviewer"
    assert resource_graph.should_review({}) == "reviewer"
