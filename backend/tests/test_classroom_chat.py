# -*- coding: utf-8 -*-
"""
classroom_chat 课堂对话服务测试

测试目标：backend/src/service/path/classroom_chat.py
覆盖：prompt 组装、课堂上下文、agent 懒创建缓存、SSE 事件序列、异常兜底。
所有 DB / Brain / LLM 依赖用 monkeypatch 模拟，不碰真实数据库和 LLM。
"""
from types import SimpleNamespace

import pytest

from backend.src.models.advanced_practice_model import AdvancedPracticeSession
from backend.src.service.advanced.practice_service import _welcome_message
from backend.src.service.path import classroom_chat as cg_chat
from backend.src.service.chat import service as chat_service


# ── 测试替身 ──

class FakeNode:
    topic = "BCD与ASCII编码"


class FakeQuerySet:
    def __init__(self, item=None):
        self._item = item

    async def first(self):
        return self._item


class FakeUser:
    id = 1


class StubBrain:
    def __init__(self, events, raise_error=False):
        self._events = events
        self._raise_error = raise_error
        self.hydrated_before_ids = []

    async def hydrate_history(self, before_id=None):
        self.hydrated_before_ids.append(before_id)

    async def stream(self, user_prompt, path_context="", portrait_context="", memory_context=""):
        if self._raise_error:
            raise RuntimeError("brain boom")
        for ev in self._events:
            yield ev


async def _collect(generator):
    return [chunk async for chunk in generator]


@pytest.fixture(autouse=True)
def _stub_classroom_chat_persistence(monkeypatch):
    """课堂流测试不连接真实 MySQL，同时保留对话落库行为的可观察性。"""
    records = []

    class FakeRecord:
        id = 88

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.saved = False

        async def save(self):
            self.saved = True

    async def fake_create(**kwargs):
        records.append(kwargs)
        return FakeRecord(**kwargs)

    scheduled = []

    def fake_schedule(*args, **kwargs):
        scheduled.append((args, kwargs))

    monkeypatch.setattr(cg_chat.ChatHistory, "create", fake_create)
    monkeypatch.setattr(cg_chat, "schedule_post_chat_enrichment", fake_schedule)
    return records, scheduled


# ── _compose_user_prompt ──

def test_compose_user_prompt_open():
    segment = {"question": {"prompt": "用你自己的话说说补码为什么能把减法变加法？"}}
    prompt = cg_chat._compose_user_prompt("open", "因为补码取反加一", segment)
    assert "课堂追问" in prompt
    assert "用你自己的话说说补码为什么能把减法变加法" in prompt
    assert "因为补码取反加一" in prompt


def test_compose_user_prompt_feynman():
    prompt = cg_chat._compose_user_prompt("feynman", "我觉得补码能把减法变成加法", {})
    assert "费曼反讲" in prompt
    assert "我觉得补码能把减法变成加法" in prompt


def test_compose_user_prompt_practice_keeps_one_step_at_a_time():
    prompt = cg_chat._compose_user_prompt("practice", "我准备换向量模型", {})
    assert "实践对话" in prompt
    assert "我准备换向量模型" in prompt
    assert "只追问一个" in prompt


def test_compose_user_prompt_practice_has_no_phase_agenda():
    """这一轮的提示词里不该再出现「当前阶段是…」，也不该再要模型写阶段标记。

    以前它写着"当前阶段是「比较方案」"，模型于是把上一轮的安排当成自己这一轮的任务：
    学生问"看看我的代码"，它回"我们先完成任务定义这一步"。阶段机删了，这段话的每一句
    都在生产一个不存在的议程。
    """
    prompt = cg_chat._compose_user_prompt("practice", "教练看看我的代码", {"phase": "比较方案"})

    assert "比较方案" not in prompt
    assert "当前阶段" not in prompt
    assert "PHASE" not in prompt
    # 学生的原话要原样在场，且提示词明确要求先回应他说的这件事
    assert "教练看看我的代码" in prompt
    assert "针对他说的这件事本身回应" in prompt


def test_compose_user_prompt_free():
    assert cg_chat._compose_user_prompt("free", "为什么补码能统一加减？", {}) == "为什么补码能统一加减？"


