# -*- coding: utf-8 -*-
"""实践教练的工具**一个都不能被自建智能体的白名单滤掉**。

`service/agent/service._agent_create` 对每个智能体都跑 `_validate_tools`，而它是静默过滤：
不在 `_ALLOWED_TOOLS` 里的名字直接消失。教练本来走的是另一条路（自愈分支直接写
`expected_tools`），但**新库上第一次创建**走的是 `_agent_create` —— 于是漏掉的那几个工具
当场没了，而且没有任何报错。

更糟的是它不会自己好：`_CLASSROOM_AGENT_IDS` 缓存的 hash 是按**代码里的** `_CLASSROOM_TOOLS`
算的，不是按库里那行算的。所以下一轮比较"一致"，直接 return，自愈分支永远走不到 ——
要等后端重启。

这个 bug 真的发生过：`read_web_page` / `write_design_doc` / `fetch_framework_docs` 三个都不在
名单里，新用户第一次进实践课堂时教练只剩 5 个工具。
"""
from backend.src.service.agent.service import _ALLOWED_TOOLS, _validate_tools
from backend.src.service.path.classroom_chat import _CLASSROOM_TOOLS


def test_every_classroom_tool_is_allowed():
    missing = [name for name in _CLASSROOM_TOOLS if name not in _ALLOWED_TOOLS]

    assert not missing, (
        f"这些工具会在创建教练时被静默滤掉：{missing}。"
        "把它们加进 service/agent/service._ALLOWED_TOOLS。"
    )


def test_the_classroom_tool_list_survives_validation_unchanged():
    """对着**真正会跑的**那个函数测一遍，而不是只比集合。

    `_validate_tools` 顺带保证顺序，这条测的是"教练拿到的就是它声明的那份" ——
    有人把 `_validate_tools` 改成去重、排序、取上限之类，这里会响。
    """
    assert _validate_tools(list(_CLASSROOM_TOOLS)) == list(_CLASSROOM_TOOLS)
