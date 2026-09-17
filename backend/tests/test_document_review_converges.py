# -*- coding: utf-8 -*-
"""文档审核不达标时必须"继续改进"，而不是"直接中断"。

对应的问题现象：审核阶段一旦发现错误，任务就被判死，同一批已经生成好的
PPT / 思维导图跟着一起作废，用户侧表现成任务凭空中断。

这里钉住三条契约：
  1. 文档生成**不抛异常**：单节重写用尽 → 尽力稿或确定性兜底；整章校验不达标 →
     带意见重修一轮 → 仍不达标也照样发出，只留痕。
  2. 兜底稿不含占位语，否则复用校验会把它判成坏内容，导致每次进章节重新生成。
  3. 并行分支互不拖累：文档分支炸了，PPT 分支的产出仍然交付。
"""

import json
from types import SimpleNamespace

import pytest

from backend.src.ai_core import resource_graph
from backend.src.service.resource.document_quality import validate_document_chapter


def _teaching_context() -> dict:
    return {
        "subject": "检索增强生成",
        "current": {
            "topic": "文档切分",
            "learning_goal": "能够解释切分粒度如何影响检索质量",
            "key_points": ["语义边界", "窗口重叠", "召回精度"],
            "teaching_spec": {"key_points": ["语义边界", "窗口重叠", "召回精度"]},
        },
    }


def _section(title: str, repeats: int = 8) -> str:
    """一节结构合法的正文：有 `##` 标题、有足够字数、不含占位语。"""
    body = (
        f"{title}需要同时观察语义边界、窗口重叠和召回精度。先按完整句子识别主题转折，"
        "再为相邻文本保留少量重叠，随后用同一组问题比较召回结果，"
        "这样可以把切分依据、操作步骤和验证指标连成闭环。"
    )
    return f"## {title}\n\n" + "\n\n".join(body for _ in range(repeats))


def _short_section(title: str) -> str:
    """一节自己合格（≥180 字），但三节加起来够不到整章 900 字的下限。"""
    body = (
        f"{title}讨论的是切分粒度与召回之间的关系。先识别完整句子的边界，"
        "再为相邻文本保留少量重叠，最后用同一组问题比较两种切分方案的召回结果。"
    )
    return f"## {title}\n\n" + "\n\n".join(body for _ in range(3))


class _FailingLlm:
    """永远返回同一份不达标内容，并记录每次调用时拼出来的 prompt。"""

    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    async def ainvoke(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.content)


