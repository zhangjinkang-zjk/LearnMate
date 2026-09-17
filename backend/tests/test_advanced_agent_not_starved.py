# -*- coding: utf-8 -*-
"""进阶智能体不能"老是在兜底"。

症状：库里今天的进阶快照 `source` 全是 `fallback`，前一天全是 `agent`（同一份提示词、
同一个模型，区别只是今天机器上一直在跑路径/资源生成）。

原因不在提示词，在排队：
- 这两次调用的对象都是**学生正等着看的东西**（进阶页的任务、提交后的评分），却被标成了
  `priority="low"`；
- low 那条通道是全局 10 路，和资源预生成、课堂过渡摘要、记忆抽取、进阶任务共用；
- 而 `asyncio.wait_for(..., 120)` 把**排队时间也算进预算里** —— 排久了直接超时降级。

这里钉的是"这两次调用必须是高优先级"，以及"调用确实发出去了"（别被提前拦掉当成降级）。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.src.service.advanced import practice_service
from backend.src.service.advanced import service as advanced_service

SERVICE_SRC = Path(__file__).resolve().parents[1] / "src" / "service" / "advanced" / "service.py"
PRACTICE_SRC = Path(__file__).resolve().parents[1] / "src" / "service" / "advanced" / "practice_service.py"


class _RecordingLlm:
    def __init__(self, content: str = '{"tasks": []}'):
        self.content = content
        self.calls: list[dict] = []

    async def ainvoke(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(content=self.content)


@pytest.fixture
def fake_llm(monkeypatch):
    from backend.src.ai_core import llm_config

    fake = _RecordingLlm()
    monkeypatch.setattr(llm_config, "llm", fake)
    return fake


def _fallback_tasks():
    """用真实的那份构造器，免得手抄一份结构出来改天对不上。"""
    return advanced_service.build_advanced_tasks(
        profile={"goal": "就业"},
        path={"subjects": ["机械制图"], "nodes": [{"topic": "三视图"}]},
        mastery_records=[],
    )


@pytest.mark.asyncio
async def test_the_task_agent_is_not_queued_behind_background_work(fake_llm):
    result = await advanced_service.generate_agent_task_set(
        1, {}, {}, [], 10, _fallback_tasks(),
    )

    assert fake_llm.calls, "模型没有被调用 —— 那就是别的路径在降级，不是优先级的问题"
    assert fake_llm.calls[0]["priority"] == "high", (
        "进阶任务生成又标成低优先级了：它会为后台的资源生成排队，然后超时降级成兜底模板"
    )
    # 结构不合约时降级是对的（这条测试的假模型就返回了个空壳）
    assert result["source"] == "fallback"


def test_no_advanced_call_is_low_priority_anymore():
    """进阶这条路上不该再有 low 的模型调用。

    两处（生成任务、实践评分）都是学生正盯着等的结果，标 low 就等于让它们给后台排队，
    而排队时间算在超时预算里 —— 排久了就降级，页面变成兜底模板。

    这条走源码断言：`run_grading` 自己读库读会话，为它搭一套能调用的替身比重写实现还长，
    而这里要钉的只是"这两个字有没有被改回去"。
    """
    for path in (SERVICE_SRC, PRACTICE_SRC):
        source = path.read_text(encoding="utf-8")
        assert 'priority="low"' not in source, f"{path.name} 里又有低优先级的模型调用了"
    assert 'llm.ainvoke(prompt, priority="high", user_id=user_id, pool="advanced")' in \
        PRACTICE_SRC.read_text(encoding="utf-8"), "实践评分那次调用没找到高优先级写法"


def test_the_grading_path_still_has_its_own_timeout():
    """降级的原因是超时，所以这条超时不能被顺手删掉 —— 它是唯一能兜住慢模型的东西。"""
    assert practice_service.GRADING_TIMEOUT_SECONDS >= 60
    assert advanced_service.ADVANCED_AGENT_TIMEOUT_SECONDS >= 60