# ── 开场（practice_opening）──
#
# 这一轮以前压根不存在：会话建好时只种一句写死的通用开场，教练要等学生先说一句才被
# 调用。于是学生在进阶学习里看到的第一问永远一样、也不提这个任务是什么。

def test_compose_user_prompt_practice_opening_asks_the_first_question():
    prompt = cg_chat._compose_user_prompt("practice_opening", "", {})
    assert "学生还没有任何发言" in prompt
    assert "只问一个问题" in prompt


def test_compose_user_prompt_practice_opening_does_not_name_a_stage():
    prompt = cg_chat._compose_user_prompt("practice_opening", "", {"phase": "理解问题"})

    assert "理解问题" not in prompt
    assert "阶段" not in prompt


def test_practice_opening_fallback_carries_the_task_title():
    """兜底必须点出任务名 —— 这正是原来那句写死开场缺的东西。"""
    text = cg_chat._opening_fallback({"title": "构建一个身份-权限模型"})
    assert "构建一个身份-权限模型" in text
    assert "「」" not in text


def test_practice_opening_fallback_without_a_title_is_still_a_whole_sentence():
    """拿不到任务名时退回通用那句，但不能拼出「」这种空引用。"""
    for segment in ({}, {"phase": "理解问题"}, None):
        text = cg_chat._opening_fallback(segment)
        assert text == cg_chat._FALLBACK_REPLIES["practice_opening"]
        assert "「」" not in text


def test_practice_opening_fallback_differs_from_the_seeded_opening():
    """兜底那句必须和 `practice_service._welcome_message` 种下的那句**字面不同**。

    `_opening_pending` 是靠"助手说过的话 != 种下的那句"来判断开场已经生成过的。
    两句一样的话，就会每轮都重新请教练开场一次。
    """
    segment = {"title": "写一份检索方案"}
    assert cg_chat._opening_fallback(segment) != _welcome_message({"title": "写一份检索方案"})["text"]


@pytest.mark.asyncio
async def test_the_opening_turn_emits_no_phase_event(monkeypatch):
    """流式回复里不该再有 `type:phase` 事件 —— 阶段账本已经删了。

    以前这里跑一个 `PhaseStreamStripper` 剥掉模型吐的 `[[PHASE:done]]`，再把它交给
    `AdvancedPracticeService.record_phase_markers`。两个东西都不在了，模型万一还是
    吐了标记，它会原样出现在回复里 —— 这是可接受的：提示词里已经没有任何地方要求它写。
    """
    monkeypatch.setattr(cg_chat, "get_or_create_classroom_agent", _async_value(123))
    monkeypatch.setattr(cg_chat, "_get_classroom_brain", lambda *a, **k: StubBrain([
        {"role": "assistant", "type": "chunk", "content": "这个任务要你产出的是「检索方案」。"},
    ]))
    monkeypatch.setattr(cg_chat, "_build_classroom_path_context", _async_value("ctx"))
    monkeypatch.setattr(cg_chat, "_build_global_portrait_context", _async_value("portrait"))

    session = SimpleNamespace(status="active")
    monkeypatch.setattr(AdvancedPracticeSession, "filter", lambda *a, **k: FakeQuerySet(session))

    events = await _collect(cg_chat.stream_classroom_chat(
        1, 1, 1, {}, "practice_opening", "", practice_session_id="abc",
    ))
    joined = "\n".join(events)

    assert "这个任务要你产出的是" in joined
    assert '"type":"phase"' not in joined


# ── _build_classroom_path_context ──

@pytest.mark.asyncio
async def test_build_classroom_path_context(monkeypatch):
    monkeypatch.setattr(cg_chat.PathNode, "filter", lambda *a, **k: FakeQuerySet(FakeNode()))
    segment = {
        "title": "补码",
        "type": "concept",
        "script": "补码把减法转换为加法",
        "board_items": ["补码等于反码加一", "统一加减运算"],
        "example": "-5 的补码是 11111011",
        "question": {"prompt": "补码为什么能省减法电路？", "options": ["A", "B"]},
    }
    ctx = await cg_chat._build_classroom_path_context(1, 1, segment)
    assert "BCD与ASCII编码" in ctx          # 从 DB 节点 topic
    assert "补码" in ctx                     # 当前幕
    assert "补码把减法转换为加法" in ctx     # 讲解要点
    assert "补码等于反码加一" in ctx         # 板书
    assert "-5 的补码是 11111011" in ctx     # 例子
    assert "补码为什么能省减法电路" in ctx   # 课堂提问


