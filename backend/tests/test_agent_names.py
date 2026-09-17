# -*- coding: utf-8 -*-
"""智能体显示名。

这些名字是纯展示字符串 —— 写错了不会报错、不会让别的测试变红，只会让界面上、
显示 LeaderAgent / ResourceService 这类内部类名。所以在这里钉住。

面板面向学生和培训管理者，所以名字要说清"这一步在干什么"，也不能带英文内部名。
「协同调度 / 学情诊断 / 领域知识生成 / 内容审核 / 交叉验证」就是这几个环节在
业务上的叫法。

另外要把"智能体"和"流程步骤"分开：落库那一步不是智能体，它的显示名里就不该带
"智能体" —— 否则整排阶段看下来每个环节都是"智能体"，反而说不清哪一步真的有
智能体在做决策。
"""

import ast
import re
from pathlib import Path

import pytest

from backend.src.ai_core import agent_names

FRONTEND_STATE = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "entities" / "agent" / "agentWorkflowState.js"
)

# 最早随手起的内部名，一个都不该再作为显示名出现在任何一侧
LEGACY_NAMES = ("LeaderAgent", "ExecutorAgent", "ReviewerAgent", "ConsistencyReviewer", "ResourceService")

# 真正的智能体角色。落库那一步（SAVER_AGENT）不在里面 —— 它不是智能体，
# 由 test_the_saver_step_is_not_named_as_an_agent 单独钉住。
ROLE_NAMES = (
    agent_names.LEADER_AGENT,
    agent_names.DIAGNOSIS_AGENT,
    agent_names.EXECUTOR_AGENT,
    agent_names.REVIEWER_AGENT,
    agent_names.CROSS_VALIDATOR_AGENT,
)


def _frontend_source() -> str:
    if not FRONTEND_STATE.exists():
        pytest.skip("前端不在这个工作区里，跨语言对齐检查无从谈起")
    return FRONTEND_STATE.read_text(encoding="utf-8")


# ── 角色名 ────────────────────────────────────────────

def test_role_names_are_chinese_and_end_with_the_agent_suffix():
    """Role names are user-facing: no internal class names, and every one reads as an agent."""
    for name in ROLE_NAMES:
        assert name.endswith("智能体"), f"{name} 读起来不像一个角色名"
        assert not re.search(r"[A-Za-z]", name), f"{name} 里还带着英文内部名"


def test_role_names_say_what_each_agent_does():
    """名字要能直接读出这一步在干什么，而不是一个看不出内容的角色头衔。"""
    assert "协同调度" in agent_names.LEADER_AGENT          # 调度：决定顺序与并行度
    assert "学情" in agent_names.DIAGNOSIS_AGENT            # 诊断：推断能力画像
    assert "领域知识" in agent_names.EXECUTOR_AGENT          # 生成：产出各领域资源
    assert "生成" in agent_names.EXECUTOR_AGENT
    assert "审核" in agent_names.REVIEWER_AGENT             # 审核：校验内容质量
    assert "交叉验证" in agent_names.CROSS_VALIDATOR_AGENT   # 跨节一致性检查


def test_the_saver_step_is_not_named_as_an_agent():
    """落库是一次数据库写入，不是智能体。

    把它也叫成"智能体"，整排阶段看下来每个环节都是"智能体"，反而说不清哪一步
    真的有智能体在做决策 —— 这恰恰是这套面板最容易显得名不副实的地方。
    """
    assert "智能体" not in agent_names.SAVER_AGENT
    assert agent_names.SAVER_AGENT.strip()


def test_role_names_are_distinct():
    assert len(set(ROLE_NAMES)) == len(ROLE_NAMES), "两个角色同名的话界面上分不出谁在干活"


# ── 资源子智能体 ──────────────────────────────────────

def test_every_resource_sub_agent_reads_as_a_generator():
    for resource_type, name in agent_names.RESOURCE_AGENT_NAMES.items():
        assert name.endswith(agent_names.GENERATOR_SUFFIX), f"{resource_type}: {name}"


def test_resource_reviewer_name_derives_from_the_generator_name():
    assert agent_names.resource_reviewer_name("ppt") == "PPT审核智能体"
    assert agent_names.resource_reviewer_name("document") == "文档审核智能体"
    # 大小写/空格不该影响结果（调用点传进来的类型未必规范化过）
    assert agent_names.resource_reviewer_name(" PPT ") == "PPT审核智能体"


