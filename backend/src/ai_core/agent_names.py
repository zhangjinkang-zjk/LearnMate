# -*- coding: utf-8 -*-
"""智能体在"智能体流程"面板里的显示名 —— 唯一来源。

名字是给用户看的，所以用业务方的说法，不用框架内部术语：面板面向的是学生和
培训管理者，「协同调度 / 学情诊断 / 领域知识生成 / 内容审核 / 交叉验证」能直接
说明这一步在干什么；而最初随手起的 LeaderAgent / ExecutorAgent / ReviewerAgent、
以及 ConsistencyReviewer 这类英文内部名，在界面上等于没写。

**要把"智能体"和"流程步骤"分开**：`SAVER_AGENT` 是一次落库，不是智能体，它的
显示名里就不该带"智能体"三个字。给每个环节都贴上智能体标签，是这套面板最容易
显得名不副实的地方。

**agent_id 一律不动**：它是前后端的协议键（前端按 `executor:ppt:section-3`
聚合章节卡片、按 phase.id 映射阶段、按 phase 分组审核统计）。这里只改显示名。
前端 `frontend/src/entities/agent/agentWorkflowState.js` 里有同一份字面量 ——
跨语言没法 import，改这里时记得同步那一份。
"""

# ── 角色级：面板里的一整行 ────────────────────────────
LEADER_AGENT = "协同调度智能体"          # 读大纲、排优先级、决定哪些节点并行
DIAGNOSIS_AGENT = "学情诊断智能体"        # 从访谈与测验推断能力画像
EXECUTOR_AGENT = "领域知识生成智能体"      # 按画像产出文档 / PPT / 习题 / 导图
REVIEWER_AGENT = "内容审核智能体"          # 按资源类型分派对应的审核角色
CROSS_VALIDATOR_AGENT = "交叉验证智能体"   # 逐节自洽之外，再做跨节一致性检查
SAVER_AGENT = "保存资源"                  # 落库步骤，不是智能体：显示名里不带"智能体"

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
