# -*- coding: utf-8 -*-
"""知识库使用模式固定为参考模式。

strict（严格资料模式）一律不启用 —— 这既是产品决定（知识库只作参考，不作唯一依据），
也是当前的必要选择：知识库为空时 strict 的提示词会让模型只输出"待补充"。

这条测试盯的是"不许有人把 strict 悄悄放回来"。原先 strict 有两条触发路径
（answers 里的显式模式、user_notes 里的关键词），两条都要保证已失效。
"""

import pytest

from backend.src.service.resource.generation_context import infer_rag_mode


@pytest.mark.parametrize(
    "answers,user_notes",
    [
        (None, None),
        (None, ""),
        ({}, ""),
        # 原先的路径一：answers 里显式指定
        ({"rag_mode": "strict"}, ""),
        ({"rag_mode": "source_only"}, ""),
        ({"rag_mode": "knowledge_only"}, ""),
        ({"knowledge_mode": "strict"}, ""),
        # 原先的路径二：user_notes 里的关键词
        (None, "只根据这份资料讲"),
        (None, "仅根据上传的资料"),
        (None, "严格按照资料，不要扩展"),
        (None, "不要扩展"),
        (None, "不扩展"),
        (None, "只用上传资料"),
        (None, "按这份资料来"),
        # 两条同时
        ({"rag_mode": "strict"}, "只根据资料"),
    ],
)
def test_rag_mode_is_always_reference(answers, user_notes):
    assert infer_rag_mode(answers, user_notes) == "reference"


def test_rag_mode_survives_the_real_call_shape():
    """按真实调用方式过一遍：make_generation_state 只传这两个参数。"""
    assert infer_rag_mode({"rag_mode": "strict", "knowledge_mode": "strict"}, "严格按照资料") == "reference"
