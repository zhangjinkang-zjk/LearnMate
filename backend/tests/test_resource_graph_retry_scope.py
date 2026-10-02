# -*- coding: utf-8 -*-
"""重试轮该重做哪些类型：**只重做没通过全局审核的那些**。

## 这条规则挡住的浪费

图是 `executor → reviewer →（没过就回 executor）`，重试粒度原本是整张图。但全局审核
实际只判 mindmap / exercise —— ppt / document / case / reading 在生成阶段已经逐章节
审过，全局审核直接给 `passed=True, score=100` 跳过。

于是**一个脑图不达标，会把已经判过"通过"的文档和 PPT 一起重做**；重做时它们又拿不到
任何反馈（`review_feedback` 只喂给失败的类型），等于原样重抽一遍。

实测（`eval/results` 里 20261002-192443 那轮）：

    第 1 轮 326s   ── 一次生成，全部通过
    第 2 轮 678s   ── 脑图 87 分判不过 → 文档+PPT+脑图全量重做一遍

一次重试让整轮耗时翻倍，其中文档和 PPT 那段是纯浪费。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.ai_core.resource_graph import _types_to_regenerate  # noqa: E402

ALL = ["document", "ppt", "mindmap"]


def test_first_pass_regenerates_everything():
    """首次生成（审核还没跑过）必须是全量。漏一个就是少一份资源。"""
    assert _types_to_regenerate(ALL, None) == ALL
    assert _types_to_regenerate(ALL, []) == ALL


def test_only_the_failed_type_is_regenerated():
    """脑图没过就只重做脑图 —— 文档和 PPT 已经过了它们自己那条审核。"""
    assert _types_to_regenerate(ALL, ["mindmap"]) == ["mindmap"]


def test_several_failures_regenerate_several_types():
    requested = ["document", "ppt", "mindmap", "exercise"]
    assert _types_to_regenerate(requested, ["mindmap", "exercise"]) == ["mindmap", "exercise"]


def test_a_failed_type_that_was_not_requested_is_ignored():
    """审核报了一个这次没请求的类型：它被忽略，**其余没过照常重做**（不是退回全量）。"""
    assert _types_to_regenerate(ALL, ["mindmap", "exercise"]) == ["mindmap"]


def test_an_unknown_failed_type_does_not_produce_an_empty_round():
    """审核报了一个这次没请求的类型时，**退回全量**。

    空手而归比多花钱糟得多：`generated_resources` 会变成空字典，前端什么都拿不到。
    """
    assert _types_to_regenerate(ALL, ["exercise"]) == ALL


def test_the_order_follows_the_request_not_the_failure_list():
    """产出的顺序按请求顺序来，别被审核返回的顺序带跑。"""
    assert _types_to_regenerate(ALL, ["ppt", "document"]) == ["document", "ppt"]


def test_the_result_is_a_copy_so_callers_cannot_mutate_the_state():
    requested = list(ALL)
    result = _types_to_regenerate(requested, None)
    result.append("exercise")
    assert requested == ALL
