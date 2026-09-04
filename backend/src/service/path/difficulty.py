"""学习路径节点难度的统一计算规则。

路径规划智能体负责给新节点提供相对难度；这里负责边界校验、旧数据兜底
以及把同一路径内的分数归一化为可比较的折线图高度。
"""

from __future__ import annotations

import math
from typing import Any


_COGNITIVE_WEIGHTS = {
    "记忆": 1.0,
    "理解": 1.25,
    "应用": 1.55,
    "分析": 1.9,
    "评价": 2.2,
    "创造": 2.5,
}

_MODULE_OFFSETS = {
    "概念奠基": 0.0,
    "方法操作": 0.08,
    "案例应用": 0.16,
    "误区辨析": 0.12,
    "综合迁移": 0.24,
}


def clamp_difficulty_score(value: Any, default: float | None = None) -> float | None:
    """规范路径内相对难度倍数，首节点基准为 1.0。"""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(score) or score < 1.0:
        return default
    return round(min(score, 100.0), 2)


def derive_difficulty_score(
    *,
    order_index: int,
    total_nodes: int,
    cognitive_level: str = "",
    module: str = "",
    key_points_count: int = 0,
    prerequisite_count: int = 0,
) -> float:
    """根据已有教学元数据推导旧节点难度，保证同一路径内有梯度。"""
    total = max(int(total_nodes or 1), 1)
    order = max(1, int(order_index or 1))
    progress = (order - 1) / max(total - 1, 1)
    base = _COGNITIVE_WEIGHTS.get(str(cognitive_level).strip(), 1.0 + progress * 1.2)
    module_offset = _MODULE_OFFSETS.get(str(module).strip(), 0)
    complexity = min(max(int(key_points_count or 0), 0), 5) * 0.04
    prerequisites = min(max(int(prerequisite_count or 0), 0), 4) * 0.06
    progression = progress * 0.12
    return round(max(1.0, min(10.0, base + module_offset + complexity + prerequisites + progression)), 2)


def normalize_relative_difficulty(scores: list[float | None]) -> list[int]:
    """将一条路径的相对倍数映射为 20-90 的图表高度。"""
    values = [clamp_difficulty_score(score, 1.0) or 1.0 for score in scores]
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [50 for _ in values]
    return [round(20 + ((score - low) / (high - low)) * 70) for score in values]
