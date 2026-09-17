# -*- coding: utf-8 -*-
"""阶段词汇：三种任务类型各一套，老会话仍用通用那套。

改动之前，进阶学习只有一个全局的 6 阶段词汇（`understand/evidence/...`），三种任务
类型共用，所以"迁移练习"和"项目实训"的操作方式一字不差，只有卡片标题不同；而任务
生成器自己产的是第三套（`context/plan/verify/review`），谁都不认识它。

现在的分工：
- `PHASES`（通用 6 阶段）是**没有 kind 的会话**那套，也就是改动之前建的所有会话 ——
  保留它是为了不做数据迁移（见 test_a_session_without_a_kind_keeps_the_generic_vocabulary）
- `PHASE_SETS` 是三类任务各自那套，都是 4 个
- **id 的归属唯一**：一个 id 只出现在一套词汇里，否则"这串 id 属于哪一套"就没法判断

这里还钉住一条曾经很隐蔽的坑：任务生成器给的阶段 id 落进账本后会被当未知值丢掉，
用户的进度会清零而日志里什么都不显（见 test_agent_supplied_stage_ids_never_reach_the_ledger）。
"""

from types import SimpleNamespace

import pytest

from backend.src.service.advanced import practice_service
from backend.src.service.advanced.service import _merge_agent_stages
from backend.src.service.advanced.practice_service import (
    PHASE_IDS,
    PHASE_SETS,
    PHASES,
    AdvancedPracticeService,
    _clean_phases,
    _serialize,
    _task_snapshot,
    advance_phase_state,
    clamp_current_phase,
    phases_for,
    session_phases,
)

_evaluate = AdvancedPracticeService._evaluate

KINDS = ("case", "transfer", "project")


# ═══════════════════════════════════════
#  词汇表本身
# ═══════════════════════════════════════

@pytest.mark.parametrize("kind", KINDS)
def test_every_task_kind_has_its_own_four_phases(kind):
    phases = phases_for(kind)
    assert len(phases) == 4, "三类任务的阶段数一致，phase_score 的分母才一致"
    for phase_id, label, hint in phases:
        assert phase_id and label and hint


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_reads_visibly_different_from_the_others(kind):
    """这是 T4 的验收标准："三种类型的阶段列表肉眼可见地不同"。"""
    labels = {label for _, label, _ in phases_for(kind)}
    for other in KINDS:
        if other == kind:
            continue
        assert labels != {label for _, label, _ in phases_for(other)}


def test_a_phase_id_belongs_to_exactly_one_vocabulary():
    """id 的归属必须唯一。

    否则同一串 `completed_phases` 能同时被两套词汇解释，而"这个 id 是哪个阶段"就
    取决于读它的人手里拿着哪一套 —— 进度会看起来对、算起来错。
    """
    seen: dict[str, str] = {}
    for phase_id in PHASE_IDS:
        seen[phase_id] = "generic"
    for kind, phases in PHASE_SETS.items():
        for phase_id, _, _ in phases:
            assert phase_id not in seen, f"{phase_id} 同时属于 {seen.get(phase_id)} 和 {kind}"
            seen[phase_id] = kind


@pytest.mark.parametrize("kind", ["", None, "nonsense", "  "])
def test_an_unknown_kind_falls_back_to_the_generic_vocabulary(kind):
    assert phases_for(kind) == PHASES


def test_a_session_without_a_kind_keeps_the_generic_vocabulary():
    """老会话（改动之前建的）快照里没有 kind —— 它们必须继续按 6 阶段解释。

    这是"不做数据迁移"的全部依据：它们的 completed_phases 里存的就是那 6 个 id。
    """
    old_session = SimpleNamespace(task_snapshot={"title": "老任务"})
    assert session_phases(old_session) == PHASES


# ═══════════════════════════════════════
#  账本按 kind 走
# ═══════════════════════════════════════

def test_a_four_phase_task_walks_its_own_four_phases():
    session = SimpleNamespace(task_snapshot={"kind": "project"})
    phases = session_phases(session)
    assert [phase_id for phase_id, _, _ in phases] == ["scope", "delivery", "integration", "retro"]

    completed, current = [], "scope"
    for _ in range(4):
        completed, current = advance_phase_state(completed, current, ["done"], phases)
    assert completed == ["scope", "delivery", "integration", "retro"]
    assert current == "retro", "走到底就停在最后一个阶段，不会越界"

    # 再推也不会长出第五个
    completed, current = advance_phase_state(completed, current, ["done"], phases)
    assert completed == ["scope", "delivery", "integration", "retro"]


def test_the_ledger_drops_ids_from_another_vocabulary():
    """这就是"前端拿任务 stages 的 id 去往返会静默清零"的回归测试。"""
    project_phases = phases_for("project")
    # 通用词汇的 id 混进来 → 全被丢掉（日志里不会有任何提示，所以必须有测试守着）
    assert _clean_phases(["understand", "evidence"], project_phases) == []
    # 本套词汇的 id 照常保留，并按本套顺序重排
    assert _clean_phases(["retro", "scope"], project_phases) == ["scope", "retro"]


