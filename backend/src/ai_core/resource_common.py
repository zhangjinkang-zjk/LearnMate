# -*- coding: utf-8 -*-
"""资源生成图里被两个环节共用的小工具。

现在只有 `_parse_review_response`：PPT 的分节审核环（`resource_ppt`）和图的全局审核节点
（`resource_graph`）都要用它。单独放一个文件，是为了让这两边不用互相 import —— 它们之间
已经有一条依赖（图要用 `generate_ppt_parallel`），再拉一条反向的就成环了。
"""
import json

from backend.src.utils.json_parser import parse_llm_json


def _parse_review_response(raw: str) -> dict:
    """解析 reviewer 返回的 JSON，容错处理。
    支持新格式（逐题）和旧格式（整批），统一返回含 questions 字段的 dict。"""
    try:
        result = parse_llm_json(raw)
        if not isinstance(result, dict):
            return {"passed": True, "score": 70, "feedback": raw, "questions": []}
        # exercise 新格式：包含逐题结果
        if "questions" in result and isinstance(result["questions"], list):
            return {
                "passed": result.get("overall_passed", True),
                "score": result.get("overall_score", 70),
                "feedback": result.get("overall_feedback", ""),
                "questions": result["questions"],
            }
        # 旧格式兼容（其他资源类型）
        return {
            "passed": result.get("passed", True),
            "score": result.get("score", 70),
            "feedback": result.get("feedback", ""),
            "questions": [],
        }
    except json.JSONDecodeError:
        return {"passed": True, "score": 70, "feedback": raw, "questions": []}
