"""水合窗口与折叠边界必须是同一个数。

两处各自定义了一个"最近多少轮保留原文"：

- `ai_core/brain._MAX_HISTORY_TURNS` —— 冷启动时从 `chat_history` 原样水合进上下文
- `service/memory/service.WORKING_BUFFER_TURNS` —— 超过这个窗口的消息会被折进滚动摘要

`_collect_fold_records` 的 docstring 写着"最近 WORKING_BUFFER_TURNS 条保留原文
（**供 Brain 水合**）"—— 也就是说这两处**本意就是同一个窗口**。但实际值是 20 和 12。

差 8 条的后果：倒数第 13~20 轮会**同时以"原文"和"摘要"两种形态**进 prompt。
既白烧 token，又可能让模型把同一件事当成两件（一条"你之前提过"，一条"你刚才说"）。

两边不能互相 import（`ai_core` 不能反向依赖 `service/`），所以各自读同一个环境变量
`MEMORY_BUFFER_TURNS`，由这个文件把"它们必须一致"钉死。
"""

import os

from backend.src.ai_core import brain
from backend.src.service.memory import service as memory_service


def test_hydration_window_equals_the_fold_boundary():
    assert brain._MAX_HISTORY_TURNS == memory_service.WORKING_BUFFER_TURNS, (
        "水合窗口必须等于折叠边界：不等的话，多出来的那几轮会同时以原文和摘要进上下文"
    )


def test_both_sides_honour_the_same_env_var():
    """两边都要认这一个变量。只让一边变成可配的，就等于把漂移重新埋回去。"""
    expected = int(os.getenv("MEMORY_BUFFER_TURNS", "20"))

    assert brain._MAX_HISTORY_TURNS == expected
    assert memory_service.WORKING_BUFFER_TURNS == expected
