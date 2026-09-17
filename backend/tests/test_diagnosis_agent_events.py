"""诊断流程往"智能体流程"里推的事件。

学情诊断是协同闭环的第一个角色（分析→生成→校验→决策），它以前只推 status/result，
在智能体工作流里完全不可见。这里把事件的形状和文案钉住 —— 文案错了不会报错，
只会让抽屉里显示一句没信息量的话。
"""
from backend.src.router.diagnosis_router import _describe_result, _diagnosis_event


def test_event_shape_identifies_diagnosis_agent():
    event = _diagnosis_event("running", "正在生成第一道题")
    assert event["type"] == "agent_event"
    assert event["agent_id"] == "diagnosis"
    assert event["agent_name"] == "学情诊断智能体"
    assert event["phase"] == "diagnosis"
    assert event["status"] == "running"
    assert event["message"] == "正在生成第一道题"


def test_event_passes_extra_fields_through():
    event = _diagnosis_event("done", "完成", finished=True, correct_count=2)
    assert event["finished"] is True
    assert event["correct_count"] == 2


def test_describe_finished_with_percentage():
    message = _describe_result({
        "finished": True,
        "result": {"percentage": 66.7, "correct_count": 2, "total_questions": 3},
    })
    assert message == "诊断完成，正确率 66.7%"


def test_describe_finished_without_percentage():
    # 百分比缺失时不能显示 "正确率 None%"
    assert _describe_result({"finished": True, "result": {}}) == "诊断完成"
    assert _describe_result({"finished": True}) == "诊断完成"


def test_describe_zero_percentage_is_shown():
    # 0% 是合法结果，不能因为 falsy 被当成"没有百分比"
    assert _describe_result({"finished": True, "result": {"percentage": 0}}) == "诊断完成，正确率 0%"


def test_describe_in_progress_uses_one_based_index():
    # current_index 是"已答完几题"，展示给用户要 +1 变成题号
    message = _describe_result({"finished": False, "current_index": 0, "total_questions": 3})
    assert message == "第 1/3 题已就绪"
    message = _describe_result({"finished": False, "current_index": 1, "total_questions": 3})
    assert message == "第 2/3 题已就绪"


def test_describe_in_progress_without_counts():
    assert _describe_result({"finished": False}) == "诊断题目已就绪"


def test_describe_tolerates_non_dict():
    assert _describe_result(None) == "诊断步骤完成"
    assert _describe_result("oops") == "诊断步骤完成"
