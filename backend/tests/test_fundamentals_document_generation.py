# -*- coding: utf-8 -*-
"""基础讲解文档生成的离线契约测试。"""

import json
import re
from types import SimpleNamespace

import pytest

from backend.src.ai_core import path_graph, resource_graph
from backend.src.service.path.teaching_context import (
    PATH_DEFAULT_RESOURCE_TYPES,
    attach_teaching_specs,
    compose_node_teaching_context,
    normalize_teaching_spec,
    teaching_spec_payload,
)
from backend.src.service.resource.document_quality import (
    validate_document_chapter,
    validate_document_section,
)


def _make_teaching_context() -> dict:
    return {
        "subject": "检索增强生成",
        "difficulty": "medium",
        "position": {"current": 2, "total": 3},
        "current": {
            "order_index": 2,
            "topic": "文档切分",
            "learning_goal": "能够解释切分粒度如何影响检索质量",
            "key_points": ["语义边界", "窗口重叠", "召回精度"],
            "teaching_spec": {
                "module": "检索准备",
                "cognitive_level": "应用",
                "learning_goal": "能够解释切分粒度如何影响检索质量",
                "key_points": ["语义边界", "窗口重叠", "召回精度"],
                "micro_example": "比较两个切分方案的召回结果",
            },
        },
        "previous": {
            "order_index": 1,
            "topic": "RAG 工作流",
            "learning_goal": "说出 RAG 的主要阶段",
            "key_points": ["索引", "检索", "生成"],
        },
        "next": {
            "order_index": 3,
            "topic": "向量检索",
            "learning_goal": "选择合适的相似度方法",
            "key_points": ["向量", "相似度"],
        },
        "covered_scope": [],
        "reserved_scope": [],
        "learner": {
            "major": "软件工程",
            "grade": "大二",
            "goal": "准备算法方向研究生复试",
        },
    }


def _valid_section(title: str) -> str:
    paragraph = (
        f"{title}需要同时观察语义边界、窗口重叠和召回精度。"
        "先按完整句子识别主题转折，再为相邻文本保留少量重叠，"
        "随后用同一组问题比较召回结果。这样可以把切分依据、操作步骤和验证指标连成闭环，"
        "也能发现块过大导致主题混杂、块过小导致上下文断裂的问题。"
    )
    return f"## {title}\n\n" + "\n\n".join(paragraph for _ in range(8))


def test_learning_path_default_resources_are_document_and_mindmap():
    assert PATH_DEFAULT_RESOURCE_TYPES == ("document", "mindmap")

    fallback_nodes = path_graph._fallback_group_nodes(
        [{"topic": "文档切分", "key_points": ["语义边界"]}],
        group_start=1,
    )

    assert fallback_nodes[0]["resource_types"] == ["document", "mindmap"]


@pytest.mark.parametrize("title", ["一元二次方程", "二叉树", "三角函数"])
def test_document_outline_normalization_preserves_titles_starting_with_chinese_numerals(title):
    sections = resource_graph._normalize_document_outline(
        [title],
        topic="数学与数据结构",
        count=1,
    )

    assert sections == [title]


def test_teaching_spec_normalizes_legacy_and_partially_persisted_nodes():
    legacy = normalize_teaching_spec(
        None,
        node={
            "topic": "文档切分",
            "description": "能够说明合理切分为什么改善召回",
            "knowledge_tags": ["语义边界", "语义边界", "窗口重叠"],
        },
    )

    assert legacy == {
        "module": "基础讲解",
        "cognitive_level": "理解",
        "learning_goal": "能够说明合理切分为什么改善召回",
        "key_points": ["语义边界", "窗口重叠"],
        "micro_example": "用一个具体例子说明「文档切分」解决了什么问题",
    }

    persisted = teaching_spec_payload(
        json.dumps(
            {
                "module": "检索准备",
                "cognitive_level": "应用",
                "key_points": "召回精度",
                "micro_example": "比较两种切分方案",
            },
            ensure_ascii=False,
        ),
        node={"topic": "文档切分", "description": "完成切分并验证结果"},
    )

    assert persisted["module"] == "检索准备"
    assert persisted["cognitive_level"] == "应用"
    assert persisted["learning_goal"] == "完成切分并验证结果"
    assert persisted["key_points"] == ["召回精度"]
    assert persisted["micro_example"] == "比较两种切分方案"


