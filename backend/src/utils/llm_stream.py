# -*- coding: utf-8 -*-
"""模型输出"两段式"的共用处理：先一行给人看的正文，`---`，再是程序用的 JSON。

诊断和画像访谈都走这套约定。分开之后正文一积出来就能推给前端，不用等整段 JSON 拼完 ——
学生等四十秒看一句"正在生成"，和看着字一个个长出来，是完全不同的两件事。

这里集中放"什么能推、什么不能推"的判断，两边共用一份：这类判断各写一份必然走偏，
而走偏的后果是把半截 JSON 画到学生眼前。
"""

import asyncio
import logging

from backend.src.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)

# 两段之间的分隔行（独占一行）。提示词里让模型写的是 `---`，这里带上前面的换行。
VISIBLE_MARKER = "\n---"


def bind_channel(on_delta, channel: str):
    """把"这是哪个气泡的字"绑在回调上。

    一轮里可能有两段正文先后流出来（先判分那句、再下一题），前端必须知道往哪个气泡里
    追加，否则两句话会挤在一起。
    """
    if not on_delta:
        return None
    return lambda text: on_delta(text, channel)


def split_visible(raw: str) -> tuple[str, str]:
    """把模型输出切成 (给人看的正文, 剩下的尾巴)。

    没写分隔行时**正文为空**，不是"整段都算正文"：那种情况下整段是 JSON（老格式），
    把它当正文就等于把 `{"question": ...}` 原样画到用户眼前。
    """
    head, sep, tail = raw.partition(VISIBLE_MARKER)
    return (head.strip(), tail) if sep else ("", raw)


def releasable(buffer: str) -> str:
    """流式过程中"现在就可以给人看"的那一段。

    两条底线：分隔行（或它的半截，比如刚收到一个 `\\n-`）不能露出去；模型没按两段式写、
    直接吐 JSON 时，一个字都不能当正文推 —— 那比不流式更糟。
    """
    cut = len(buffer)
    for stop in (VISIBLE_MARKER, "{", "["):
        pos = buffer.find(stop)
        if pos >= 0:
            cut = min(cut, pos)
    if cut == len(buffer) and VISIBLE_MARKER not in buffer:
        # 扣住结尾那几个字符：它可能就是分隔行的开头，等下一块到了再决定
        for size in range(min(len(VISIBLE_MARKER) - 1, len(buffer)), 0, -1):
            if buffer.endswith(VISIBLE_MARKER[:size]):
                cut -= size
                break
    return buffer[:cut]


async def consume_stream(chunks, on_delta=None, timeout: float | None = None) -> dict:
    """消费模型流，边收边把"可以安全展示"的那部分推出去。

    返回 {"raw": 完整输出, "visible": 已展示的正文, "done": 是否正常收完}。

    超时不丢已经展示出去的内容：正文已经到了用户眼前，再撤回换成兜底只会更糟。所以
    超时/中断都只影响"程序字段拿不拿得到"，不影响用户看到的那句话。
    """
    state = {"raw": "", "visible": "", "done": False}
    try:
        async with asyncio.timeout(timeout):
            async for delta in chunks:
                state["raw"] += delta
                visible = releasable(state["raw"])
                if on_delta and len(visible) > len(state["visible"]):
                    on_delta(visible[len(state["visible"]):])
                    state["visible"] = visible
            state["done"] = True
    except TimeoutError:
        logger.warning("模型流超时，用已经拿到的部分继续 timeout=%s", timeout)
    except Exception:
        logger.warning("模型流中断，用已经拿到的部分继续", exc_info=True)
    # 收尾以完整输出切出来的那段为准：流式期间为了不泄露，可能扣住了结尾几个字符。
    head = split_visible(state["raw"])[0]
    if head:
        state["visible"] = head
    return state


def tail_payload(raw: str) -> dict:
    """取分隔行之后那段 JSON；模型没按格式写就整段当 JSON 试一次（兼容老格式）。

    解不出来返回空字典，**不抛**：走到这里时正文通常已经显示给用户了
    （模型写到一半被打断、或者压根忘了写 JSON），为了一个程序字段把整段降级成
    兜底模板，等于在用户眼皮底下换掉他正在读的那句话。
    """
    _, tail = split_visible(raw)
    candidate = (tail or raw).strip()
    # 整段里连一个花括号都没有 → 直接认定没有程序字段，不去解析。
    #
    # 判据只能是"有没有花括号"，不能是"是不是以花括号开头"：parse_llm_json 自己会从
    # 散文里把 { ... } 那段抠出来（老格式就是"正文 + 一段 JSON"混着写），按开头判会
    # 把这些能解析的反而丢掉。而没有花括号时它必然解析失败，还打一行"解析失败"的
    # WARNING —— 可对访谈题面来说"只写正文、不写 JSON"是**正常输出**，于是每一问都来
    # 一行看着像出故障的告警。
    if "{" not in candidate and "[" not in candidate:
        return {}
    try:
        parsed = parse_llm_json(candidate)
    except Exception:
        logger.warning("模型输出里没有可解析的 JSON，正文照用 raw=%r", str(raw or "")[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}
