"""主智能体的渐进式披露：按需加载行为模块。

背景：`chat/unified.yaml` 曾经把「资料入库 / 资料管理 / 画像构建 / 历史记录」四段
**写死在常驻提示词里**，每一轮都整份注入。用户随口说一句"你好"，模型也要读一遍
「画像构建」那 25 行怎么发起新用户访谈。无关指令不只是浪费 token —— 它会稀释真正
相关的那几条，让模型照着不相关的剧本走。

现在这四段拆到 `chat/modules/*.yaml`，只在对应情境下才加载。这个文件钉住三件事：
分类器认得对、没命中就真的不加载、以及**别有人再把它们塞回常驻提示词**。
"""

import pytest

from backend.src.ai_core import brain as brain_module
from backend.src.ai_core.brain import Brain, _classify_message
from backend.src.utils.prompt_loader import load_prompt

# 拆出去的四块（类别 → 文件）
EXTRACTED = {
    "ingest": "chat/modules/ingest",
    "kb_manage": "chat/modules/kb_manage",
    "portrait": "chat/modules/portrait",
    "history": "chat/modules/history",
}


def _guides(message: str, *, has_portrait: bool = True) -> str:
    return Brain(user_id=1)._load_tool_guides(message, has_portrait=has_portrait)


# ── 分类器 ──

@pytest.mark.parametrize(("message", "expected"), [
    ("帮我生成一份 PPT", "create"),
    ("我想重新规划学习路径", "manage"),
    ("帮我把这份笔记入库", "ingest"),
    ("知识库里有哪些资料", "kb_manage"),
    ("记住我最近在学 FastAPI", "portrait"),
    ("我们上次聊到哪了", "history"),
])
def test_representative_messages_hit_their_module(message, expected):
    assert expected in _classify_message(message)


@pytest.mark.parametrize("message", [
    "", "你好", "今天天气不错", "谢谢", "嗯嗯",
])
def test_small_talk_loads_nothing(message):
    """闲聊不该拉起任何模块 —— 这正是拆分要换来的东西。

    尤其是「画像构建」那块：它对着一句"你好"会要求模型主动发起 3-5 个访谈问题，
    把一句招呼变成一场访谈。
    """
    assert _classify_message(message) == set()


def test_one_message_can_hit_several_modules():
    """触发词不是一个消息只能命中一个 —— 旧实现每类 break 一次，但类与类之间互不影响。"""
    cats = _classify_message("我把之前的笔记上传了，帮我入库，顺便记住我最近在学 FastAPI")
    assert {"ingest", "portrait"} <= cats


# ── 加载器 ──

def test_a_hit_actually_pulls_the_module_text_in():
    text = _guides("帮我把这份笔记入库")
    assert "### 资料入库" in text
    assert "ingest_document" in text, "模块正文要真的进来了，不能只加个标题"


def test_a_miss_pulls_nothing():
    assert _guides("你好").strip() == ""


def test_a_new_user_gets_the_portrait_module_without_saying_anything():
    """新用户引导是**情境信号**不是消息信号。

    画像还空着的时候，模型必须拿到「画像构建」那段，否则它不会主动发起那几个认识
    对方的问题 —— 这是一条靠触发词覆盖不到的行为。
    """
    assert "### 画像构建" not in _guides("你好", has_portrait=True)
    assert "### 画像构建" in _guides("你好", has_portrait=False)


def test_an_existing_user_without_portrait_triggers_does_not_get_it():
    """反方向也要成立：老用户闲聊时不该被重新访谈一遍。"""
    assert "### 画像构建" not in _guides("你好", has_portrait=True)


# ── 防止退回常驻 ──

def test_the_four_sections_are_gone_from_the_always_on_prompt():
    """常驻提示词里不该再有这四节 —— 有人顺手粘回去的话，这个测试会红。"""
    core = load_prompt("chat/unified")
    for title in ("### 资料入库", "### 资料管理", "### 画像构建", "### 历史记录"):
        assert title not in core, f"{title} 又被写回常驻提示词了"


def test_the_always_on_prompt_keeps_its_core_sections():
    """拆东西不等于可以少内容：身份、工作契约、通用规则必须还在。"""
    core = load_prompt("chat/unified")
    for title in ("## 你的身份", "## 技能培训导师工作契约", "## 通用规则", "### 对话引导", "### 知识库检索"):
        assert title in core


def test_every_registered_module_file_actually_exists():
    """表里登记的每一类都要有对应文件 —— 否则 load_prompt 会在运行时才炸。"""
    for category, name in brain_module._GUIDE_MODULES.items():
        text = load_prompt(name)
        assert text.strip(), f"{category} → {name} 是空的"


def test_the_always_on_prompt_still_has_its_injection_slot():
    """{tool_guides} 是这些东西唯一的注入口，不能被顺手删掉。"""
    assert "{tool_guides}" in load_prompt("chat/unified")
