# -*- coding: utf-8 -*-
"""进阶任务评估里那些**会算错的函数**：数字归一、分组、扫描范围、判据归属。

这份评估是要拿结论去改提示词的，所以它的判据不能只靠"跑一遍看着对"。这里守四类具体事故，
每一类都真实发生过或者差一点发生：

1. **合规换算被判成编造。** 模型把掌握度 0.67 如实写成"67%"，原来的实现按 token 比字符串
   （`0.67` ≠ `67`），判了"编造数字"。落盘那次 3 轮里挂掉 2 轮，挂的**全部**是 0.67/0.45
   这两个数的换算 —— 报告里逐条列着 `case 里的 67；project 里的 45；…`。判据误报比漏报更坏：
   它会让人去改一份没坏的东西。
2. **允许集被提示词的规则文本污染。** 原来的允许集是 `提示词 ∪ 上下文`，而提示词里写着
   规则编号 10/11/12/13/14、字数上限 42/140/100、推荐门槛 60/80 —— 全是规则，不是输入数据。
   实测 17 个 token 里有 10 个来自规则文本。后果是模型随手写"掌握度 60% 可推荐 transfer"
   也能过，因为 60 "在输入里找得到"。
3. **"预期恒过"的判据混进真判据里打分。** 六条契约符合性（结构/字段/黑话/话术/summary 推荐/
   超长）的答案是"模型抄没抄提示词里那张清单"，混排会把整体观感刷成几乎满分。
4. **扫描范围漏了学生真的看得见的地方。** `summary` 显示在任务条下面，但越界判据只扫任务的
   五个字段；而 `focus` 恰恰相反 —— 它由服务端无条件覆盖（`service.py` 的
   `_normalise_agent_tasks`），模型写的那份不发给学生，扫它等于判一段被丢弃的文字。

只测纯函数，不联网、不碰数据库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.task_eval import (  # noqa: E402
    GROUP_CONTRACT,
    GROUP_INFO,
    GROUP_QUALITY,
    GROUP_SKIPPED,
    _exact_leak,
    _is_transient_error,
    _number_forms,
    _number_tokens,
    _number_values,
    _student_visible_texts,
    check_banned_words,
    check_fabricated_numbers,
    check_lengths,
    check_product_speak,
    check_substitution,
    has_model_output,
    judge_all,
    learner_tags,
    render_report,
    summarise,
    task_text,
)

# ── 固定世界：与 `task_eval.py` 里学习者 A 同形，够判据用就行 ──

_LEARNED = ["API 调用", "结构化输出", "文本切块", "向量检索"]
_NOT_LEARNED = ["HNSW 索引", "混合检索"]
# 0.67 / 0.45 是事故当事人；90001 是路径 id（真实输入数据）
_CONTEXT = {
    "milestone": 0,
    "completed_nodes": 5,
    "total_nodes": 7,
    "path": {"id": 90001},
    "mastery": [
        {"knowledge_tag": "向量检索", "accuracy": 0.67},
        {"knowledge_tag": "结构化输出", "accuracy": 0.45},
    ],
}

# 每个判据归在哪一组，是这份报告的核心口径。**新加判据时这张表必须跟着动** ——
# 加漏了它会落到默认组（quality），也就是悄悄混进真判据里。
_EXPECTED_GROUPS = {
    "没考没学过的": GROUP_QUALITY,
    "project 跨节点": GROUP_QUALITY,
    "没有编造数字": GROUP_QUALITY,
    "结构完整": GROUP_CONTRACT,
    "字段齐全": GROUP_CONTRACT,
    "没有咨询黑话": GROUP_CONTRACT,
    "没有产品话术": GROUP_CONTRACT,
    "summary 不宣称推荐": GROUP_CONTRACT,
    "没有超长字段": GROUP_CONTRACT,
    "兜底顶替情况": GROUP_INFO,
}


def _task(kind: str, **overrides) -> dict:
    base = {
        "kind": kind,
        "title": f"{kind} 的标题",
        "brief": "一句话说清要做什么",
        "scenario": "假装你手上有一份真实材料",
        "problem": "把这三块串起来做一个东西",
        "why": "练的是把它们放进同一条链路里",
        "focus": "重点能力（服务端取的那份）",
        "deliverables": [{"label": "一份说明"}],
        "criteria": ["说清取舍"],
        "constraints": ["只用已经学过的内容"],
    }
    base.update(overrides)
    return base


def _payload(summary: str = "本次里程碑的重点是把学过的几块串起来。", **by_kind) -> dict:
    """三个任务 + summary。按 kind 覆盖字段：`_payload(project={"problem": "…"})`。"""
    tasks = [_task(kind, **(by_kind.get(kind) or {})) for kind in ("case", "transfer", "project")]
    return {"tasks": tasks, "summary": summary}


def _task_variant(kind: str, tag: str) -> dict:
    """同一个 kind 的两种版本（兜底 / 模型写的）：除 `focus` 外每个字段都带自己的前缀。

    `focus` 刻意不带前缀 —— 服务端那一份对两边是同一个值，这正是要测的东西。
    """
    return _task(
        kind,
        title=f"{tag} {kind} 的标题",
        brief=f"{tag} 的简述",
        scenario=f"{tag} 的情境",
        problem=f"{tag} 的问题",
        why=f"{tag} 的理由",
        deliverables=[{"label": f"{tag} 的交付物"}],
        criteria=[f"{tag} 的验收点"],
        constraints=[f"{tag} 的约束"],
    )


def _one(verdicts: list[dict], name: str) -> dict:
    matches = [item for item in verdicts if item["name"] == name]
    assert len(matches) == 1, f"{name} 出现了 {len(matches)} 次"
    return matches[0]


def _numbers_verdict(payload: dict) -> dict:
    return _one(check_fabricated_numbers(payload, _CONTEXT), "没有编造数字")


# ── 1. 数字归一 ────────────────────────────────────────

def test_only_numbers_that_look_like_facts_are_collected():
    """两位数不判 —— 它几乎总是模型给自己出的题设的设计参数。

    这一刀是拿落盘那三轮**真实产出**定的：13 个数字里 12 个是输入数据，唯一一个非输入的
    是「不超过 10 句话」。模型真写一句编出来的"召回率 92%"抓不到，这个盲区是已知代价。
    """
    assert _number_tokens("串起 3 个标签，做 2 轮") == []
    assert _number_tokens("写清错在哪一步（不超过 10 句话）") == []
    assert _number_tokens("串起 12 个标签") == []
    assert _number_tokens("按 Qdrant 1.13 的接口") == ["1.13"]
    assert _number_tokens("把 131072 条向量重排") == ["131072"]
    assert _number_tokens("summary 不超过 100 字") == ["100"]


def test_a_ratio_and_its_percentage_are_the_same_number():
    """0.67 ≡ 67 ≡ 6700 ≡ 0.0067 —— 同一个数的几种写法。"""
    forms = _number_forms("0.67")
    assert forms == {0.67, 67.0, 0.0067}
    assert _number_forms("67") & forms
    assert _number_forms("6700") & forms
    assert not (_number_forms("60") & forms)


def test_a_design_parameter_is_not_a_fabrication():
    """**这条是 20261002-214029 第 3 轮挂掉的原文**：「不超过 10 句话」。

    那是模型给自己出的题设的约束，不是编造事实。它以前"过"只是因为 `要求 10` 那个规则
    编号恰好在允许集里 —— 同样是假过。
    """
    payload = _payload(case={"criteria": ["写清错在哪一步、依据哪条线索（不超过 10 句话）"]})
    verdict = _numbers_verdict(payload)
    assert verdict["ok"], verdict["detail"]


def test_the_real_false_positive_no_longer_fires():
    """**这条是 20261002-214029 前两轮挂掉的全部原因。**

    掌握度是 0.67 和 0.45，模型如实写成 67% 和 45%，原来判"编造"。现在两位数不在靶心里，
    所以它过 —— 但**归一化仍然是必须的**，见下面 `67.0%` 那条（带小数，在靶心里）。
    """
    payload = _payload(project={"problem": "按 67% 的命中率盘一遍，45% 那个先补。"})
    verdict = _numbers_verdict(payload)
    assert verdict["ok"], verdict["detail"]


def test_a_decimal_percentage_of_an_input_ratio_is_allowed():
    """模型把 0.67 写成 67.0% —— 带小数，在靶心里，必须靠归一化放行。"""
    payload = _payload(project={"problem": "掌握度 67.0% 的那块先补。"})
    verdict = _numbers_verdict(payload)
    assert verdict["ok"], verdict["detail"]


def test_a_number_the_model_wrote_literally_still_passes():
    """0.67 字面量当然也要过 —— 上面那条不是靠"放宽到什么都不判"换来的。"""
    payload = _payload(project={"problem": "掌握度 0.67 的那块先补。"})
    assert _numbers_verdict(payload)["ok"]


def test_an_invented_number_is_still_caught():
    """真的编一个输入里没有的数，必须挂 —— 别把误报修成漏报。"""
    payload = _payload(project={"problem": "把 131072 条向量全部重排一遍。"})
    verdict = _numbers_verdict(payload)
    assert not verdict["ok"]
    assert "131072" in verdict["detail"]


def test_a_number_that_only_exists_in_the_prompt_rules_is_not_input_data():
    """提示词里的 100 是**字数上限**（yaml 要求 13），不是输入数据。

    以前允许集把提示词也算进去，所以模型把规则原样写进正文也判不出来（那是**规则回声**，
    学生会看到"不超过 100 字"这种跟他无关的限制）。新的口径是只取数据上下文 —— 钉住它。
    """
    payload = _payload(project={"why": "summary 不超过 100 字就行。"})
    verdict = _numbers_verdict(payload)
    assert not verdict["ok"], "100 只在提示词的规则文本里，不该被当成输入数据"
    assert "100" in verdict["detail"]


def test_the_path_id_from_the_context_is_allowed():
    """真实输入数据里的数（路径 id）当然要能写。"""
    payload = _payload(project={"scenario": "顺着第 90001 号路径往下做。"})
    assert _numbers_verdict(payload)["ok"]


def test_context_numbers_are_read_from_the_json_form_not_the_python_form():
    """允许集是从 `json.dumps(context)` 里读的，所以浮点写成 `0.8` 也一样能认出来。"""
    values = _number_values('{"accuracy": 0.8}')
    assert 80.0 in values and 0.8 in values


# ── 2. 扫描范围：谁在学生眼前 ──────────────────────────

def test_summary_is_scanned_for_leaks():
    """summary 显示在任务条下面。以前越界判据只扫任务的五个字段，从这里漏出去的抓不到。"""
    payload = _payload(summary="本次要动手把 HNSW 索引 配起来。")
    hits = _exact_leak(payload, _NOT_LEARNED)
    assert any(hit.startswith("summary") for hit in hits), hits


def test_summary_is_part_of_the_student_visible_texts():
    assert [where for where, _ in _student_visible_texts(_payload())] == ["case", "transfer", "project", "summary"]


def test_the_models_focus_is_not_scanned():
    """模型写的 `focus` **不发给学生**：`_normalise_agent_tasks` 无条件用服务端那份覆盖它。

    扫它等于判一段被丢弃的文字 —— 抓不到真实的越界（学生看到的那份来自已完成节点），
    只会凭空多出误判。
    """
    payload = _payload(project={"focus": "围绕 HNSW 索引 设计"})
    assert _exact_leak(payload, _NOT_LEARNED) == []
    assert "HNSW" not in task_text(payload["tasks"][2])


def test_a_long_focus_is_not_a_length_violation():
    """同理：`focus` 不是被截断，是被整份换掉，它的长度到不了学生眼前。"""
    payload = _payload(project={"focus": "重" * 300})
    assert _one(check_lengths(payload), "没有超长字段")["ok"]


def test_banned_words_cover_the_summary_but_product_speak_does_not():
    """两条扫描范围**故意不同**，别当成疏漏：

    - 要求 14（禁词）没有范围限定（"别用这些词"）→ 所有学生会读到的文字都算，含 summary。
    - 要求 10（产品话术）自己划了范围（"不要在标题、why 或 brief 中提及"），summary 另有
      要求 11 管着 → 不扫 summary。扫了就是在判提示词没要求的东西。
    """
    banned = _one(check_banned_words(_payload(summary="形成一个闭环。")), "没有咨询黑话")
    assert not banned["ok"] and "summary" in banned["detail"]

    speak = _one(check_product_speak(_payload(summary="系统会根据你的情况安排。")), "没有产品话术")
    assert speak["ok"], speak["detail"]

    speak_in_title = _one(check_product_speak(_payload(case={"title": "系统会根据你安排"})), "没有产品话术")
    assert not speak_in_title["ok"]


# ── 3. 分组 ────────────────────────────────────────────

def test_every_criterion_declares_the_intended_group():
    """新加判据时这张表必须跟着改 —— 漏了它会默认落进真判据那一组。"""
    payload = _payload()
    groups = {item["name"]: item.get("group") for item in judge_all(payload, _CONTEXT, [], payload["tasks"])}
    assert groups == _EXPECTED_GROUPS


def test_summarise_groups_by_learner_and_then_by_group():
    """报告要能一眼分出"真判据全过"和"预期恒过的那几条也全过"。"""
    payload = _payload()
    verdicts = judge_all(payload, _CONTEXT, [], payload["tasks"])
    records = [{"learner": "agent-dev", "learner_label": "A", "verdicts": verdicts},
               {"learner": "algo", "learner_label": "B", "verdicts": verdicts}]

    summary = summarise(records)

    assert set(summary) == {"agent-dev", "algo"}
    assert set(summary["agent-dev"]) <= {GROUP_QUALITY, GROUP_CONTRACT, GROUP_INFO}
    assert summary["agent-dev"][GROUP_QUALITY]["project 跨节点"]["total"] == 1
    assert summary["algo"][GROUP_CONTRACT]["字段齐全"]["passed"] == 1


def test_an_informational_row_never_claims_a_failed_round():
    """`兜底顶替情况` 的 `ok` 恒为 True，所以它不能进任何"通过率"。

    最坏的情况就是这条存在的理由：模型整个崩掉、学生看到的全是模板原文，它照样满分。
    """
    fallback = [_task("case"), _task("transfer"), _task("project")]
    for task in fallback:
        task["summary"] = ""
    normalised = [_task("case"), _task("transfer"), _task("project")]  # 与兜底一字不差

    item = _one(check_substitution(_payload(), fallback, normalised), "兜底顶替情况")

    assert item["ok"] is True
    assert item["group"] == GROUP_INFO
    assert "一字不差" in item["detail"], item["detail"]


def test_substitution_does_not_count_focus():
    """`focus` 每一轮都等于兜底那份（服务端无条件覆盖），把它算进"顶替"会让人以为模型又漏了字段。"""
    fallback = [_task_variant(kind, "兜底") for kind in ("case", "transfer", "project")]
    normalised = [_task_variant(kind, "模型写的") for kind in ("case", "transfer", "project")]

    item = _one(check_substitution(_payload(), fallback, normalised), "兜底顶替情况")

    assert item["ok"] is True
    assert item["detail"] == "没有一个字段等于兜底原文（说明这些字都是模型写的）", item["detail"]


def test_substitution_does_count_the_other_fields():
    """除了 focus，其余字段一字不差就该报出来 —— 不然上面那条测的就是"什么都不报"。"""
    fallback = [_task_variant(kind, "兜底") for kind in ("case", "transfer", "project")]
    normalised = [_task_variant(kind, "兜底") for kind in ("case", "transfer", "project")]

    item = _one(check_substitution(_payload(), fallback, normalised), "兜底顶替情况")

    assert "24 处与兜底模板一字不差" in item["detail"]
    assert "case.title" in item["detail"]


# ── 4. 固定世界本身 ────────────────────────────────────

def test_learner_tags_splits_by_node_status_and_never_hand_lists():
    """判据 2 和 5 的清单由节点状态**算**出来，不手抄 —— 手抄必然会漂移，而且往宽了漂。"""
    path = {"nodes": [
        {"status": "completed", "knowledge_tags": ["甲", "乙"]},
        {"status": "unlocked", "knowledge_tags": ["丙"]},
        {"status": "locked", "knowledge_tags": ["丁"]},
    ]}
    assert learner_tags(path) == (["甲", "乙"], ["丙", "丁"])


# ── 5. 没有模型产出的那一轮 ────────────────────────────
#
# 落盘那次（20261002-225137）A 第 2 轮：`source=fallback`、120 秒超时，模型一个字没写。
# 评估照跑了判据，往真判据表里塞了两条假失败 —— 它们指向"提示词不行"，而真相是
# 这一轮没有产出。这一组钉的就是这个。

def _record(learner: str, round_index: int, verdicts: list[dict], *,
            source: str = "agent", error: str | None = None) -> dict:
    return {
        "round": round_index, "learner": learner, "learner_label": learner.upper(),
        "elapsed_ms": 1000, "source": source, "error": error, "parse_error": "",
        "completed_nodes": 5, "total_nodes": 7, "milestone": 0,
        "summary": "小结", "tasks": [], "verdicts": verdicts,
        "raw_text": "", "prompt": "",
    }


def test_has_model_output_needs_a_real_task_list():
    assert not has_model_output({})
    assert not has_model_output({"tasks": []})
    assert not has_model_output({"tasks": None})
    assert has_model_output({"tasks": [{"kind": "case"}]})


def test_a_round_without_model_output_runs_no_real_criterion():
    """空 payload 只回一行说明 —— 真判据和契约那几张表里一条都不许出现。"""
    verdicts = judge_all({}, _CONTEXT, [_task("case")], [_task("case")], None, [], [], source="fallback")

    assert len(verdicts) == 1
    assert verdicts[0]["group"] == GROUP_SKIPPED
    assert verdicts[0]["ok"] is True
    assert not [item for item in verdicts if item.get("group") in (GROUP_QUALITY, GROUP_CONTRACT)]


def test_the_two_false_failures_of_the_fallback_round_are_gone():
    """钉死那次事故的两条：`没考没学过的` 和 `project 跨节点`。

    它们是**两种不同机理**的假失败，所以这里两条一起钉：
    - 前者以前判**兜底任务**（`result["tasks"]`），判官按"越界宁可多报"在通用模板上
      编出改述命中 —— 实测那两个标签在兜底模板里零次出现；
    - 后者判**空 payload**，直接落到"没有 project 任务"。
    """
    fallback = [_task("transfer"), _task("case"), _task("project")]
    names = {item["name"] for item in judge_all({}, _CONTEXT, fallback, fallback, None, [], [], source="fallback")}

    assert "没考没学过的" not in names
    assert "project 跨节点" not in names


def test_the_skip_row_says_which_way_it_failed():
    detail = judge_all({}, _CONTEXT, [], [], None, [], [], source="timeout")[0]["detail"]
    assert "timeout" in detail


def test_a_generated_round_still_runs_every_criterion():
    """别把"没有产出"修成"什么都不判" —— 有产出的一轮判据一条不能少。"""
    payload = _payload()
    verdicts = judge_all(payload, _CONTEXT, [], payload["tasks"], None, _LEARNED, _NOT_LEARNED)

    assert {item["name"] for item in verdicts} == set(_EXPECTED_GROUPS)


def test_skipped_rounds_get_their_own_section_and_never_a_rate():
    """跳过的轮次单独一节；真判据表里不许因为它多出任何一行。"""
    payload = _payload()
    judged = judge_all(payload, _CONTEXT, [], payload["tasks"], None, _LEARNED, _NOT_LEARNED)
    skipped = judge_all({}, _CONTEXT, [], [], None, [], [], source="fallback")

    records = [
        _record("agent-dev", 1, judged),
        _record("agent-dev", 2, skipped, source="fallback", error="进阶任务智能体暂时不可用"),
    ]
    summary = summarise(records)

    assert set(summary["agent-dev"]) == {GROUP_QUALITY, GROUP_CONTRACT, GROUP_INFO, GROUP_SKIPPED}
    assert summary["agent-dev"][GROUP_QUALITY]["没考没学过的"]["total"] == 1, "跳过的那轮不该进真判据"
    assert summary["agent-dev"][GROUP_SKIPPED]["本轮没有模型产出"]["total"] == 1

    report = render_report(records, summary)
    assert "没有模型产出" in report
    assert "source=fallback" in report
    # 节号必须连上 —— 插进来一节之后还从"三"接着数，会跳过"四"。
    assert "## 三、没有模型产出" in report
    assert "## 四、信息项" in report
    assert "## 五、每轮" in report


def test_a_run_without_skipped_rounds_prints_no_such_section():
    payload = _payload()
    verdicts = judge_all(payload, _CONTEXT, [], payload["tasks"], None, _LEARNED, _NOT_LEARNED)
    records = [_record("agent-dev", 1, verdicts)]
    report = render_report(records, summarise(records))

    assert "没有模型产出" not in report
    assert "## 三、信息项" in report
    assert "## 四、每轮" in report


# ── 6. 判官的临时错误重试 ──────────────────────────────

def test_transport_errors_are_worth_one_retry():
    """B 第 1 轮判官的死因，原样钉住。"""
    assert _is_transient_error(RuntimeError(
        "peer closed connection without sending complete message body (incomplete chunked read)"))
    assert _is_transient_error(TimeoutError("timed out"))


def test_a_broken_json_reply_is_not_a_transient_error():
    """内容错重试一次多半还是坏的 —— 那是模型的事，该如实报出来，不拿重试掩盖。"""
    assert not _is_transient_error(ValueError("判官返回的不是对象"))
    assert not _is_transient_error(KeyError("learned_used"))
