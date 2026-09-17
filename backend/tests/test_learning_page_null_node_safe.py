# -*- coding: utf-8 -*-
"""基础讲解页：`activeNode` 可空，那一大片却没做保护 —— 一句渲染异常整页就废了。

现场证据（浏览器控制台）：
    TypeError: Cannot read properties of null (reading 'knowledge_tags')
    [Vue warn]: Unhandled error during execution of render function
      at <FundamentalsPage ...>

根因在模板结构上：`v-if="isChecking && activeNode"` 的 **`v-else` 分支**（`FundamentalsPage.vue`
里那句 `<template v-else>`，一直盖到 `</main>`）在 `activeNode` 为 **null** 时照样渲染 ——
第 41 行 `activeNode?.title` 说明作者本来就知道它可空，但同一个 v-else 里的
`:title="activeNode.title"`、`:tags="activeNode.knowledge_tags || []"`、
页脚里那串 `${activeNode.knowledge_tags?.length || 0} 个知识点` 全是裸读。

触发条件不苛刻：`activeNodeId` 指向一个不在当前路径节点里的 id（换路径、路径重建之后很常见）
→ `findIndex` 返回 -1 → `activeNode` 为 null；而 `documentContent` 只在 selectNode 时清空，
上一章正文还留着 → 页脚那句就炸，整个组件树连带 AppShell 一起报错，
表现就是学生点了「视频讲解」只看见转圈（`videoResource` 就算拿到了也渲染不出来）。

这份测试钉的是那条最省事的规矩：**这个 v-else 区域里不许出现裸的 `activeNode.`**，
要读就写 `activeNode?.`。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "pages" / "learning" / "FundamentalsPage.vue"

# 裸读：activeNode 后面直接跟点。`activeNode?.x` 不含这个子串，`activeNodeIndex` 也不含。
BARE_DEREF = re.compile(r"activeNode\.")


@pytest.fixture(scope="module")
def ungated_region() -> str:
    """截出「activeNode 为 null 时也会渲染」的那一段。"""
    page = PAGE.read_text(encoding="utf-8")
    guard = page.index('v-if="isChecking && activeNode"')
    start = page.index("<template v-else>", guard)
    end = page.index("</main>", start)
    region = page[start:end]
    # 截错了要立刻发现，别让这条测试因为"区域为空"而假绿
    assert "chapter-footer" in region and "MarkdownDocument" in region
    return region


def test_the_region_is_the_ungated_one(ungated_region):
    """这段区域里确实没有 activeNode 的守卫 —— 守卫的是外面那个 v-if。"""
    assert 'v-if="activeNode"' not in ungated_region


def test_no_bare_node_dereference_in_the_ungated_region(ungated_region):
    offenders = [
        f"第 {number} 行: {line.strip()[:110]}"
        for number, line in enumerate(ungated_region.splitlines(), 1)
        if BARE_DEREF.search(line)
    ]
    assert not offenders, (
        "activeNode 可能为 null，这一区域里不能裸读它（会整页渲染失败）：\n  " + "\n  ".join(offenders)
    )


def test_the_chapter_footer_still_counts_knowledge_points(ungated_region):
    """修的是"别炸"，不是把这个信息删掉 —— 页脚还得能说出本章有几个知识点。"""
    assert "activeNode?.knowledge_tags?.length || 0" in ungated_region
