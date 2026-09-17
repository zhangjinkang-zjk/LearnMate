from backend.src.service.exam.service import _prepare_questions_for_storage


def test_choice_answers_are_rebalanced_without_changing_correct_content():
    questions = [
        {
            "question_type": "single_choice",
            "content": f"第 {index + 1} 题",
            "options": ["A. 正确内容", "B. 干扰项一", "C. 干扰项二", "D. 干扰项三"],
            "answer": "A",
        }
        for index in range(5)
    ]

    prepared = _prepare_questions_for_storage(questions)

    answers = [item["answer"] for item in prepared]
    # 5 道题 4 个选项：正确项要铺满 A/B/C/D 而不是全挤在同一个位置。
    # 具体顺序是打散的（种子来自题干，避免形成 A/B/C/D 的可预测循环），所以这里只钉分布。
    assert sorted(answers) == ["A", "A", "B", "C", "D"]
    for item in prepared:
        correct = next(option for option in item["options"] if option.startswith(f"{item['answer']}."))
        assert correct.endswith("正确内容")

    # 同一批题目重复准备必须得到同样的排布，否则每次落库/刷新都会把已存的题重排一遍。
    assert _prepare_questions_for_storage(questions) == prepared


def test_multiple_choice_answer_is_mapped_with_options():
    question = {
        "question_type": "multi_choice",
        "options": ["A. 正确一", "B. 干扰项", "C. 正确二", "D. 干扰项"],
        "answer": ["A", "C"],
    }

    leading_choice = {
        "question_type": "single_choice",
        "options": ["A. 正确", "B. 干扰一", "C. 干扰二", "D. 干扰三"],
        "answer": "A",
    }
    prepared = _prepare_questions_for_storage([leading_choice, question])[1]

    assert prepared["answer"] == ["B", "D"]
    selected = [option for option in prepared["options"] if option[0] in prepared["answer"]]
    assert {option[3:] for option in selected} == {"正确一", "正确二"}
