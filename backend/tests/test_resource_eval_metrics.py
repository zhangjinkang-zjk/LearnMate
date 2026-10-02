# -*- coding: utf-8 -*-
"""资源评估里**算数的那些函数**：正文取对了没有、产出率/兜底/重复判对了没有。

这些数字是要写进提交文档的，所以它们不能只靠"跑一遍看着对"。这里守三类具体事故：

1. **正文取错份**。一份资源有两处可能拿到正文 —— `resource_complete` 事件和图最终状态的
   `generated_resources`。前者只为 ppt / document / video 推（见 `resource_graph.executor_node`
   里那三处 `_emit_resource_complete`），mindmap 这类只能从后者取。取漏了会**把生成成功的
   资源报成"没产出"**，而且不报错。
2. **"没产出"与"没请求"混在一起**。`executor` 遇到 `is_failed_generation_content` 会直接
   跳过该类型（`resource_graph.executor_node` 里那道判断），`generated_resources` 里就没有它。分母必须是
   请求数，不是产出数 —— 否则缺一份的类型反而把那次的产出率拉高。
3. **把"数不出来"报成 0**。一条都没跑时产出率是 `None`，不是 `0.0`：0 是"全都失败了"，
   None 是"这次没测"。这和 `test_review_audit.py` 里那条是同一个道理。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.claim_audit import _normalise, summarize as audit_summarize  # noqa: E402
from eval.resource_eval import (  # noqa: E402
    _content_of,
    _looks_like_fallback,
    _role_counts,
    _structure,
    summarize as resource_summarize,
)

CLAIMS = [
    {"id": "mutable-default", "claim": "默认值在定义时求值一次", "wrong": "说成每次新建",
     "probe": "pass", "expect": "[1, 2]"},
    {"id": "args-is-tuple", "claim": "*args 收成 tuple", "wrong": "说成 list",
     "probe": "pass", "expect": "'tuple'"},
]


def _resource(**overrides) -> dict:
    base = {"type": "document", "produced": True, "fallback_skeleton": False, "chars": 120,
            "section_count": 3, "code_blocks": 1, "digest": "aaa", "content": "正文"}
    base.update(overrides)
    return base


def _record(round_index: int, resources: list[dict], roles: dict | None = None, ms: int = 1000) -> dict:
    return {"round": round_index, "topic": "t", "elapsed_ms": ms,
            "requested_types": [item["type"] for item in resources],
            "resources": resources, "events": [], "event_roles": roles or {}}


# ── 取正文 ──

def test_the_complete_event_is_preferred_over_the_final_state():
    """事件里那份是**落库前推给前端的那一份**，和图最终状态可能不同（图末端还会改）。"""
    events = [{"type": "resource_complete", "resource_type": "ppt", "content": "事件里的正文"}]
    assert _content_of({"ppt": "最终状态里的正文"}, events, "ppt") == "事件里的正文"


def test_the_last_complete_event_wins():
    """同名事件可能推多次（重写后重推），**要最后那份**，不能拿第一份。"""
    events = [
        {"type": "resource_complete", "resource_type": "document", "content": "第一版"},
        {"type": "resource_complete", "resource_type": "document", "content": "第二版"},
    ]
    assert _content_of({}, events, "document") == "第二版"


def test_a_type_without_an_event_falls_back_to_the_final_state():
    """mindmap 这类**根本不推 `resource_complete`** —— 只能从图最终状态取。
    取不到就一律报"没产出"，会把生成成功的 mindmap 全部误判。"""
    assert _content_of({"mindmap": "脑图正文"}, [], "mindmap") == "脑图正文"


def test_a_missing_resource_yields_an_empty_string_not_a_neighbour():
    """拿不到就是拿不到。**绝不能糊上别的类型的内容** —— 那会把"没产出"变成"产出得不对"。"""
    assert _content_of({"document": "文档正文"}, [], "ppt") == ""


# ── 兜底骨架 ──

def test_fallback_skeletons_are_recognised_by_their_placeholder_wording():
    assert _looks_like_fallback("## 一、概述\n本节内容包含以下要点。")
    assert _looks_like_fallback("……依此类推。")


def test_a_short_but_real_document_is_not_a_skeleton():
    """**只看占位句，不看长短**：短的实内容不是兜底稿，误判会冤枉正常的生成。"""
    assert not _looks_like_fallback("## 默认参数\n默认值在函数定义时求值一次，所以可变默认值会被共用。")
    assert not _looks_like_fallback("")


# ── 形状 ──

def test_structure_counts_sections_and_code_blocks():
    shape = _structure("## A\n```python\nx=1\n```\n## B\ntext")
    assert shape["section_count"] == 2
    assert shape["code_blocks"] == 1
    assert shape["chars"] == len("## A\n```python\nx=1\n```\n## B\ntext")


def test_the_digest_is_stable_and_content_sensitive():
    assert _structure("同样正文")["digest"] == _structure("同样正文")["digest"]
    assert _structure("正文甲")["digest"] != _structure("正文乙")["digest"]


# ── 汇总 ──

def test_production_rate_uses_requested_not_produced_as_denominator():
    """分母是**请求数**。缺一份的类型不该把产出率抬高（那是把失败算成不存在）。"""
    record = _record(1, [_resource(type="document"), _resource(type="ppt", produced=False, digest="")])
    summary = resource_summarize([record])
    assert summary["请求数"] == 2
    assert summary["产出数"] == 1
    assert summary["类型产出率"] == 0.5


def test_nothing_measured_reports_none_not_zero():
    summary = resource_summarize([])
    assert summary["类型产出率"] is None
    assert summary["请求数"] == 0


def test_the_same_digest_across_rounds_is_flagged():
    """同一个类型两轮拿到同一个哈希 = 两轮其实是同一份内容（缓存复用或模型稳定）。
    这是整份评估里**唯一能看见缓存偷偷生效的信号**，必须被点出来。"""
    summary = resource_summarize([_record(1, [_resource()]), _record(2, [_resource()])])
    assert summary["跨轮重复的正文"] == {"document": ["aaa", "aaa"]}


def test_different_digests_across_rounds_are_not_flagged():
    summary = resource_summarize([_record(1, [_resource()]), _record(2, [_resource(digest="bbb")])])
    assert summary["跨轮重复的正文"] == {}


def test_fallback_skeletons_are_listed_with_their_round():
    summary = resource_summarize([_record(1, [_resource(fallback_skeleton=True)])])
    assert summary["兜底骨架清单"] == ["第1轮 document"]


def test_reviewer_states_and_cross_validation_events_are_counted_apart():
    roles = {
        "reviewer:ppt|reviewer|done": 3,
        "reviewer:ppt|reviewer|failed": 1,
        "cross_validator|reviewer|done": 2,
        "executor:ppt|executor|done": 3,
        "saver|saver|done": 1,
    }
    summary = resource_summarize([_record(1, [_resource()], roles=roles)])
    # 审核条目的键是 `agent_id|status`（它们 phase 恒为 reviewer，再带上就是重复）
    assert summary["审核状态分布"]["reviewer:ppt|failed"] == 1
    assert summary["审核状态分布"]["reviewer:ppt|done"] == 3
    assert summary["交叉验证事件数"] == 2
    assert "cross_validator" in summary["出现过的角色"]
    assert "saver" in summary["出现过的角色"]


def test_role_counts_only_read_agent_events():
    """事件流里还有 `stream_text_*` 之类，它们没有 `phase`/`status`，不该进角色统计。"""
    events = [
        {"type": "agent_event", "agent_id": "executor:ppt", "phase": "executor", "status": "running"},
        {"type": "stream_text_start", "resource_type": "ppt"},
    ]
    assert _role_counts(events) == {"executor:ppt|executor|running": 1}


# ── 真实性审计的规整与汇总 ──

def _reply(payload: str) -> str:
    return payload


def test_an_unknown_ref_is_dropped_not_invented():
    """材料提到一个底本里没有的点 —— **不能塞进结果**，那等于判了一个没预注册的判据。"""
    findings = _normalise(_reply('{"findings": [{"ref": "not-in-reference", "verdict": "supports"}]}'), CLAIMS)
    assert [item["ref"] for item in findings] == ["mutable-default", "args-is-tuple"]
    assert all(item["verdict"] == "absent" and item.get("missing") for item in findings)


def test_an_illegal_verdict_is_marked_not_silently_counted_as_absent():
    findings = _normalise(_reply('{"findings": [{"ref": "mutable-default", "verdict": "maybe"}]}'), CLAIMS)
    by_ref = {item["ref"]: item for item in findings}
    assert by_ref["mutable-default"]["verdict"] == "absent"
    assert by_ref["mutable-default"]["invalid"] == "maybe"


def test_an_unanswered_claim_is_marked_missing():
    findings = _normalise(_reply('{"findings": [{"ref": "args-is-tuple", "verdict": "supports"}]}'), CLAIMS)
    by_ref = {item["ref"]: item for item in findings}
    assert by_ref["mutable-default"].get("missing") is True
    assert by_ref["args-is-tuple"].get("missing") is None


def test_a_reply_without_findings_raises_rather_than_reporting_absent():
    """回话里没有 findings 时**必须抛**，让调用方记成"判官报错"。
    要是当成"材料什么都没说"，判官的失败就被洗成了材料的清白。"""
    import pytest

    with pytest.raises(ValueError):
        _normalise(_reply("我觉得这份材料写得不错"), CLAIMS)


def _audit(findings: list[dict], error: str | None = None) -> dict:
    return {"label": "第1轮 `document`", "type": "document", "chars": 10,
            "findings": findings, "error": error}


def test_the_error_rate_denominator_is_what_the_material_actually_asserted():
    audits = [_audit([
        {"ref": "mutable-default", "verdict": "contradicts", "quote": "每次都是新列表"},
        {"ref": "args-is-tuple", "verdict": "supports", "quote": "*args 是元组"},
    ])]
    summary = audit_summarize(audits, CLAIMS)
    assert summary["支持"] == 1
    assert summary["反驳"] == 1
    assert summary["谬误率"] == 0.5


def test_a_material_that_asserts_nothing_gives_no_error_rate():
    """一份完全没触及底本的材料，谬误率是 **None**，不是 0% —— 0% 会被读成"全对"。"""
    audits = [_audit([{"ref": "mutable-default", "verdict": "absent", "quote": ""}])]
    summary = audit_summarize(audits, CLAIMS)
    assert summary["谬误率"] is None


def test_a_verdict_without_a_quote_is_counted_separately():
    """判词要能对证。给了结论却没抄原句的，单独计数 —— 那种判词没法核。"""
    audits = [_audit([{"ref": "mutable-default", "verdict": "supports", "quote": ""}])]
    assert audit_summarize(audits, CLAIMS)["有结论但没抄原句数"] == 1


def test_a_judge_error_is_counted_as_an_error_not_as_absence():
    audits = [_audit([], error="ValueError: 判官回话里没有 findings 数组")]
    summary = audit_summarize(audits, CLAIMS)
    assert summary["判官报错数"] == 1
    assert summary["未涉及"] == 0
    assert summary["谬误率"] is None