def test_a_current_phase_from_another_vocabulary_falls_back_to_the_first():
    project_phases = phases_for("project")
    assert clamp_current_phase("understand", [], project_phases) == "scope"


def test_a_client_cannot_jump_ahead_in_a_four_phase_task():
    case_phases = phases_for("case")
    assert clamp_current_phase("check", [], case_phases) == "clues"
    assert clamp_current_phase("check", ["clues"], case_phases) == "fault"
    # 回看已完成的阶段仍然允许
    assert clamp_current_phase("clues", ["clues", "fault"], case_phases) == "clues"


# ═══════════════════════════════════════
#  算分
# ═══════════════════════════════════════

def _score_with(phases):
    return _evaluate({}, [{"role": "user", "text": "写了一版方案"}], ["scope"], "我的方案", phases)["score"]


def test_the_phase_score_denominator_follows_the_vocabulary():
    """同一个已完成阶段，4 阶段任务里占 10 分，通用 6 阶段里只占约 7 分。

    其余几项（依据/验证/取舍/发言次数）锚在同一份输入上，所以两次之差就是阶段分 ——
    这样断言不必跟着那几个关键词口径一起改。
    """
    assert _score_with(phases_for("project")) - _score_with(PHASES) == 3  # 10 - 7


def test_the_first_criterion_follows_the_vocabulary_too():
    """四条维度标签不动，但第一条问的是"第一个阶段完成没有"，那要看词汇。"""
    project = _evaluate({}, [{"role": "user", "text": "写了"}], ["scope"], "方案", phases_for("project"))
    assert project["criteria"][0] == {"label": "问题理解", "passed": True}

    mismatched = _evaluate({}, [{"role": "user", "text": "写了"}], ["understand"], "方案", phases_for("project"))
    assert mismatched["criteria"][0]["passed"] is False


def test_the_next_step_names_a_phase_from_the_right_vocabulary():
    evaluation = _evaluate({}, [{"role": "user", "text": "写了"}], [], "方案", phases_for("case"))
    joined = " ".join(evaluation["next_steps"])
    assert "线索筛选" in joined
    assert "理解问题" not in joined


# ═══════════════════════════════════════
#  快照：会话得记住自己做的是哪类任务
# ═══════════════════════════════════════

def test_the_session_snapshot_keeps_the_task_type_and_support_level():
    snapshot = _task_snapshot({
        "id": "path-1-node-2-project",
        "title": "综合交付",
        "kind": "project",
        "support_level": "low",
        "problem": "把已完成节点串起来",
        "stages": [],
    })
    assert snapshot["kind"] == "project"
    assert snapshot["support_level"] == "low"
    assert [item["id"] for item in snapshot["stages"]] == ["scope", "delivery", "integration", "retro"]


def test_an_unknown_kind_is_not_written_into_the_snapshot():
    """快照里的 kind 只留认识的那三个 —— 别的值留着只会让读它的人以为有第四套词汇。"""
    assert _task_snapshot({"id": "x", "kind": "brand-new"})["kind"] == ""
    assert phases_for(_task_snapshot({"id": "x", "kind": "brand-new"})["kind"]) == PHASES


def test_agent_supplied_stage_labels_are_kept_but_their_ids_are_not():
    """生成器写的文案可以用，它起的 id 不行。

    改动前这里是"智能体给了 id 就用它的"，而生成器一直在写 context/plan/verify/review
    —— 那些 id 进账本后会被静默丢掉，学生的进度会莫名其妙清零。
    """
    snapshot = _task_snapshot({
        "id": "x",
        "kind": "case",
        "stages": [
            {"id": "context", "label": "读线索", "hint": "先看材料"},
            {"id": "plan", "label": "找故障", "hint": "定位环节"},
            {"id": "verify", "label": "讲推理", "hint": "说清链条"},
            {"id": "review", "label": "验假设", "hint": "设计检查"},
        ],
    })
    assert [item["id"] for item in snapshot["stages"]] == ["clues", "fault", "reasoning", "check"]
    assert [item["label"] for item in snapshot["stages"]] == ["读线索", "找故障", "讲推理", "验假设"]
    assert "context" not in str(snapshot["stages"])


def test_a_wrong_number_of_stages_falls_back_entirely():
    snapshot = _task_snapshot({"id": "x", "kind": "transfer", "stages": [{"label": "只有一个"}]})
    assert [item["id"] for item in snapshot["stages"]] == ["source", "breakdown", "redesign", "boundary"]
    assert snapshot["stages"][0]["label"] == "识别原方法"


def test_the_session_reads_labels_from_the_snapshot_but_ids_from_the_server():
    session = SimpleNamespace(task_snapshot={
        "kind": "case",
        "stages": [{"id": "clues", "label": "读线索", "hint": "先看材料"}],
    })
    phases = session_phases(session)
    assert phases[0] == ("clues", "读线索", "先看材料")
    assert phases[1][0] == "fault", "快照没给的阶段回落服务端默认，id 始终是服务端的"


# ═══════════════════════════════════════
#  下发给前端的阶段列表
# ═══════════════════════════════════════