def test_teaching_specs_prefer_topic_match_when_executor_reorders_nodes():
    outline = [
        {
            "topic": "向量检索",
            "learning_goal": "能够比较常用相似度方法",
            "key_points": ["余弦相似度"],
        },
        {
            "topic": "文档切分",
            "learning_goal": "能够选择合适的切分粒度",
            "key_points": ["语义边界"],
        },
    ]
    executor_nodes = [
        {"order_index": 1, "topic": "文档切分"},
        {"order_index": 2, "topic": "向量检索"},
    ]

    nodes = attach_teaching_specs(executor_nodes, outline)

    assert nodes[0]["teaching_spec"]["learning_goal"] == "能够选择合适的切分粒度"
    assert nodes[0]["teaching_spec"]["key_points"] == ["语义边界"]
    assert nodes[1]["teaching_spec"]["learning_goal"] == "能够比较常用相似度方法"
    assert nodes[1]["teaching_spec"]["key_points"] == ["余弦相似度"]


def test_compose_teaching_context_includes_path_neighbors_and_learner():
    path = SimpleNamespace(subject="检索增强生成", difficulty="medium")
    nodes = [
        SimpleNamespace(
            order_index=1,
            topic="RAG 工作流",
            knowledge_tags=json.dumps(["索引", "检索", "生成"], ensure_ascii=False),
            teaching_spec=None,
        ),
        SimpleNamespace(
            order_index=2,
            topic="文档切分",
            knowledge_tags=json.dumps(["语义边界", "窗口重叠"], ensure_ascii=False),
            teaching_spec=json.dumps(
                {
                    "module": "检索准备",
                    "cognitive_level": "应用",
                    "learning_goal": "能够比较不同切分策略",
                    "key_points": ["语义边界", "窗口重叠"],
                    "micro_example": "比较两段文本的切分结果",
                },
                ensure_ascii=False,
            ),
        ),
        SimpleNamespace(
            order_index=3,
            topic="向量检索",
            knowledge_tags=json.dumps(["向量", "相似度"], ensure_ascii=False),
            teaching_spec=None,
        ),
    ]
    learner = {"major": "软件工程", "grade": "大二", "goal": "准备算法复试"}

    context = compose_node_teaching_context(path, nodes[1], nodes, learner)

    assert context["subject"] == "检索增强生成"
    assert context["current"]["topic"] == "文档切分"
    assert context["current"]["teaching_spec"]["learning_goal"] == "能够比较不同切分策略"
    assert context["previous"]["topic"] == "RAG 工作流"
    assert context["next"]["topic"] == "向量检索"
    assert [item["topic"] for item in context["covered_scope"]] == ["RAG 工作流"]
    assert [item["topic"] for item in context["reserved_scope"]] == ["向量检索"]
    assert context["learner"] == learner


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("", "文档内容为空"),
        ("# 文档切分\n\n## 语义边界\n\n待补充", "文档包含省略或待补充占位语"),
        ("# 文档切分\n\n## 语义边界\n\n简短说明", "文档有效内容不足 900 字符"),
    ],
)
def test_document_quality_gate_rejects_empty_placeholder_and_short_content(
    content,
    expected_error,
):
    errors = validate_document_chapter(content, _make_teaching_context())

    assert expected_error in errors


def test_document_quality_gate_accepts_a_complete_chapter():
    content = "# 文档切分\n\n" + "\n\n".join(
        _valid_section(title)
        for title in ("语义边界", "窗口重叠", "召回精度")
    )

    assert validate_document_chapter(content, _make_teaching_context()) == []
    assert validate_document_section(_valid_section("语义边界"), "语义边界") == []


def test_document_quality_gate_allows_failure_analysis_as_a_real_topic():
    content = _valid_section("生成失败：常见原因与排查")

    assert validate_document_section(content, "生成失败：常见原因与排查") == []


def test_markdown_cleanup_preserves_a_real_code_block_at_the_end():
    section = _valid_section("Python 示例") + "\n\n```python\nprint('LearnMate')\n```"

    assert resource_graph._strip_outer_markdown_fence(section) == section
    assert validate_document_section(section, "Python 示例") == []


def test_markdown_cleanup_removes_only_a_complete_response_wrapper():
    wrapped = "```markdown\n## 语义边界\n\n完整解释。\n```"

    assert resource_graph._strip_outer_markdown_fence(wrapped) == "## 语义边界\n\n完整解释。"