@pytest.mark.asyncio
async def test_build_classroom_path_context_knows_segment_position(monkeypatch):
    # 小知必须知道学生在哪一幕（费曼反讲）以及自己此刻的职责
    monkeypatch.setattr(cg_chat.PathNode, "filter", lambda *a, **k: FakeQuerySet(FakeNode()))
    segment = {"id": "feynman", "title": "费曼反讲", "type": "feynman", "script": "讲给小知听"}
    ctx = await cg_chat._build_classroom_path_context(1, 1, segment)
    assert "第 4/4 幕" in ctx
    assert "费曼反讲" in ctx
    assert "挑一个漏洞" in ctx
    assert "不要替他把内容讲完" in ctx


@pytest.mark.asyncio
async def test_build_classroom_path_context_empty_node(monkeypatch):
    # 节点查不到时退化为 segment.title
    monkeypatch.setattr(cg_chat.PathNode, "filter", lambda *a, **k: FakeQuerySet(None))
    ctx = await cg_chat._build_classroom_path_context(1, 1, {"title": "数制", "script": "基数决定可用数字"})
    assert "数制" in ctx


# ── get_or_create_classroom_agent 缓存幂等 ──

@pytest.mark.asyncio
async def test_get_or_create_classroom_agent_cached(monkeypatch):
    cg_chat._CLASSROOM_AGENT_IDS.clear()
    monkeypatch.setattr(cg_chat.User, "filter", lambda *a, **k: FakeQuerySet(FakeUser()))
    monkeypatch.setattr(cg_chat.UserAgent, "filter", lambda *a, **k: FakeQuerySet(None))  # 不存在 → 走 create
    created = {"id": 123}
    calls = {"n": 0}

    async def fake_create(user_id, name, persona, tools, **kwargs):
        calls["n"] += 1
        return created

    monkeypatch.setattr(cg_chat, "_agent_create", fake_create)

    first = await cg_chat.get_or_create_classroom_agent(1)
    second = await cg_chat.get_or_create_classroom_agent(1)
    assert first == 123 and second == 123
    assert calls["n"] == 1, "create 应只调用一次（第二次命中缓存）"


@pytest.mark.asyncio
async def test_get_or_create_classroom_agent_missing_user(monkeypatch):
    cg_chat._CLASSROOM_AGENT_IDS.clear()
    monkeypatch.setattr(cg_chat.User, "filter", lambda *a, **k: FakeQuerySet(None))
    assert await cg_chat.get_or_create_classroom_agent(999) is None


# ── stream_classroom_chat 事件序列 ──

@pytest.mark.asyncio
async def test_stream_classroom_chat_events(monkeypatch, _stub_classroom_chat_persistence):
    monkeypatch.setattr(cg_chat, "get_or_create_classroom_agent", _async_value(123))
    brain = StubBrain([
        {"role": "assistant", "type": "chunk", "content": "你理解对了，"},
        {"role": "assistant", "type": "chunk", "content": "再补一个例子更稳。"},
    ])
    monkeypatch.setattr(cg_chat, "_get_classroom_brain", lambda *a, **k: brain)
    monkeypatch.setattr(cg_chat, "_build_classroom_path_context", _async_value("【课堂上下文】补码"))
    monkeypatch.setattr(cg_chat, "_build_global_portrait_context", _async_value("计算机专业"))

    events = await _collect(cg_chat.stream_classroom_chat(1, 1, 1, {}, "free", "为什么补码能统一加减？"))
    joined = "\n".join(events)
    assert "你理解对了" in joined
    assert "再补一个例子更稳" in joined
    assert '"type":"done"' in joined
    assert "[DONE]" in joined
    records, scheduled = _stub_classroom_chat_persistence
    assert records == [{
        "user_id": 1,
        "chat_group_id": cg_chat._classroom_group_id(1, 1, 1),
        "agent_id": 123,
        "req": "为什么补码能统一加减？",
        "res": "",
    }]
    assert brain.hydrated_before_ids == [88]
    assert scheduled == [
        ((1, cg_chat._classroom_group_id(1, 1, 1), 123), {
            "portrait_minimum_records": 1,
            "persist_memory": False,
        })
    ]