def test_unknown_resource_type_still_gets_a_readable_reviewer_name():
    """未知类型走兜底名时也要派生出审核角色。

    这里以前是靠 `resource_agent_name(rt).replace("生成智能体", "审核智能体")` 现拼，
    兜底名里没有那个后缀时替换会静默失效 —— 用户会看到一个"xx生成智能体"在干审核。
    """
    fallback = agent_names.resource_agent_name("brand_new")
    assert fallback == "brand_new生成智能体"

    assert agent_names.resource_reviewer_name("brand_new") == "brand_new审核智能体"
    assert "生成" not in agent_names.resource_reviewer_name("brand_new")


def test_empty_resource_type_does_not_produce_a_broken_name():
    assert agent_names.resource_agent_name("") == "资源生成智能体"
    assert agent_names.resource_agent_name(None) == "资源生成智能体"
    assert agent_names.resource_reviewer_name(None) == "资源审核智能体"


# ── 跨语言对齐：前端没法 import 这个模块，只能靠字面量同步 ──

def _frontend_resource_labels(source: str) -> dict[str, str]:
    block = re.search(r"export const resourceAgentLabels = \{(.*?)\n\}", source, re.S)
    assert block, "前端的 resourceAgentLabels 不见了，同步检查要跟着改"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


def test_frontend_resource_labels_match_the_backend():
    """两边对不上时，同一批资源在弹窗里和抽屉里会叫两个名字。"""
    source = _frontend_source()

    assert _frontend_resource_labels(source) == agent_names.RESOURCE_AGENT_NAMES


def test_frontend_phase_tables_match_the_backend():
    """前端的阶段表在后端没推 agent_name 时当兜底，两边必须逐项一致。

    `cross_validator` 不在这张表里，也不该在：它不是阶段，而是审核阶段下的一个
    子角色。它的事件带 phase="reviewer" 和现成的 agent_name，抽屉按 phase 归并到
    "质量审核"，所以前端不需要它的字面量。
    """
    source = _frontend_source()
    expected = {
        "leader": agent_names.LEADER_AGENT,
        "executor": agent_names.EXECUTOR_AGENT,
        "reviewer": agent_names.REVIEWER_AGENT,
        "saver": agent_names.SAVER_AGENT,
        "diagnosis": agent_names.DIAGNOSIS_AGENT,
    }

    found = dict(re.findall(r"\{ id: '(\w+)', label: '[^']*', agentName: '([^']+)' \}", source))

    for phase, name in expected.items():
        assert found.get(phase) == name, f"阶段 {phase} 两边对不上：前端 {found.get(phase)!r} / 后端 {name!r}"
    assert "cross_validator" not in found, "交叉验证是子角色，不该混进阶段表"


@pytest.mark.parametrize("legacy", LEGACY_NAMES)
def test_legacy_internal_names_are_gone_from_the_frontend(legacy):
    assert legacy not in _frontend_source(), f"{legacy} 这类内部名不该出现在用户看得见的界面上"


# 后端同理，而且这条以前是缺的：上面那个用例只读前端文件，所以
# `resource/service.py` 里硬编码的 `'agent_name': 'ResourceService'` 一直没人发现 ——
# 学习路径那条生成流的事件流里会露出一个用户看不懂的类名，而同一个"保存"阶段在
# 任务制那条路上叫"保存资源"，两条路各叫各的。
#
# 这里查的是**字符串常量**，不是类名本身：`class ResourceService` 和
# `ResourceService.generate_stream(...)` 都是正常代码，只有被当成字符串用的才是显示名。
# 用 ast 而不是正则去扫文本：正则会把注释里提到这个名字的地方也算成违规，
# 而注释里恰恰最需要能写出"这里原本硬编码了某某"。
@pytest.mark.parametrize("legacy", LEGACY_NAMES)
def test_legacy_internal_names_are_not_used_as_display_strings_in_the_backend(legacy):
    backend_src = Path(__file__).resolve().parents[2] / "backend" / "src"
    offenders = []
    for path in sorted(backend_src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == legacy:
                offenders.append(f"{path.relative_to(backend_src)}:{node.lineno}")

    assert not offenders, f"{legacy} 被当成字符串常量用了（多半是显示名）：{offenders}"