@pytest.mark.asyncio
async def test_document_outline_prompt_contains_teaching_contract_and_learner_goal(monkeypatch):
    prompts = []

    class FakeLlm:
        async def ainvoke(self, prompt, **kwargs):
            prompts.append(prompt)
            return SimpleNamespace(
                content='["切分要解决的检索问题", "语义边界与窗口重叠", "召回结果迁移检查"]'
            )

    monkeypatch.setattr(resource_graph, "llm", FakeLlm())
    teaching_context = _make_teaching_context()

    sections = await resource_graph.generate_doc_outline(
        "文档切分",
        kb="内部资料强调按语义边界切分。",
        guidance="用可核验的对比例子解释。",
        count=3,
        portrait="软件工程专业大二学生",
        user_notes="重点比较块大小。",
        teaching_context=teaching_context,
    )

    assert sections == ["切分要解决的检索问题", "语义边界与窗口重叠", "召回结果迁移检查"]
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "完整主讲文档" in prompt
    assert "小节" in prompt
    assert "检索增强生成" in prompt
    assert "能够解释切分粒度如何影响检索质量" in prompt
    assert "软件工程专业大二学生" in prompt
    assert "准备算法方向研究生复试" in prompt
    assert "向量检索" in prompt


@pytest.mark.asyncio
async def test_generic_document_outline_does_not_receive_path_contract(monkeypatch):
    prompts = []

    class FakeLlm:
        async def ainvoke(self, prompt, **kwargs):
            prompts.append(prompt)
            return SimpleNamespace(content='["问题背景", "核心原理", "完整示例"]')

    monkeypatch.setattr(resource_graph, "llm", FakeLlm())

    sections = await resource_graph.generate_doc_outline(
        "操作系统调度",
        count=3,
        portrait="计算机专业学生",
    )

    assert sections == ["问题背景", "核心原理", "完整示例"]
    assert "完整学习文档" in prompts[0]
    assert "路径节点教学契约" not in prompts[0]
    assert "covered_scope" not in prompts[0]
    assert "reserved_scope" not in prompts[0]


def test_generic_document_body_uses_general_resource_prompt():
    prompt = resource_graph.build_resource_prompt(
        "document",
        "操作系统调度",
        portrait="计算机专业学生",
        section="时间片轮转",
    )

    assert "专业的学习文档生成器" in prompt
    assert "路径节点教学契约" not in prompt
    assert "当前小节：" not in prompt


def test_custom_document_prompt_keeps_standard_path_teaching_contract():
    teaching_context = _make_teaching_context()

    prompt = resource_graph.build_resource_prompt(
        "document",
        "文档切分",
        portrait="软件工程专业大二学生",
        guidance="用可核验的对比例子解释。",
        user_notes="重点比较块大小。",
        custom_prompts={
            "document": "自定义风格：围绕 {topic}，结合 {portrait_context}，通过连续追问引导学习者。"
        },
        section="语义边界",
        teaching_context=teaching_context,
        section_index=1,
        section_total=3,
        previous_section="RAG 工作流",
        next_section="窗口重叠",
        document_outline="第1节「语义边界」\n第2节「窗口重叠」\n第3节「召回精度」",
    )

    assert "自定义风格：围绕 文档切分，结合 软件工程专业大二学生" in prompt
    assert "{topic}" not in prompt
    assert "{portrait_context}" not in prompt
    assert "路径节点教学契约" in prompt
    assert "当前小节" in prompt
    assert "前一小节" in prompt
    assert "后一小节" in prompt
    assert "能够解释切分粒度如何影响检索质量" in prompt
    assert "软件工程专业大二学生" in prompt
    assert "准备算法方向研究生复试" in prompt


@pytest.mark.asyncio
async def test_document_section_prompts_use_teaching_context_and_call_nodes_sections(monkeypatch):
    prompts = []
    section_titles = ("语义边界", "窗口重叠", "召回精度")

    class FakeLlm:
        async def ainvoke(self, prompt, **kwargs):
            prompts.append(prompt)
            match = re.search(r"当前小节：第 \d+/\d+ 节「([^」]+)」", prompt)
            assert match, "正文 prompt 应明确标识当前小节"
            title = match.group(1)
            return SimpleNamespace(content=_valid_section(title))

    async def fake_kb_search(*args, **kwargs):
        return "暂无相关知识库资料"

    monkeypatch.setattr(resource_graph, "llm", FakeLlm())
    monkeypatch.setattr(resource_graph, "kb_search", fake_kb_search)
    teaching_context = _make_teaching_context()

    content = await resource_graph.generate_document_parallel(
        "文档切分",
        portrait="软件工程专业大二学生",
        guidance="用可核验的对比例子解释。",
        user_notes="重点比较块大小。",
        sections=list(section_titles),
        section_count=len(section_titles),
        teaching_context=teaching_context,
        user_id=7,
    )

    assert len(prompts) == len(section_titles)
    assert validate_document_chapter(content, teaching_context) == []
    for prompt in prompts:
        assert "当前小节" in prompt
        assert "前一小节" in prompt
        assert "后一小节" in prompt
        assert "检索增强生成" in prompt
        assert "能够解释切分粒度如何影响检索质量" in prompt
        assert "软件工程专业大二学生" in prompt
        assert "准备算法方向研究生复试" in prompt