@pytest.mark.asyncio
async def test_classroom_portrait_enrichment_accepts_one_complete_turn(monkeypatch):
    """课堂每个节点独立成组，一问一答也必须能进入同一画像提取器。"""
    calls = []

    async def fake_extract(user_id, chat_group_id, *, minimum_records=2):
        calls.append((user_id, chat_group_id, minimum_records))

    monkeypatch.setattr(chat_service, "extract_portrait_from_chat", fake_extract)
    monkeypatch.setattr(chat_service, "invalidate_portrait_cache", lambda user_id: None)

    await chat_service._extract_portrait_and_refresh(1, 321, portrait_minimum_records=1)
    assert calls == [(1, 321, 1)]


@pytest.mark.asyncio
async def test_stream_classroom_chat_empty_brain_fallback(monkeypatch):
    # Brain 无文本输出 → 下发兜底文案
    monkeypatch.setattr(cg_chat, "get_or_create_classroom_agent", _async_value(123))
    monkeypatch.setattr(cg_chat, "_get_classroom_brain", lambda *a, **k: StubBrain([
        {"role": "tool", "type": "tool_start", "tool": "web_search"},
    ]))
    monkeypatch.setattr(cg_chat, "_build_classroom_path_context", _async_value("ctx"))
    monkeypatch.setattr(cg_chat, "_build_global_portrait_context", _async_value("portrait"))

    events = await _collect(cg_chat.stream_classroom_chat(1, 1, 1, {}, "free", "xxx"))
    joined = "\n".join(events)
    assert cg_chat._FALLBACK_REPLIES["free"] in joined
    assert "[DONE]" in joined


@pytest.mark.asyncio
async def test_stream_classroom_chat_error(monkeypatch):
    # Brain 抛异常 → error 事件 + [DONE]，不静默中断
    monkeypatch.setattr(cg_chat, "get_or_create_classroom_agent", _async_value(123))
    monkeypatch.setattr(cg_chat, "_get_classroom_brain", lambda *a, **k: StubBrain([], raise_error=True))
    monkeypatch.setattr(cg_chat, "_build_classroom_path_context", _async_value("ctx"))
    monkeypatch.setattr(cg_chat, "_build_global_portrait_context", _async_value("portrait"))

    events = await _collect(cg_chat.stream_classroom_chat(1, 1, 1, {}, "free", "xxx"))
    joined = "\n".join(events)
    assert '"error"' in joined
    assert "[DONE]" in joined