class _ScriptedLlm:
    """按调用次序返回不同内容；脚本用尽就复用最后一条，并记下超出的调用。"""

    def __init__(self, contents: list[str]):
        self.contents = list(contents)
        self.prompts: list[str] = []

    async def ainvoke(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        if not self.contents:
            raise AssertionError(f"脚本外多调了一次模型，第 {len(self.prompts)} 次")
        return SimpleNamespace(content=self.contents.pop(0))


async def _no_kb(*_args, **_kwargs):
    return "暂无相关知识库资料"


def _install(monkeypatch, llm):
    monkeypatch.setattr(resource_graph, "llm", llm)
    monkeypatch.setattr(resource_graph, "kb_search", _no_kb)


TITLES = ("语义边界", "窗口重叠", "召回精度")

# 文档生成收尾会固定多花一次 LLM 调用做跨章节交叉验证（ConsistencyReviewer）。
# 脚本化 LLM 在脚本外用尽就抛，所以凡是不传 skip_review=True 的用例都要给它留一条。
_NO_CONSISTENCY_ISSUES = '{"has_issues": false, "issues": []}'


# ── 单节重写用尽 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_section_failure_degrades_to_fallback_instead_of_raising(monkeypatch):
    """每一节都写不出合格内容时，仍然交付一份可用的文档，而不是抛异常。"""
    events: list[dict] = []
    # 「待补充」既是小节级硬失败，也是整章级的占位语失败。
    _install(monkeypatch, _FailingLlm("## 语义边界\n\n待补充"))

    content = await resource_graph.generate_document_parallel(
        "文档切分",
        sections=list(TITLES),
        section_count=len(TITLES),
        teaching_context=_teaching_context(),
        user_id=7,
        stream_writer=events.append,
    )

    assert content.startswith("# 文档切分")
    assert validate_document_chapter(content, _teaching_context()) == [], "兜底稿必须能通过整章校验"
    # 兜底不是"占位"，而是真写出来的内容
    assert "待补充" not in content
    assert all(f"## {title}" in content for title in TITLES)
    done = [e for e in events if e.get("agent_id") == "executor:document" and e.get("status") == "done"]
    assert done, "文档分支最终应以 done 收尾，而不是 failed"


@pytest.mark.asyncio
async def test_section_keeps_best_effort_draft_when_content_is_merely_weak(monkeypatch):
    """内容只是"不完美"（标题层级写成三级）时保留原稿，不用兜底顶掉真实内容。"""
    weak = "### 语义边界\n\n" + ("这一节讨论切分粒度与召回的关系。" * 30)
    _install(monkeypatch, _FailingLlm(weak))

    content = await resource_graph.generate_document_parallel(
        "文档切分",
        sections=["语义边界"],
        section_count=1,
        teaching_context=_teaching_context(),
        user_id=7,
    )

    assert "这一节讨论切分粒度与召回的关系。" in content, "真实内容不该被兜底覆盖"
    assert "## 语义边界" in content, "三级标题应被提升为二级，否则整章会被判成小节不足"


def test_section_heading_promotion_only_touches_a_leading_h3():
    assert resource_graph._promote_section_heading("### 甲\n\n正文") == "## 甲\n\n正文"
    assert resource_graph._promote_section_heading("## 甲\n\n正文") == "## 甲\n\n正文"
    assert resource_graph._promote_section_heading("#### 甲\n\n正文") == "#### 甲\n\n正文"
    assert resource_graph._promote_section_heading("正文\n\n### 甲") == "正文\n\n### 甲"


# ── 整章校验：先改进，再接受 ──────────────────────────

@pytest.mark.asyncio
async def test_chapter_validation_triggers_a_repair_round_that_converges(monkeypatch):
    """整章不达标 → 带着校验意见重修一轮 → 修好就交付，不再作废。"""
    llm = _ScriptedLlm([
        *(_short_section(t) for t in TITLES),   # 首轮：每节都合格，但整章够不到 900 字
        *(_section(t) for t in TITLES),          # 重修轮：一次修好
        _NO_CONSISTENCY_ISSUES,                  # 收尾的跨章节交叉验证
    ])
    _install(monkeypatch, llm)

    content = await resource_graph.generate_document_parallel(
        "文档切分",
        sections=list(TITLES),
        section_count=len(TITLES),
        teaching_context=_teaching_context(),
        user_id=7,
    )

    assert validate_document_chapter(content, _teaching_context()) == []
    assert len(llm.prompts) == 2 * len(TITLES) + 1, "应为 1 轮首轮 + 1 轮重修 + 1 次交叉验证"
    # 重修意见在第 2 批 prompt 里；最后一条已经是交叉验证了。
    assert "整章校验未通过" in llm.prompts[len(TITLES)], "重修必须带着校验意见，否则等于白重写"


@pytest.mark.asyncio
async def test_chapter_still_failing_is_reported_not_fatal(monkeypatch):
    """重修一轮仍不达标：照样返回内容，用 done + 提示留痕，不抛异常。"""
    events: list[dict] = []
    llm = _ScriptedLlm([
        *(_short_section(t) for t in TITLES),
        *(_short_section(t) for t in TITLES),
        _NO_CONSISTENCY_ISSUES,
    ])
    _install(monkeypatch, llm)

    content = await resource_graph.generate_document_parallel(
        "文档切分",
        sections=list(TITLES),
        section_count=len(TITLES),
        teaching_context=_teaching_context(),
        user_id=7,
        stream_writer=events.append,
    )

    assert content.startswith("# 文档切分")
    assert validate_document_chapter(content, _teaching_context()) != [], "这份稿子确实还不达标"
    # 但它是"还行但可以更好"，不是"坏到不能给学生看"
    assert resource_graph.validate_document_safety(content) == []
    final = [e for e in events if e.get("agent_id") == "executor:document"][-1]
    assert final["status"] == "done"
    assert "待改进" in final["message"]


@pytest.mark.asyncio
async def test_clean_document_never_spends_a_repair_round(monkeypatch):
    llm = _ScriptedLlm([_section(t) for t in TITLES] + [_NO_CONSISTENCY_ISSUES])
    _install(monkeypatch, llm)

    await resource_graph.generate_document_parallel(
        "文档切分",
        sections=list(TITLES),
        section_count=len(TITLES),
        teaching_context=_teaching_context(),
        user_id=7,
    )

    # 每节一次生成 + 收尾一次跨章节交叉验证，没有重修轮。
    # _ScriptedLlm 在脚本外多调一次就抛，所以跑完不报错即证明没有重修轮。
    assert len(llm.prompts) == len(TITLES) + 1, "达标时不该多花一次重修"


# ── 并行分支互不拖累 ──────────────────────────────────

@pytest.mark.asyncio
async def test_executor_keeps_sibling_resources_when_document_branch_explodes(monkeypatch):
    """文档分支抛异常，PPT 产出仍要交付 —— 这是"任务中断"最刺眼的那个版本。"""

    async def boom(*_args, **_kwargs):
        raise RuntimeError("完整文档未通过质量检查：文档有效内容不足 900 字符")

    async def fake_ppt(*_args, **_kwargs):
        return "## 甲\n<!-- layout: content_cards -->\n- 内容"

    monkeypatch.setattr(resource_graph, "generate_document_parallel", boom)
    monkeypatch.setattr(resource_graph, "generate_ppt_parallel", fake_ppt)

    result = await resource_graph.executor_node({
        "topic": "文档切分",
        "resource_types": ["document", "ppt"],
        "user_id": "7",
    })

    assert result["generated_resources"]["ppt"] == "## 甲\n<!-- layout: content_cards -->\n- 内容"
    assert "document" not in result["generated_resources"]


@pytest.mark.asyncio
async def test_executor_keeps_document_when_ppt_branch_explodes(monkeypatch):
    """反过来也一样：PPT 炸了不该带走文档。"""

    async def fake_doc(*_args, **_kwargs):
        return "# 文档切分\n\n## 甲\n\n正文。"

    async def boom(*_args, **_kwargs):
        raise RuntimeError("ppt 生成失败")

    monkeypatch.setattr(resource_graph, "generate_document_parallel", fake_doc)
    monkeypatch.setattr(resource_graph, "generate_ppt_parallel", boom)

    result = await resource_graph.executor_node({
        "topic": "文档切分",
        "resource_types": ["document", "ppt"],
        "user_id": "7",
    })

    assert result["generated_resources"]["document"] == "# 文档切分\n\n## 甲\n\n正文。"


def test_repair_targets_localize_when_the_problem_is_one_section():
    """某一节自己坏了 → 只改那一节，已经写好的部分不连累。"""
    parts = [_section("甲"), "## 乙\n\n待补充", _section("丙")]

    targets = resource_graph._document_repair_targets(parts, ["文档包含省略或待补充占位语"])

    assert targets == [1]


@pytest.mark.parametrize(
    "errors",
    [
        ["文档有效内容不足 900 字符"],
        ["路径节点文档缺少一级章节标题"],
        ["路径节点文档至少需要三个完整小节"],
    ],
)
def test_repair_targets_rewrite_the_whole_chapter_when_the_problem_is_global(errors):
    """字数不足、缺标题这类整章性问题定不到某一节，只补最短的一节也凑不够。"""
    parts = [_section("甲"), _section("乙"), _section("丙")]

    assert resource_graph._document_repair_targets(parts, errors) == [0, 1, 2]


def test_fallback_section_is_safe_and_structured():
    content = resource_graph._fallback_document_section("文档切分", "语义边界")

    assert content.startswith("## 语义边界")
    assert resource_graph.validate_document_section(content, "语义边界") == []
    assert resource_graph.validate_document_safety(content) == []
    assert json.dumps({"c": content})  # 兜底文本可被正常序列化进事件流
