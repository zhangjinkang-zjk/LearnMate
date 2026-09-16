# -*- coding: utf-8 -*-
"""智能体在"智能体流程"面板里的显示名 —— 唯一来源。

名字直接抄赛题原文。榜题「领域知识个性化生成与多智能体协同决策系统研究」
（XH-202630）的评分标准里既给了全流程，也点了角色名：

    学情画像构建 → 多智能体协同调度（诊断/生成/审核）→ 领域知识个性化生成
        → 交互反馈 → 动态决策更新
    「实现多智能体角色分工明确且协作顺畅（如学情Agent、生成Agent、审核Agent等）」
    「基于多Agent"交叉验证与辩论"机制解决垂直领域知识生成的"幻觉"问题」

所以角色名用赛题自己的词（协同调度 / 学情诊断 / 领域知识生成 / 内容审核 /
交叉验证），而不是最初随手起的 LeaderAgent / ExecutorAgent / ReviewerAgent。
评审对着评分表看界面时，"学情Agent、生成Agent、审核Agent"这几个词能逐条对上号；
`ConsistencyReviewer` 这种英文内部名更是直接对不上"交叉验证"这个得分点。

**agent_id 一律不动**：它是前后端的协议键（前端按 `executor:ppt:section-3`
聚合章节卡片、按 phase.id 映射阶段、按 phase 分组审核统计）。这里只改显示名。
前端 `frontend/src/entities/agent/agentWorkflowState.js` 里有同一份字面量 ——
跨语言没法 import，改这里时记得同步那一份。
"""

# ── 角色级：面板里的一整行 ────────────────────────────
LEADER_AGENT = "协同调度智能体"          # 赛题：多智能体协同调度
DIAGNOSIS_AGENT = "学情诊断智能体"        # 赛题：学情画像构建 / 学情Agent
EXECUTOR_AGENT = "领域知识生成智能体"      # 赛题：领域知识个性化生成 / 生成Agent
REVIEWER_AGENT = "内容审核智能体"          # 赛题：审核Agent
CROSS_VALIDATOR_AGENT = "交叉验证智能体"   # 赛题：交叉验证与辩论机制
SAVER_AGENT = "资源入库智能体"            # 非智能体，是落库步骤；原本显示内部类名 ResourceService

# ── 子智能体：每种资源一个生成角色，审核角色由生成角色派生 ──
RESOURCE_AGENT_NAMES = {
    "document": "文档生成智能体",
    "ppt": "PPT生成智能体",
    "mindmap": "思维导图生成智能体",
    "exercise": "习题生成智能体",
    "case": "案例资料生成智能体",
    "reading": "阅读材料生成智能体",
    "image": "图片生成智能体",
    "video": "视频生成智能体",
}

GENERATOR_SUFFIX = "生成智能体"
REVIEWER_SUFFIX = "审核智能体"


def resource_agent_name(resource_type: str) -> str:
    """某种资源的生成角色名。未知类型退化成一个仍然读得通的兜底名。"""
    normalized = str(resource_type or "").strip().lower()
    return RESOURCE_AGENT_NAMES.get(normalized, f"{normalized or '资源'}{GENERATOR_SUFFIX}")


def resource_reviewer_name(resource_type: str) -> str:
    """某种资源的审核角色名。

    不再用 `.replace("生成智能体", "审核智能体")` 现拼：兜底名（未知类型）里
    没有这个后缀时替换会静默失效，用户会看到一个"XX生成智能体"在干审核。
    """
    name = resource_agent_name(resource_type)
    if name.endswith(GENERATOR_SUFFIX):
        return name[: -len(GENERATOR_SUFFIX)] + REVIEWER_SUFFIX
    return f"{name}{REVIEWER_SUFFIX}"
