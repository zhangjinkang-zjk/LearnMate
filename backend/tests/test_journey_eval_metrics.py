# -*- coding: utf-8 -*-
"""入学一程那份记录里**算数的两个函数**：答对率怎么数、几个假学生怎么并排。

为什么要单独测这两个小函数：那份记录的全部结论就是"判分有没有区分度"，而它是由答对率
承的。数错了，读的人会得出反的结论。这里守三件事：

1. **"没判"不能算成"答错"。** 判官没给出结论时 `is_correct` 是 `None`，把它并进答错，
   报告上就成了一次"判分很严"，而实际上什么都没判 —— 同 `resource_eval.summarize` 里
   产出率那条规矩（一条都没跑是 None，不是 0.0）。
2. **按难度分开记。** 判别力几乎都落在 hard 上：唯一一次答错就出在 hard 那问上，而同一份
   底子在 medium 上全对。只报一个总答对率会把这个差别抹平。
3. **对照表要能说明它不是对照实验**（两个人问到的题不一样），别让读者把它当成 A/B。

只测纯函数：不联网、不碰数据库、不调模型。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.journey import _compare_table, _verdict_tally  # noqa: E402


def _turn(verdict, difficulty: str = "medium") -> dict:
    return {"verdict": verdict, "difficulty": difficulty}


def test_counts_correct_and_wrong():
    tally = _verdict_tally([_turn(True), _turn(False), _turn(True)])
    assert (tally["correct"], tally["wrong"], tally["total"]) == (2, 1, 3)


def test_an_unjudged_turn_is_not_counted_as_wrong():
    """判官没给结论 ≠ 学生答错。混在一起，报告会假报一次"判分很严"。"""
    tally = _verdict_tally([_turn(True), _turn(None)])
    assert tally["unjudged"] == 1
    assert tally["wrong"] == 0, "没判的那一问不该进答错"
    assert tally["correct"] == 1


def test_splits_by_difficulty():
    """唯一一次答错出现在 hard 上 —— 这个信息只在按难度分开时才看得见。"""
    tally = _verdict_tally([
        _turn(True, "medium"), _turn(True, "medium"),
        _turn(False, "hard"), _turn(True, "hard"),
    ])
    assert tally["by_difficulty"]["medium"] == {"correct": 2, "judged": 2}
    assert tally["by_difficulty"]["hard"] == {"correct": 1, "judged": 2}


def test_a_missing_difficulty_gets_its_own_bucket():
    tally = _verdict_tally([{"verdict": True}])
    assert list(tally["by_difficulty"]) == ["?"]


def test_empty_turns_do_not_divide_by_zero():
    """一个学生跑到一半挂了也得能出表。"""
    tally = _verdict_tally([])
    assert tally["total"] == 0 and tally["by_difficulty"] == {}
    assert "| doc-only | 0/0 | （没有题） |" in _compare_table(
        [{"student": "doc-only", "turns": []}]
    )


def test_the_compare_table_puts_the_students_side_by_side():
    artifacts = [
        {"student": "doc-only", "turns": [_turn(True, "hard"), _turn(True, "hard")]},
        {"student": "shaky", "turns": [_turn(False, "hard"), _turn(True, "medium")]},
    ]
    table = _compare_table(artifacts)
    assert "| doc-only | 2/2 | hard 2/2 |" in table
    assert "| shaky | 1/2 | hard 0/1、medium 1/1 |" in table


def test_the_compare_table_carries_the_unjudged_count():
    """没判的那一问要在表里露出来，不能悄悄从分母里消失。"""
    table = _compare_table([{"student": "shaky", "turns": [_turn(True), _turn(None)]}])
    assert "1/2" in table and "另有 1 问没判" in table


def test_the_table_uses_a_precomputed_tally_when_there_is_one():
    """`run` 落盘时已经算过一份，别重复算（算两次还可能不一致）。"""
    artifact = {"student": "doc-only", "turns": [_turn(True)],
                "tally": {"correct": 9, "wrong": 0, "unjudged": 0, "total": 9,
                          "by_difficulty": {"hard": {"correct": 9, "judged": 9}}}}
    assert "| doc-only | 9/9 | hard 9/9 |" in _compare_table([artifact])
