# -*- coding: utf-8 -*-
"""周报「AI 学习建议」的错题标签：字段读错了一个月没人发现。

`_get_recent_error_tags` 读的是 `r.knowledge_tags`，而 `r` 是 `ExamRecord` —— 那个字段
声明在 `ExamQuestion` 上（`exam_model.py:15` vs `:31`）。Tortoise 对未声明属性直接抛
AttributeError，被 `generate_weekly_report_and_ai_tip` 的 `except Exception` 吞掉：

    except Exception:
        logger.exception("周报/AI建议生成失败 user=%s", user.id)

于是**最近一周有错题的用户**永远收不到 AI 建议，只在日志里留一行异常 —— 定时任务每周
照着同一批人刷同一条日志，而没有任何功能在报错。周报本体（`weekly_report` 那条通知）
不受影响：它在 `_build_ai_tip` 之前就已经落库了。

这条测试的要点是**让假记录对象根本没有 `knowledge_tags` 属性**：谁把字段读回去，谁就会
在这儿拿到 AttributeError，而不是在日志里被吞掉。
"""

import pytest

from backend.src.service.notification import service as notification_service


class _Question:
    """题目：标签真正住在这一层。"""

    def __init__(self, knowledge_tags):
        self.knowledge_tags = knowledge_tags


class _Record:
    """答题记录：**没有** knowledge_tags —— 和真实的 ExamRecord 一致。"""

    def __init__(self, knowledge_tags, question_missing=False):
        self.is_correct = False
        self.question = None if question_missing else _Question(knowledge_tags)


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self.filter_kwargs = {}
        self.order_arg = None
        self.limit_arg = None
        self.prefetch_arg = None

    def order_by(self, *args):
        self.order_arg = args
        return self

    def limit(self, count):
        self.limit_arg = count
        return self

    def prefetch_related(self, *args):
        self.prefetch_arg = args
        return self

    async def all(self):
        return list(self._rows)


def _patch_exam_records(monkeypatch, rows):
    query = _Query(rows)

    class _FakeExamRecord:
        @staticmethod
        def filter(**kwargs):
            query.filter_kwargs = kwargs
            return query

    monkeypatch.setattr(notification_service, "ExamRecord", _FakeExamRecord)
    return query


@pytest.mark.asyncio
async def test_tags_come_from_the_question_not_the_record(monkeypatch):
    """核心回归：标签从 `question.knowledge_tags` 取，跨题去重。

    用集合比，不用 sorted —— 中文按码点排序的结果不是人读的顺序，写死顺序只会让这条
    测试对着一个和被测行为无关的东西断言。
    """
    _patch_exam_records(monkeypatch, [
        _Record('["洛必达法则", "极限"]'),
        _Record('["极限", "泰勒展开"]'),
    ])

    tags = await notification_service._get_recent_error_tags(7)

    assert set(tags) == {"洛必达法则", "极限", "泰勒展开"}


@pytest.mark.asyncio
async def test_the_record_really_has_no_knowledge_tags():
    """守着"假对象和真模型同形"这件事本身。

    如果哪天有人给 `_Record` 补上一个 `knowledge_tags`（比如为了让测试好写），
    上面那条测试就会重新变成永远通过的摆设 —— 它再也证明不了字段来自题目。
    """
    assert not hasattr(_Record('["甲"]'), "knowledge_tags")
    assert hasattr(_Question('["甲"]'), "knowledge_tags")


@pytest.mark.asyncio
async def test_the_query_still_asks_for_recent_wrong_answers(monkeypatch):
    """筛选条件不能被顺手改掉：只取最近一周、只取错题、按时间倒序取 10 条。"""
    query = _patch_exam_records(monkeypatch, [_Record("[]")])

    await notification_service._get_recent_error_tags(7)

    assert query.filter_kwargs["user_id"] == 7
    assert query.filter_kwargs["is_correct"] is False
    assert "created_at__gte" in query.filter_kwargs
    # 没有 order_by 的话 limit(10) 取到的是"任意 10 条"，而函数名说的是"最近"
    assert query.order_arg == ("-created_at",)
    assert query.limit_arg == 10


@pytest.mark.asyncio
async def test_the_question_is_prefetched(monkeypatch):
    """每条错题单独去取题目就是最多 10 次查询 —— 必须预取。"""
    query = _patch_exam_records(monkeypatch, [_Record("[]")])

    await notification_service._get_recent_error_tags(7)

    assert query.prefetch_arg == ("question",)


@pytest.mark.asyncio
async def test_broken_json_and_missing_question_do_not_raise(monkeypatch):
    """降级不是崩：脏 JSON、空值、题目没预取到，都不能把周报任务带崩。

    **这里钉的是现状，不是理想行为**：`knowledge_tags` 不是合法 JSON 时，原实现把整个
    原串当成一个标签（`tag_list = [kt]`）—— 对"有人存了一个光杆标签字符串"是合理的兜底，
    代价是"一段坏 JSON"也会原样漏进给模型的提示词里。真要收紧得先确认库里没有光杆字符串，
    所以这次只把它写成显式断言，不悄悄改。
    """
    _patch_exam_records(monkeypatch, [
        _Record("{不是 JSON"),
        _Record(None),
        _Record("[]"),
        _Record('["保留我"]'),
        _Record(None, question_missing=True),
    ])

    tags = await notification_service._get_recent_error_tags(7)

    assert set(tags) == {"{不是 JSON", "保留我"}


@pytest.mark.asyncio
async def test_no_wrong_answers_is_not_an_error(monkeypatch):
    """一条错题都没有：返回空列表，不抛。

    这条同时说明了原来那个 bug 为什么能藏住 —— 空结果时循环根本不执行，
    AI 建议照常生成；只有真有错题的人才会踩到 AttributeError。
    """
    _patch_exam_records(monkeypatch, [])

    assert await notification_service._get_recent_error_tags(7) == []


@pytest.mark.asyncio
async def test_the_ai_tip_is_reachable_for_a_user_with_recent_wrong_answers(monkeypatch):
    """把 `_build_ai_tip` 整条走通：有错题的用户要能拿到建议。

    这是症状层面的断言 —— 上面几条测的是字段，这条测的是"AI 建议真的生成出来了"。
    """
    _patch_exam_records(monkeypatch, [_Record('["洛必达法则"]')])

    async def fake_portrait(user_id):
        return "【用户画像】机械工程"

    async def fake_weak_tags(user_id):
        return []

    class _FakeResp:
        content = "先把洛必达法则的适用条件过一遍。"

    class _FakeLlm:
        @staticmethod
        async def ainvoke(prompt):
            return _FakeResp()

    monkeypatch.setattr(notification_service, "_read_portrait", fake_portrait)
    monkeypatch.setattr(notification_service, "_get_weak_tags", fake_weak_tags)
    monkeypatch.setattr(notification_service, "llm", _FakeLlm)
    monkeypatch.setattr(notification_service, "load_prompt", lambda key: "{portrait_context}{weak_points}{error_tags}")
    monkeypatch.setattr(notification_service, "fill_prompt", lambda tpl, **kw: tpl)

    tip = await notification_service._build_ai_tip(7)

    assert tip == "先把洛必达法则的适用条件过一遍。"
