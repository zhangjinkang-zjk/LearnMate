"""实践教练 persona 的**反死板**守门测试。

原因是一次真实的失效：学生在进阶学习页问「教练看看我的代码」，教练连着五轮回
「你先说明交付物形态」，还给了 A/B 选项让他选字母。学生最后说「我让你读我的代码
写的错误。听懂没」，它才肯直接说 —— 而且说得很好。

问题不在措辞，在三处**结构性的硬规定**被当成了不可违反的程序：

1. 「每轮只前进一步」被读成「每轮回复都必须以问句结尾」→ 学生问什么都要换回一个反问
2. 「不直接纠错」没有例外 → 学生明确要求检查，也不点破
3. 「升级前先让他说出上一条提示告诉了他什么」是一道**闸门** → 学生不配合复述，
   教练就升不了级，两个人一起卡在同一级（那条消息问到第五次就是这个形状）

这三条已经改成"默认值 + 明确例外"。这个文件钉住那些**例外**还在 —— persona 是纯文本，
改动很容易在"精简提示词"时把例外顺手删掉，而删掉之后失效要等到学生发火才看得出来。

只断言关键短语，不断言整句 —— 允许改写措辞，不允许删掉机制。
"""

import pytest

from backend.src.utils.prompt_loader import load_prompt

PERSONA = load_prompt("classroom/coach")


def test_asking_a_question_is_a_default_not_a_mandate():
    """回复不必以问句结尾 —— 这是「每轮一步」被读歪的地方。"""
    assert "不等于" in PERSONA and "每轮都得问一句" in PERSONA


def test_not_correcting_directly_has_an_exception_for_explicit_requests():
    """学生明确说「看/检查/对不对」时，必须直接给结论。"""
    assert "例外" in PERSONA
    assert "检查" in PERSONA and "评价" in PERSONA


def test_hint_escalation_is_a_signal_not_a_gate():
    """复述不出来就照样升级 —— 否则两个人一起卡在同一级。"""
    assert "不是一道闸门" in PERSONA or "只是一个信号" in PERSONA


def test_the_persona_says_these_are_defaults_not_procedure():
    """一条总括规则：任何一条都不值得拿"把对话卡死"去执行。"""
    assert "不是流程" in PERSONA or "不是程序" in PERSONA


def test_the_flexibility_rules_did_not_replace_the_teaching_ones():
    """放松死板不等于放弃教学法 —— 这些必须还在，别拿灵活性当借口删掉。

    「允许给 / 禁止给」那对清单尤其重要：只写"别替学生做"是态度，模型会打折；
    写出**允许的替代产物**才可判定。
    """
    for clause in ("允许给", "禁止给", "提示分级", "复述验证", "关键决策留给他"):
        assert clause in PERSONA, f"{clause} 不见了"


@pytest.mark.parametrize("clause", ["先回应他说的那句话", "绝不重复", "不要给 A / B / C"])
def test_the_loop_breakers_are_still_there(clause):
    """这条是上一次失效的直接修复，不能被后来的改动挤掉。"""
    assert clause in PERSONA


def test_the_persona_covers_how_to_review_code():
    """「审核代码」是这个模块的主用途，不能只剩一句"直接给结论"。

    2026-09-30 加的：只说"要落到位置"是态度，模型会打折；写出**可判定的动作**
    （按什么顺序、给多少条、留没留余地）才管得住。其中「绝不推测」是硬边界：
    工作区块会写明哪几份没附上正文，教练对那几份只能承认没看到。
    """
    for clause in ("每条意见都落到位置", "一次说一个层次", "给出判据", "绝不推测"):
        assert clause in PERSONA, f"{clause} 不见了"


def test_code_review_still_refuses_to_write_the_patch():
    """审核能力不等于代写 —— 完整的修复补丁仍在禁止之列，最后一步留给他。"""
    assert "最后一步得他自己写" in PERSONA
