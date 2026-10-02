# -*- coding: utf-8 -*-
"""内置领域智能体 —— **一个领域一条声明**。

这张表就是"可插拔"的那根口子：换一个行业，动的是这里的一条声明，不是流程代码。
声明里带着这个领域**独有**的四样东西，其余全流程共用：

    persona          这个领域的人怎么说话、按什么教学法推进（人格）
    tools            它能动什么（越权工具就是越界能力）
    workspace_kind   它的产出长什么样 —— **前端按这个选界面**
    directions       哪些学习方向该匹配到它（画像进来时用）

学员那边共用的是同一套东西：画像诊断、路径与节点、多角色生成流水线、审核与纠偏。
**这正是"领域可迁移"要展示的**：换域不重写流水线，只换声明。

## workspace_kind 是前后端的协议键

写一个前端不认识的 kind，界面会退化成最简形态（见 `AdvancedLearningPage.vue` 的分发），
所以这里只放前端已经支持的形态。新增一种形态意味着**同时**加一个前端组件 ——
省掉的是"切换那一层的判断"，不是"新界面的工作"，这一点别对外说满。

## 存量库里的那条系统行

`agent_key` 这一列是后加的，存量行是 NULL。它们都是开发教练那一份，首次按 key 取时会被
认领（见 `classroom_chat._claim_legacy_row`）—— 没有这一步，老用户身上会凭空多出一条
同名的教练行。
"""
from dataclasses import dataclass
import hashlib
import json

from backend.src.utils.prompt_loader import load_prompt

# 界面形态。前端 `features/advanced/` 下有同名的组件。
WORKSPACE_CODE = "code"                              # 代码工作区（文件 + 编辑器）
WORKSPACE_CLASSROOM_REHEARSAL = "classroom_rehearsal"  # 课堂演练台（分环节预演）

# 匹配不上任何方向时用谁。也是"老用户身上那条系统行"认领的对象。
DEFAULT_AGENT_KEY = "coach"


@dataclass(frozen=True)
class DomainAgent:
    key: str
    name: str
    scene: str                       # 一句话：这个智能体是来干什么的（给界面用）
    persona: str
    tools: tuple[str, ...]
    workspace_kind: str
    directions: tuple[str, ...] = ()

    def definition_hash(self) -> str:
        """定义指纹：name/persona/tools 任一变化都会变。

        用途和以前一样 —— 进程内缓存按它判断"代码里的定义换了没有"，换了就覆盖库里的行
        并踢掉 Brain 缓存，旧人格立刻失效。**不含 scene / directions**：改一句给界面看的
        介绍，不该导致所有学员的智能体行被重写。
        """
        blob = json.dumps(
            {"key": self.key, "name": self.name, "persona": self.persona, "tools": list(self.tools)},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.md5(blob.encode("utf-8")).hexdigest()[:16]

    def for_client(self) -> dict:
        """给前端的形态：**不带 persona / tools**。

        人格是服务端资产，发到前端只会多一个能被读出来的地方；工具白名单更是越权清单。
        前端选界面只需要 kind，介绍只需要 scene。
        """
        return {
            "key": self.key,
            "name": self.name,
            "scene": self.scene,
            "workspace_kind": self.workspace_kind,
        }


# 开发教练的工具白名单：只留知识库 / 搜索 / 画像 / 记忆，剔除生成资源、出题、PPT、图片、
# 动画、视频、路径与 skill 管理。
_COACH_TOOLS = (
    "search_knowledge_base",
    "web_search",
    # 有了它教练才能**读到**官网那一页，而不只是看到一句摘要。学生问"这个 API 怎么调"、
    # "这个项目骨架里有什么"，摘要答不了，正文能答。它是一个只读工具，和上面几个同一性质。
    "read_web_page",
    "read_portrait",
    "search_memory",
    "get_used_history",
    # 写方案文档。**它是这里唯一一个"会改东西"的工具**，但改的不是服务端的数据 ——
    # 落盘在浏览器里，服务端只负责把内容带出去（见 ai_core/tools/workspace.py）。
    # 代码代笔仍然禁止，所以这里只有写文档的一个，没有写代码的。
    "write_design_doc",
    # 拉框架官方文档放进学生的项目。和上面那个同理：服务端只把"要哪几个框架"发出去，
    # 正文的抓取和写盘都在浏览器里做（见 ai_core/tools/workspace.py）。
    "fetch_framework_docs",
)

# 幼儿园教学导师的工具白名单。**和开发教练不是同一份**，这不是偷懒，是领域差异：
# 幼师不会去拉 LangChain 的官方文档，那个工具在这儿只会被误用；反过来，幼师的产出是
# 活动方案，所以 `write_design_doc` 留着（同一个工具，标题和正文由人格决定）。
_PRESCHOOL_TOOLS = (
    "search_knowledge_base",
    "web_search",
    "read_web_page",
    "read_portrait",
    "search_memory",
    "get_used_history",
    "write_design_doc",
)


COACH = DomainAgent(
    key=DEFAULT_AGENT_KEY,
    name="LearnMate 实践教练",
    scene="带你做出自己的智能体项目，并在关键取舍上说清理由",
    persona=load_prompt("classroom/coach"),
    tools=_COACH_TOOLS,
    workspace_kind=WORKSPACE_CODE,
)

PRESCHOOL = DomainAgent(
    key="preschool",
    name="LearnMate 幼教导师",
    scene="陪你把一节幼儿园活动从设计到上台讲完 —— 台下坐着一个班",
    persona=load_prompt("classroom/preschool_mentor"),
    tools=_PRESCHOOL_TOOLS,
    workspace_kind=WORKSPACE_CLASSROOM_REHEARSAL,
    # 只列**能确定是学前教育**的词。列宽了会误伤（"教育"两个字到处都是），
    # 列窄了最多退回到默认教练 —— 学员还能自己切（切换按钮存在的意义之一）。
    directions=("幼儿园", "幼师", "学前", "幼儿", "保育", "早教", "托育"),
)

_AGENTS: dict[str, DomainAgent] = {agent.key: agent for agent in (COACH, PRESCHOOL)}


def all_agents() -> list[DomainAgent]:
    """全部内置领域智能体，顺序稳定（默认那个在最前）。"""
    return list(_AGENTS.values())


def get_agent(key: str | None) -> DomainAgent | None:
    """按 key 取；认不出返回 None。

    **认不出不等于出错**：可能是存量的 NULL、也可能是前端传来一个过期 key。调用方据此
    退回默认领域（见 `resolve_agent`），而不是抛异常把学员挡在门外。
    """
    return _AGENTS.get(str(key or "").strip())


def match_direction(direction: str) -> DomainAgent:
    """学习方向 → 默认领域智能体。

    这是"系统会按照您的初始画像匹配智能体"那句话的实现：**先看方向里有没有这个领域的
    特征词**，没有就用默认教练。刻意不做模型判断 —— 这一步每次进页面都要跑，而且判错的
    代价只是"默认选中了另一个"，学员自己一点就换（那正是切换按钮存在的意义）。
    """
    text = str(direction or "").strip().casefold()
    if text:
        for agent in all_agents():
            if any(word.casefold() in text for word in agent.directions):
                return agent
    return COACH


def resolve_agent(key: str | None, direction: str = "") -> DomainAgent:
    """已选的 key 优先，认不出就按方向匹配，再认不出就默认。

    存的 key 认不出（代码里删过这个领域）时不报错 —— 记着的那个领域已经不存在了，
    按现在的画像重新匹配一次才是学员想要的。
    """
    return get_agent(key) or match_direction(direction)