def _async_value(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


# ── 任务说明块 / 学生工作区块（_render_task_block / _render_workspace_block）──
#
# `_build_classroom_path_context` 新增了这两块，拼在最后、两个分支共用。以前 resource_id
# 存在时那个函数提前 return，只给教材摘录 —— 节点一旦绑了主讲材料，任务说明就被整块丢掉，
# 教练在不知道任务是什么的情况下跟学生聊。两块的**信任级别不一样**：任务说明来自服务端
# 账本（task_snapshot），工作区天然只能来自客户端（文件在学生浏览器里）。下面按这两条线
# 分别钉住输入契约、脏数据容错和注入边界。

# 一段带换行和 4 空格缩进的代码 —— 正是 _clip 会摧毁、而工作区块必须保住的东西。
_CODE_SAMPLE = "def add(a, b):\n    total = a + b\n    return total\n"


@pytest.mark.asyncio
async def test_workspace_block_preserves_code_newlines(monkeypatch):
    """最关键的一条回归：代码快照的换行与缩进必须原样进上下文。

    不能用 classroom._clip 渲染代码 —— 它把 \\r/\\n 换成空格再合并，代码过一遍就塌成
    一整行，缩进和结构全丢，而教练要读的正是结构。这条既直接测 _render_workspace_block，
    也经 _build_classroom_path_context 测一遍（拼接那层不能又把它塌一次）。
    """
    # 先确认 _clip 确实会把代码塌成一行 —— 这就是这条测试存在的理由
    assert "\n" not in cg_chat._clip(_CODE_SAMPLE, 500)

    workspace = {
        "available": True,
        "files": [{"path": "solution.py", "text": _CODE_SAMPLE, "truncated": False}],
    }
    block = cg_chat._render_workspace_block(workspace)
    assert "def add(a, b):\n    total = a + b\n    return total" in block
    assert "    return total" in block, "4 个空格的缩进不能被折叠掉"

    # 经完整上下文路径也要保留
    monkeypatch.setattr(cg_chat.PathNode, "filter", lambda *a, **k: FakeQuerySet(FakeNode()))
    ctx = await cg_chat._build_classroom_path_context(1, 1, {"title": "补码", "workspace": workspace})
    assert "def add(a, b):\n    total = a + b\n    return total" in ctx


def test_workspace_block_renders_tree_files_and_active_marker():
    """树、每份文件正文都要在；active_path 对应的那份要带"学生当前正在编辑"标记。"""
    workspace = {
        "available": True,
        "root_name": "learnmate-demo",
        "tree": "learnmate-demo\n├─ solution.py\n└─ utils.py",
        "tree_total_files": 2,
        "tree_shown_files": 2,
        "tree_truncated": False,
        "active_path": "solution.py",
        "files": [
            {"path": "solution.py", "text": "x = 1", "truncated": False},
            {"path": "utils.py", "text": "y = 2", "truncated": False},
        ],
    }
    block = cg_chat._render_workspace_block(workspace)
    assert "【学生工作区（只读快照）】" in block
    assert "文件树（共 2 个文件）：" in block
    assert "solution.py" in block and "utils.py" in block
    assert "x = 1" in block and "y = 2" in block
    # 标记只落在 active_path 那一份上，别的文件不能也挂上
    assert "--- solution.py（学生当前正在编辑） ---" in block
    assert "--- utils.py（学生当前正在编辑） ---" not in block


def test_workspace_block_says_so_when_nothing_is_open():
    """available:false 必须显式说"看不到代码"，并禁止教练假装读过。

    让整块凭空消失是不可靠的信号：教练会以为这条路上本来就没有工作区，于是照学生的话
    脑补代码。明说了它才知道该请学生打开文件夹。
    """
    block = cg_chat._render_workspace_block({"available": False})
    assert block == cg_chat._WORKSPACE_EMPTY_NOTICE
    assert "没有打开任何本机文件" in block
    assert "不要假装读过" in block


def test_workspace_block_reports_tree_truncation_and_omitted_files_separately():
    """树截断 和 正文遗漏 是两句独立的话，各说各的，不能合成一句也不能互相顶掉。"""
    workspace = {
        "available": True,
        "tree": "root\n├─ a.py\n└─ b.py",
        "tree_total_files": 40,
        "tree_truncated": True,
        "files": [{"path": "a.py", "text": "print(1)", "truncated": False}],
        "omitted_count": 3,
        "omitted_paths": ["b.py", "c.py", "d.py"],
    }
    block = cg_chat._render_workspace_block(workspace)
    assert "文件树较长，这里只显示了前面一部分文件。" in block
    assert "还有 3 个已打开文件因篇幅没有附上正文：b.py、c.py、d.py。" in block

    # 树没截断时，不能冒出树截断那句（但遗漏那句不受影响）
    no_tree_trunc = cg_chat._render_workspace_block({**workspace, "tree_truncated": False})
    assert "文件树较长" not in no_tree_trunc
    assert "还有 3 个已打开文件" in no_tree_trunc

    # 没有遗漏文件时，也不能冒出遗漏那句（但树截断那句仍在）
    no_omitted = cg_chat._render_workspace_block({**workspace, "omitted_count": 0, "omitted_paths": []})
    assert "还有" not in no_omitted
    assert "文件树较长，这里只显示了前面一部分文件。" in no_omitted


def test_workspace_block_stays_bounded_but_keeps_the_end_marker():
    """超长输入必须被截断到预算内，但结束标记是注入防御的边界，绝不能被截掉。

    这两条一度是互斥的：实现先把正文截到 _WORKSPACE_CONTEXT_MAX_CHARS，**再**补截断提示
    和结束标记，于是整块恒为 8000 + 18 + 8 —— 一个名字写着"上限"却能被超的常量。
    现在截断预算里先给那条尾巴留了位置，所以"整体不超过常量"和"标记仍在"能同时成立。
    """
    workspace = {
        "available": True,
        "tree": "\n".join(f"pkg{i}/file_{i}.py" for i in range(200)),
        "tree_total_files": 5000,
        "tree_truncated": True,
        "files": [{"path": f"file_{i}.py", "text": "x" * 5000, "truncated": True} for i in range(12)],
    }
    block = cg_chat._render_workspace_block(workspace)

    assert block.endswith("【工作区结束】"), "截断后必须补回结束标记，它是注入防御的边界"
    assert "（工作区内容过长，这里已经截断。）" in block, "确认这次确实触发了截断，断言才有意义"
    # 常量说多少就是多少，不留"实际会多 26 个字符"这种只存在于注释里的例外
    assert len(block) <= cg_chat._WORKSPACE_CONTEXT_MAX_CHARS


def test_workspace_block_degrades_on_dirty_payloads_without_raising():
    """工作区是不可信输入（学生能改自己的浏览器）。脏 JSON 只能退化成合理结果，不能抛异常。"""
    # 整体不是 dict：没有工作区可谈，整块消失
    assert cg_chat._render_workspace_block("not-a-dict") == ""
    assert cg_chat._render_workspace_block(None) == ""

    # files 不是 list、tree_total_files 不是数字：当成缺失，其余照常渲染，且不崩
    block = cg_chat._render_workspace_block(
        {"available": True, "tree": "root\n└─ a.py", "tree_total_files": "abc", "files": "not-a-list"}
    )
    assert "文件树：" in block, "计数非法时只省略个数"
    assert "共" not in block
    assert "已打开的文件正文" not in block

    # files 里混入非 dict / 缺 path 的元素：跳过那几条，合法的照渲染
    block = cg_chat._render_workspace_block(
        {"available": True, "files": [1, "x", {"text": "没有 path"}, {"path": "ok.py", "text": "z = 1"}]}
    )
    assert "ok.py" in block and "z = 1" in block
    assert "没有 path" not in block

    # omitted_paths 里混入数字：收成字符串后照列，不崩
    block = cg_chat._render_workspace_block(
        {"available": True, "files": [{"path": "a.py", "text": "1"}], "omitted_paths": [1, 2]}
    )
    assert "还有 2 个已打开文件因篇幅没有附上正文：1、2。" in block


def test_render_task_block_absent_when_empty():
    """任务块没有实质内容时返回空串：不能留一个"【本次实践任务】"空壳占位。

    快照缺字段/类型不对/字段全空白都算"这次没任务说明"，课堂不该因此中断，也不该塞空壳。
    """
    for snapshot in (
        None,
        {},
        "不是 dict",
        [],
        {"title": "   ", "problem": "\n\t", "focus": ""},
        {"criteria": [], "deliverables": ["  "]},
    ):
        assert cg_chat._render_task_block(snapshot) == ""


@pytest.mark.asyncio
async def test_task_block_comes_from_server_ledger_not_client_segment(monkeypatch):
    """任务说明只认服务端账本 task_snapshot，客户端 segment["task"] 一律不采信。"""
    monkeypatch.setattr(cg_chat.PathNode, "filter", lambda *a, **k: FakeQuerySet(FakeNode()))
    segment = {"title": "补码", "task": {"title": "客户端伪造的任务名"}}

    ctx = await cg_chat._build_classroom_path_context(
        1, 1, segment, task_snapshot={"title": "服务端的任务名"}
    )
    assert "【本次实践任务】" in ctx
    assert "服务端的任务名" in ctx
    assert "客户端伪造的任务名" not in ctx

    # 没有服务端快照时任务块整块消失，客户端那份也不能顶上来
    ctx_without = await cg_chat._build_classroom_path_context(1, 1, segment)
    assert "【本次实践任务】" not in ctx_without
    assert "客户端伪造的任务名" not in ctx_without


def test_workspace_goes_into_path_context_not_the_user_prompt():
    """工作区属于 path_context（系统侧材料），绝不能漏进 user prompt。"""
    workspace = {
        "available": True,
        "files": [{"path": "secret_marker.py", "text": "TOKEN_IN_WORKSPACE"}],
    }
    prompt = cg_chat._compose_user_prompt(
        "practice", "学生的话", {"phase": "比较方案", "workspace": workspace}
    )
    assert "TOKEN_IN_WORKSPACE" not in prompt
    assert "【学生工作区" not in prompt
    # 学生的原话照常进 prompt，改动没有误伤正常路径
    assert "学生的话" in prompt