def _session(**overrides):
    base = {
        "session_key": "s1",
        "task_key": "t1",
        "path_id": 1,
        "node_id": 2,
        "status": "active",
        "current_phase": "fault",
        "completed_phases": ["clues"],
        "task_snapshot": {"kind": "case", "title": "定位一次故障", "stages": []},
        "messages": [],
        "confirmed_facts": [],
        "assumptions": [],
        "final_submission": "",
        "evaluation": None,
        "updated_at": None,
        "deliverable_state": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_api_sends_the_whole_phase_list_with_status():
    """前端不再自己抄一份阶段词汇：它渲染的就是这里下发的。"""
    payload = _serialize(_session())
    assert [(item["id"], item["status"]) for item in payload["phases"]] == [
        ("clues", "completed"),
        ("fault", "current"),
        ("reasoning", "pending"),
        ("check", "pending"),
    ]
    assert payload["phases"][0]["label"] == "线索筛选"
    assert payload["current_phase_label"] == "定位故障"


def test_the_api_keeps_sending_the_label_for_a_finished_session():
    payload = _serialize(_session(current_phase="check", completed_phases=["clues", "fault", "reasoning", "check"]))
    assert payload["current_phase_label"] == "验证假设"
    assert all(item["status"] == "completed" for item in payload["phases"])


def test_the_api_sends_the_deliverable_ticks_back():
    """勾选过的交付物要能读回来 —— 存了不下发等于没存（刷新后勾选全没了）。"""
    payload = _serialize(_session(deliverable_state={"故障定位说明": True, "验证记录": False}))
    assert payload["deliverable_state"] == {"故障定位说明": True, "验证记录": False}


# ═══════════════════════════════════════
#  交付物勾选
# ═══════════════════════════════════════

def test_deliverable_state_only_keeps_deliverables_this_task_actually_has():
    snapshot = {"deliverables": ["故障定位说明", "验证记录"]}
    cleaned = practice_service._clean_deliverable_state(
        {"故障定位说明": True, "验证记录": False, "别的东西": True},
        snapshot,
    )
    assert cleaned == {"故障定位说明": True, "验证记录": False}


@pytest.mark.parametrize("value", [None, [], "字符串", 3])
def test_deliverable_state_survives_junk(value):
    assert practice_service._clean_deliverable_state(value, {"deliverables": ["甲"]}) == {}


def test_deliverable_state_values_become_booleans():
    cleaned = practice_service._clean_deliverable_state({"甲": "yes", "乙": 0}, {"deliverables": ["甲", "乙"]})
    assert cleaned == {"甲": True, "乙": False}


def test_a_session_saved_before_this_column_existed_still_serializes():
    """这一列是后加的，库里已存在的行是 NULL —— 取回来不能把响应拼崩。"""
    legacy = _session()
    del legacy.deliverable_state
    assert _serialize(legacy)["deliverable_state"] == {}


# ═══════════════════════════════════════
#  生成器智能体不能自己定阶段 id
# ═══════════════════════════════════════

CASE_FALLBACK_STAGES = [
    {"id": "clues", "label": "线索筛选", "status": "active"},
    {"id": "fault", "label": "定位故障", "status": "pending"},
    {"id": "reasoning", "label": "说明推理", "status": "pending"},
    {"id": "check", "label": "验证假设", "status": "pending"},
]


def test_the_agent_may_rewrite_stage_wording_but_not_the_ids():
    """这是本次改动最隐蔽的一条坑。

    生成器一直在写 `context/plan/verify/review`（它自己那套），而账本只认会话那套
    —— 那些 id 落进 `completed_phases` 后会被 `_clean_phases` 当未知值**静默**丢掉：
    学生的进度莫名其妙清零，日志里什么都不显。
    """
    merged = _merge_agent_stages(
        [
            {"id": "context", "label": "读线索", "hint": "先看材料"},
            {"id": "plan", "label": "找故障", "hint": "定位环节"},
            {"id": "verify", "label": "讲推理", "hint": "说清链条"},
            {"id": "review", "label": "验假设", "hint": "设计检查"},
        ],
        CASE_FALLBACK_STAGES,
    )
    assert [item["id"] for item in merged] == ["clues", "fault", "reasoning", "check"]
    assert [item["label"] for item in merged] == ["读线索", "找故障", "讲推理", "验假设"]
    assert merged[0]["status"] == "active", "status 也是服务端的"
    assert "context" not in str(merged)


def test_a_wrong_number_of_agent_stages_falls_back_entirely():
    for raw in ([{"label": "只有一个"}], [], None, "不是列表", CASE_FALLBACK_STAGES + [{"label": "多一个"}]):
        assert _merge_agent_stages(raw, CASE_FALLBACK_STAGES) == CASE_FALLBACK_STAGES


def test_a_broken_stage_entry_falls_back_instead_of_crashing():
    broken = [{"label": "甲"}, "不是对象", {"label": "丙"}, {"label": "丁"}]
    assert _merge_agent_stages(broken, CASE_FALLBACK_STAGES) == CASE_FALLBACK_STAGES
