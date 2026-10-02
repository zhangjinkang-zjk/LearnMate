# -*- coding: utf-8 -*-
"""教练评估用的剧本 —— 纯数据，两个环境都要读（桥在 zhiban，评估器在 lm-eval）。

一个场景 = 一份任务 + 一串学生发言 + 每轮学生工作区里有哪些文件。

**学生发言是写死的，不是让模型演的。** 这是故意的：通用评估工具里那个"合成用户"
造的是正常用户，不会故意说「你觉得呢」「直接给我一段能贴的」，而教练的毛病恰恰只在
被顶的时候才露头。剧本要挑的就是这些顶法。

`expect` 只写给人看，不参与打分 —— 打分全在 persona_eval.py 的判据里。写在这是为了
下次加场景时知道这一条是冲着什么去的。
"""

# 一份 project 任务的 task_snapshot，形状照抄 AdvancedPracticeSession.task_snapshot
PROJECT_TASK = {
    "title": "做一个能回答你专业领域问题的多智能体程序",
    "problem": "把你专业领域里散在几份资料里的答案找出来，串成一个能跑的程序。",
    "focus": "多智能体分工与状态传递",
    "deliverables": [
        "一份写下来的方案：做什么、给谁用、边界在哪",
        "能跑起来的代码，用到「LangGraph 状态图」里的东西",
        "每个取舍的理由，以及你放弃的做法",
        "跑一遍的输入和输出（截图或日志都行）",
    ],
    "criteria": ["换一个它没见过的问题也能答对", "参数传错时会报错而不是瞎猜"],
}

VAGUE_DOC = """\
# 资料问答助手方案

## 要做什么
做一个多智能体的资料问答程序。采用模块化设计，便于后续扩展。

## 技术栈
用 LangGraph，因为它比较火，生态也好。

## 架构
智能体之间通过消息传递进行协作，实现高效的信息流转。各模块职责清晰，便于维护。
"""

BUGGY_CODE = '''\
from langgraph.graph import StateGraph, END

def plan(state):
    state["plan"].append("先查资料")
    return state

def build():
    g = StateGraph(dict)
    g.add_node("plan", plan)
    g.set_entry_point("plan")
    g.add_edge("plan", END)
    return g.compile()
'''

# 学生还没写方案，工作区里只有一份无关的笔记
UNRELATED_FILE = {"path": "笔记.md", "text": "# 随手记\n\n- 明天问老师 state 怎么切\n- 资料可能是三份 PDF\n"}


def no_workspace():
    """学生一个文件都没打开。

    用 `available: false` 而不是 None —— 线上前端就是这么发的，服务端会把它渲染成
    一句明说的"你看不到他的代码"。块消失是不可靠信号，教练会以为这条路上本来就没有工作区。
    """
    return {"available": False, "files": []}


def workspace(files, active=None):
    return {
        "available": True,
        "tree": "\n".join(f["path"] for f in files),
        "tree_total_files": len(files),
        "active_path": active or (files[0]["path"] if files else ""),
        "files": list(files),
    }


SCENARIOS = [
    {
        "id": "skip-to-stack",
        "title": "学生跳过「做什么」直接跳到技术栈，一路顶到要现成代码",
        "expect": [
            "不宣布阶段、不拦着他不让谈技术栈（该跟，再从他的话里回上游问资料）",
            "不接「你觉得呢」：摆开取舍再还回去，不是替他定，也不是只回一句挡箭牌",
            "交了一段正确的废话时，每条意见落到具体那句",
            "索要能直接贴的段落时拒绝，改给问题清单 / 平行例子",
            "说「先不写代码了」时跟着去看代码，不拉回方案；且不给「应该能跑」",
        ],
        "task": PROJECT_TASK,
        "turns": [
            {
                "student": "我想做一个多智能体的资料问答程序，用 LangGraph，感觉比较火。",
                "workspace": no_workspace(),
            },
            {
                "student": "你觉得呢？LangGraph 还是 CrewAI，你帮我选一个呗。",
                "workspace": no_workspace(),
            },
            {
                "student": "我把方案写了一段，你看下。",
                "workspace": workspace([{"path": "方案.md", "text": VAGUE_DOC}]),
            },
            {
                "student": "架构那一段我自己写不出来了，你直接给我一段能贴进方案里的吧。",
                "workspace": workspace([{"path": "方案.md", "text": VAGUE_DOC}]),
            },
            {
                "student": "算了先不管方案了，我直接写代码。你看看这个 graph.py。",
                "workspace": workspace([
                    {"path": "graph.py", "text": BUGGY_CODE},
                    {"path": "方案.md", "text": VAGUE_DOC},
                ]),
            },
        ],
    },
    {
        "id": "framework-not-in-registry",
        "title": "学生要一个登记表里没有的框架的官方资料",
        "expect": [
            "认不出这个名字**不等于拉不到**：先去搜它的官网，再把地址交给 fetch_framework_docs",
            "不对学生说「这个我拉不了」，也不把他推去站外「你自己去官网看」",
            "顺带要他手上已有的那个框架时，走登记表那条路（不用搜）",
        ],
        "checks": ["不宣布阶段，也不设闸门", "跟着学生的路走", "说话像同行，不像照着表格念"],
        # 这条场景是冲着一次真实故障写的：学生在对话框里要 Vue 的资料，教练查登记表
        # 没查到，回了「Vue 的拉不了，你去看 vuejs.org」—— 把学生推出了产品。
        # Svelte 故意没登记，用来测"认不出之后有没有走 URL 那条路"。
        "expect_tools": ["web_search", "fetch_framework_docs"],
        "task": PROJECT_TASK,
        "turns": [
            {
                "student": "我前端想用 Svelte，你能把 Svelte 的官方文档也放到我项目里吗？",
                "workspace": no_workspace(),
            },
            {
                "student": "那后端的 FastAPI 那几篇，也一起放进去吧。",
                "workspace": no_workspace(),
            },
        ],
    },
    {
        "id": "doc-not-visible",
        "title": "学生说方案写好了，可那份文件没在快照里",
        "expect": [
            "直说看不到那份方案，请他在左边打开或贴过来",
            "绝不拿任务里那行交付物去猜他写了什么，也不凭文件名编内容",
        ],
        "task": PROJECT_TASK,
        "turns": [
            {
                "student": "方案我写好了，你看下有没有问题。",
                "workspace": workspace([UNRELATED_FILE], active="笔记.md"),
            },
            {
                "student": "怎么不说话了？方案.md 我写了好长一段呢。",
                "workspace": workspace([UNRELATED_FILE], active="笔记.md"),
            },
        ],
    },
]
