# -*- coding: utf-8 -*-
"""进阶实践任务智能体：**它出的题直接就是学生接下来要做的事。**

## 为什么单测测不到

`backend/tests/test_advanced_task_scheduling.py` 测的是"什么时候该跑生成"（快照年龄、
并发闸、失败不许覆盖已有结果）—— 它把 `generate_agent_task_set` 整个换成假的。
**没人测过它真的吐出什么。** 而它的产出会原样落到进阶学习页上，学生照着做一周。

## 走真的那条路

    build_advanced_tasks(profile, path, mastery)      ← 真实兜底（服务端自己那份）
    generate_agent_task_set(user_id, profile, path, mastery, milestone, fallback)
        ├─ _agent_context(...)     真实上下文组装
        ├─ _build_agent_prompt(...) 真实提示词填充
        ├─ llm.ainvoke(...)         真模型调用
        └─ _normalise_agent_tasks(...) 真实规范化

和后台作业 `_run_agent_generation` 里那两行完全一致（`service.py:885` 与它的调用方）。
**唯一的差别是数据库**：这里不建快照行，直接把整轮的结果留在 `results/` 里。
`user_id` 只被模型池拿去排队，不读用户表。

## 判据抄自哪里

逐条对着 `prompts/advanced/task_generator.yaml` 里的 14 条要求写，不自己加规矩。
每条判据都写成**近乎机械**的（词表、字数、标签是否出现），因为判官和被测是同一个模型 ——
让它"读一读觉得好不好"是给自己发通行证。判不出机械判据的那些（任务有没有意思、
难度是否真的合适）**不判**，只在报告里把原文摊开给人看。

## "机械"不等于"有区分度"——这两件事必须分开报

十四条规定里有六条（结构 / 字段 / 黑话 / 产品话术 / summary 推荐 / 超长）测的是
**"模型有没有照抄提示词里那张清单"**，而清单就写在提示词里 —— 一个及格线的模型必然全过，
挂了只能说明它崩了。**把它们和真判据混在一张表里打分，整体观感会被刷成"几乎满分"，
而实际上真的会挂的只有三条。**（落盘的两份报告就是这样：10 条判据里 9 条从没挂过，
唯一挂过的 `没有编造数字` 还是误报 —— 见下面 `check_fabricated_numbers` 的说明。）

所以报告按三组出，判据挂哪一组由每条 verdict 的 `group` 字段决定：

    quality   真判据。会挂，挂了说明模型干了错事。
    contract  契约符合性。预期恒过，挂了说明它没照提示词输出，**不说明质量**。
    info      信息项。不计分（`兜底顶替` 在这里，它的 `ok` 恒为 True）。

## 判官和被测是同一个模型

`llm_config.llm`，而 `pool="eval"` **只是按 (user_id, pool) 分的并发信号量键，不是另一个
模型**（`llm_config._user_pool_async`）。所以：

- 判官只留一条口径明确的（标签匹配），且它的两半口径**是反的** —— 覆盖判定要保守
  （宁可漏报），越界判定要宁可多报，见 `_TAG_JUDGE_PROMPT` 里分开写的那两条。合成一个
  口径必然牺牲一头：要它认改述，就得容忍它放行边缘情况。
- 判官报错时**如实标出来**，退回逐字匹配并在结论里写明是退回来的。
- 判官的结论和机械匹配的数字**一并打出来**，两者不一致时读者要能一眼看出差在哪。

## 两条判据的写法是刻意收窄的，别照字面放开

- **产品话术**（要求 10）原文写的是"不要提及 AI、智能体、系统会根据你、个性化推荐"。
  但**这个领域的学习者本身就在学"智能体开发"**，任务里出现「智能体」是内容，不是话术。
  所以这里判的是**产品自我中心的那几句**（"系统会根据你…""为你推荐…"），不是那个名词。
- **「方案」**（要求 14 的禁词之一）带了个限定："当名词兜底用时"。机械判不了这个限定，
  所以不放进禁词表，只在报告里把含它的句子列出来给人抽检。

## 一个必须单独计数的东西：兜底悄悄顶替

`_normalise_agent_tasks` 在**任何字段缺失或为空**时会用兜底任务里的那一份顶上
（`_clean_text(raw.get("title"), fallback["title"], 42)`），而返回的 `source` 仍然是
`"agent"` —— 也就是**对外是成功，学生看到的却可能是模板原文**。这不是 bug（兜底正是
为这个准备的），但它让"智能体到底写了几个字段"从对外结果里看不出来。所以这里逐个字段
和兜底比对，把顶替掉的列出来。

## 什么算不合格（`group=quality` 那三条）

- 任务里出现**未完成节点**的知识标签（要求 2：不要围绕下一步出题）；
- project 没有跨到 3 个已完成标签（要求 5：那就成了单点练习，不是"综合"）；
- 正文里出现**带小数点或三位以上**的数，而输入上下文里没有它（要求 12）。两位整数不判，
  理由见 `_number_tokens` —— 那一刀是拿三轮真实产出定的。

**那个"3"是提示词自己写的**（yaml 要求 5：`至少串起已完成节点中的 3 个知识标签`），不是
评估自定的门槛。12 个已学标签里命中 3 个 = 25%，确实低 —— 但要抬它得**先改提示词**，
评估跟着走；评估自己抬等于换了一把尺子量。

## 判不到的部分（写清楚，不然读的人会当成结论）

- **任务难不难、对不对、值不值得做** —— 判不了。这里只判它有没有违反自己声明的规矩。
- **契约符合性那六条基本测不出东西**：清单在提示词里，模型照抄就过。
- **通过率不是统计量**：生成温度是 `llm_config._BASE_TEMPERATURE`（0.3）且无种子，
  3 轮是 3 次采样。判官那份是 0.0，但被测那份不是 —— 这是有意的（生产就是这个温度，
  把被测对象钉死在 0 等于换了一条链路来测）。
- **"已完成节点"是编的**：`eval` 里这两份路径是合成的。真库里的节点是模型按学科生成的，
  标签质量另说。

## 怎么跑

    F:/anaconda3/envs/zhiban/python.exe eval/task_eval.py             # 两个学习者 × 3 轮
    F:/anaconda3/envs/zhiban/python.exe eval/task_eval.py --rounds 1  # 只想看一眼
    F:/anaconda3/envs/zhiban/python.exe eval/task_eval.py --learner algo   # 只跑 B
    F:/anaconda3/envs/zhiban/python.exe eval/task_eval.py --raw       # 只打原文不判分

**默认两个学习者都跑**，理由在 `LEARNERS` 上方那段：这套东西的卖点是"跟着你学过的节点
出题"，只跑一个人就分不清"题目跟着节点走"和"题目对谁都一样"。一个人时那两份落盘报告
（都是学习者 A）正是这个缺陷的样子。
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RESULTS_DIR = REPO_ROOT / "eval" / "results"

ROUNDS = 3
# 生成发生在后台作业里，超时是 120 秒（`ADVANCED_AGENT_TIMEOUT_SECONDS`）。这里比它宽一点，
# 是为了把"超时"和"卡住"分开：真超时的话生产那边已经降级兜底了，评估该看到的是这件事本身。
CALL_TIMEOUT_SECONDS = 180

# ═══════════════════════════════════════
#  固定的世界：一个"刚学完一个里程碑"的学习者
# ═══════════════════════════════════════
#
# 这不是随便编的一个人，每一处都是为了**让判据能落地**：
#
#   · 5 个已完成节点、12 个知识标签 —— project 要求跨到 3 个标签，得有得跨；
#   · 第 6 个节点是「已解锁、尚未完成」，标签是 HNSW 索引 / 混合检索 / 重排序 ——
#     这三个词**绝不能出现在任务里**（要求 2），它们是否出现就是一条硬判据；
#   · 掌握度记录里留一个 0.45 的弱项 —— 让"锚点/重点能力"有东西可挑。
#
# 领域选智能体开发，是因为产品面向的就是这批人（判「智能体」这个词是不是话术时，
# 这一点必须先成立）。

LEARNER_A_PROFILE = {
    "identity": "在校学生",
    "major": "计算机科学与技术",
    "grade": "大三",
    "goal": "就业",
    "direction": "智能体开发",
}

LEARNER_A_PATH = {
    "path_id": 90001,
    "goal": "智能体开发",
    "stage": "基础学习",
    # 已解锁、**尚未完成** —— 服务端会把它塞进 current_node，并注明"不要围绕它出题"
    "current_node_id": 6,
    "diagnosis": {"weak_points": [{"name": "结构化输出", "accuracy": 0.45}]},
    "nodes": [
        {"id": 1, "order_index": 1, "title": "大模型调用基础", "status": "completed",
         "summary": "把一个请求发出去、把回复读回来，搞清楚消息里每种角色各自负责什么。",
         "knowledge_tags": ["API 调用", "消息角色", "流式输出"]},
        {"id": 2, "order_index": 2, "title": "提示词设计", "status": "completed",
         "summary": "把要求写清楚，让模型稳定按想要的结构回答。",
         "knowledge_tags": ["提示词结构", "少样本示例"]},
        {"id": 3, "order_index": 3, "title": "工具调用", "status": "completed",
         "summary": "让模型自己决定什么时候去调一个函数，并把参数传对。",
         "knowledge_tags": ["函数调用", "结构化输出", "参数校验"]},
        {"id": 4, "order_index": 4, "title": "多智能体协作", "status": "completed",
         "summary": "把一件事拆给几个角色，让它们按顺序交接。",
         "knowledge_tags": ["角色分工", "状态传递"]},
        {"id": 5, "order_index": 5, "title": "检索增强生成", "status": "completed",
         "summary": "先查资料再回答，把查到的内容当成依据用起来。",
         "knowledge_tags": ["文本切块", "向量检索"]},
        {"id": 6, "order_index": 6, "title": "向量数据库进阶", "status": "unlocked",
         "summary": "还没学。",
         "knowledge_tags": ["HNSW 索引", "混合检索", "重排序"]},
        {"id": 7, "order_index": 7, "title": "部署与观测", "status": "locked",
         "summary": "还没学。",
         "knowledge_tags": ["容器化部署", "日志埋点"]},
    ],
}

LEARNER_A_MASTERY = [
    {"knowledge_tag": "消息角色", "total_attempts": 8, "accuracy": 0.88},
    {"knowledge_tag": "数据格式解析", "total_attempts": 0, "accuracy": None},
    {"knowledge_tag": "结构化输出", "total_attempts": 6, "accuracy": 0.45},
    {"knowledge_tag": "函数调用", "total_attempts": 5, "accuracy": 0.72},
    {"knowledge_tag": "角色分工", "total_attempts": 4, "accuracy": 0.80},
    {"knowledge_tag": "向量检索", "total_attempts": 3, "accuracy": 0.67},
]

# ── 第二个学习者：**换领域、换目标、换掌握度** ──
#
# 为什么要两个：这套东西的全部卖点是"根据你学过哪些节点给你出题"。只跑一个学习者，
# 看不出它到底跟不跟节点走 —— 题目可能换成谁都一样（路径那边已经实测过一次：
# 4 条路径里 3 条是同一份内容）。所以这里第二个人的节点、领域、目标全都不同：
#
#   · 领域：数据结构与算法（不是智能体开发）；
#   · 目标：比赛 —— 走的是另一个 `TASK_TEMPLATE`（竞赛那套措辞）；
#   · 掌握度全线偏高（>=0.8）—— 服务端会把它判成 project 优先，和 A 的 case 优先不同；
#   · 没学的节点是「图论」那两个 —— 出题时同样一个都碰不得。
LEARNER_B_PROFILE = {
    "identity": "在职转岗",
    "major": "信息管理",
    "grade": "",
    "goal": "比赛",
    "direction": "数据结构与算法",
}

LEARNER_B_PATH = {
    "path_id": 90002,
    "goal": "数据结构与算法",
    "stage": "基础学习",
    "current_node_id": 7,
    "diagnosis": {"weak_points": []},
    "nodes": [
        {"id": 1, "order_index": 1, "title": "数组与链表", "status": "completed",
         "summary": "连续内存和链式存储各自贵在哪。",
         "knowledge_tags": ["下标访问", "插入删除代价"]},
        {"id": 2, "order_index": 2, "title": "栈与队列", "status": "completed",
         "summary": "两种受限的线性表，各自适合什么场景。",
         "knowledge_tags": ["后进先出", "先进先出"]},
        {"id": 3, "order_index": 3, "title": "哈希表", "status": "completed",
         "summary": "用散列把查找降到常数级，以及冲突了怎么办。",
         "knowledge_tags": ["散列函数", "冲突处理"]},
        {"id": 4, "order_index": 4, "title": "二叉树与遍历", "status": "completed",
         "summary": "树上的三种深度优先遍历和一层层走的广度优先。",
         "knowledge_tags": ["递归遍历", "层序遍历"]},
        {"id": 5, "order_index": 5, "title": "排序算法", "status": "completed",
         "summary": "几种排序的取舍：稳定性、额外空间、最坏情况。",
         "knowledge_tags": ["时间复杂度分析", "稳定性"]},
        {"id": 6, "order_index": 6, "title": "递归与分治", "status": "completed",
         "summary": "把大问题拆成同型的小问题，再合并结果。",
         "knowledge_tags": ["递归边界", "分治合并"]},
        {"id": 7, "order_index": 7, "title": "图的表示与遍历", "status": "unlocked",
         "summary": "还没学。",
         "knowledge_tags": ["邻接表", "深度优先搜索", "广度优先搜索"]},
        {"id": 8, "order_index": 8, "title": "最短路径", "status": "locked",
         "summary": "还没学。",
         "knowledge_tags": ["Dijkstra 算法", "松弛操作"]},
    ],
}

LEARNER_B_MASTERY = [
    {"knowledge_tag": "下标访问", "total_attempts": 5, "accuracy": 0.90},
    {"knowledge_tag": "插入删除代价", "total_attempts": 4, "accuracy": 0.83},
    {"knowledge_tag": "散列函数", "total_attempts": 6, "accuracy": 0.85},
    {"knowledge_tag": "递归遍历", "total_attempts": 5, "accuracy": 0.80},
    {"knowledge_tag": "时间复杂度分析", "total_attempts": 7, "accuracy": 0.86},
    {"knowledge_tag": "分治合并", "total_attempts": 3, "accuracy": 0.81},
]

LEARNERS = {
    "agent-dev": {"profile": LEARNER_A_PROFILE, "path": LEARNER_A_PATH, "mastery": LEARNER_A_MASTERY,
                  "label": "A · 在校生／就业／智能体开发"},
    "algo": {"profile": LEARNER_B_PROFILE, "path": LEARNER_B_PATH, "mastery": LEARNER_B_MASTERY,
             "label": "B · 转岗／比赛／数据结构与算法"},
}
# **默认两个都跑。** 只跑一个人时，"题目跟着节点走"和"题目对谁都一样"分不出来 ——
# 落盘过两份报告全是学习者 A，正是这个缺陷的样子。只想跑一个用 `--learner agent-dev`。
DEFAULT_LEARNERS = "all"


def learner_tags(path: dict) -> tuple[list[str], list[str]]:
    """从固定世界里**算**出"学过哪些标签 / 没学过哪些"，不手抄一份。

    手抄的那份一定会和 fixture 漂移，而漂移的方向恰好是往宽了判（少列一个未学标签，
    就等于放它一马）。
    """
    learned: list[str] = []
    not_learned: list[str] = []
    for node in path.get("nodes") or []:
        target = learned if node.get("status") == "completed" else not_learned
        for tag in node.get("knowledge_tags") or []:
            if tag not in target:
                target.append(tag)
    return learned, not_learned

# 学过 / 没学过的标签不再写在这里，而是由 `learner_tags(path)` 从固定世界算出来 ——
# 那是判据 2 和 5 的依据，它必须跟着 fixture 走。

# ═══════════════════════════════════════
#  判据（纯函数，`test_task_eval_metrics.py` 直接测它们）
# ═══════════════════════════════════════

EXPECTED_KINDS = {"case", "transfer", "project"}

# 判据分组 —— 见文件开头"机械不等于有区分度"那段。分组是这份报告最重要的一件事：
# 契约符合性那六条的答案是"模型抄没抄提示词里那张清单"，混进真判据里打分就是虚报。
GROUP_QUALITY = "quality"
GROUP_CONTRACT = "contract"
GROUP_INFO = "info"
# 模型没产出的那一轮（`source=fallback/timeout`）。它**一条判据都不跑** —— 见
# `has_model_output`。落盘那次 A 第 2 轮（兜底，120 秒超时）就是因为照跑了判据，
# 往真判据表里塞了两条假失败。
GROUP_SKIPPED = "skipped"

GROUP_LABELS = {
    GROUP_QUALITY: "真判据（会挂的）",
    GROUP_CONTRACT: "契约符合性（预期恒过 —— 挂了说明模型没照提示词输出，不说明质量）",
    GROUP_INFO: "信息项（不计分）",
    GROUP_SKIPPED: "没有模型产出（不计分）",
}


def verdict(name: str, ok: bool, detail: str, group: str = GROUP_QUALITY) -> dict:
    """一条判据。`group` 决定它进报告哪一张表 —— 收在一个函数里加，就不会漏。"""
    return {"name": name, "ok": ok, "detail": detail, "group": group}

# 要求 13 的字数上限。标题 42、单条描述 140 是提示词明写的；deliverables / criteria 的
# 100 字来自**代码里的**上限（`_clean_list(..., limit=100)` 会硬截），超了会被截断而不是报错。
LIMIT_TITLE = 42
LIMIT_DESC = 140
LIMIT_LIST_ITEM = 100

# 要求 5 的"3 个标签"。**它是提示词里的数，不是评估自定的**（yaml 要求 5 原文：
# "至少串起已完成节点中的 3 个知识标签"）。两个学习者的已学标签都是 12 个，所以这个门槛
# 只要求覆盖 25% —— 确实低，但要抬它得**先改提示词**，评估自己抬就成了另一把尺子。
COVERAGE_MIN_TAGS = 3

# 要求 14 点名的咨询黑话。「方案」带限定条件（当名词兜底用时）机械判不了，不收。
BANNED_BIZ_WORDS = (
    "赋能", "抓手", "闭环", "拉通", "可交付应用", "可验证交付", "矩阵", "端到端",
    "可用与可控", "可复现", "可复核", "评判流程", "复核证据", "架构设计文档",
    "通信协议定义",
)

# 要求 10 的产品话术。**刻意不包含「AI」「智能体」这两个名词** —— 见文件开头那段说明。
PRODUCT_SPEAK_PATTERNS = (
    "系统会根据你", "系统会为你", "系统自动为你", "为你推荐", "个性化推荐",
    "根据你的情况", "根据你的学习记录", "自动为你生成", "AI 会根据你", "AI 为你",
)

# 要求 11：summary 不宣称推荐项。只在这句话里出现才算违规。
RECOMMEND_CLAIM_WORDS = ("优先推荐", "优先选择", "建议先做", "推荐你", "首选")

# 判官温度。和 `claim_audit.py` 同一个值、同一个理由：它的活是机械匹配，不是创作。
JUDGE_TEMPERATURE = 0.0

# 标签覆盖**不能靠逐字匹配**。实测第 1 轮原文里 project 写的是「切块检索 / 角色接力 /
# 固定输出结构」，而标签原文是「文本切块 / 角色分工 / 结构化输出」—— 逐字匹配数出 2 个，
# 判了不合格，实际上它串了 4 个。判据误报比漏报更坏：它会让人去改一份没坏的东西。
# 所以覆盖判定交给判官（温度 0），它的活只是"这段话里用到了清单上的哪几个词"。
# 机械匹配留着当复核，两者不一致时**两个数都打出来**给人看。
_TAG_JUDGE_PROMPT = """\
你要做的是**机械匹配**，不是评价。

下面给你两批词条和三个任务描述。请做两件事 —— **这两件事的宽严标准是相反的，
不要用同一个尺度**：


### 第一件：覆盖 —— 每个描述**实际用到**了哪些"已完成"词条
**宁缺勿滥。** "用到"指的是意思上确实在讲这件事，**不要求原词出现**（描述里写"切块检索"就对应词条"文本切块"，写"角色接力"就对应"角色分工"）。只是顺带提一句、
或者看不出在讲这件事的，**不要算** —— 误报的代价是让人去改一份没坏的任务，比漏报更坏。

### 第二件：越界 —— 每个描述碰到了哪些"尚未完成"词条
**宁可多报。** 这一件的代价是不对称的：漏掉一个 = 一道题在考学生还没学过的东西，而这类
泄漏大多是**改述**的（不写"HNSW 索引"，整道题却在考近似最近邻），逐字匹配一个都抓不到。
所以只要描述**围绕、要求或者暗示**了某个没学过的词条，就算命中；拿不准的**算命中**，
并在 reason 里写清拿不准在哪。

## 已完成（学过）的词条
{learned}

## 尚未完成（没学过）的词条
{not_learned}

## 三个任务描述
{tasks}

只输出 JSON，不要解释文字：
{{
  "learned_used": {{"case": ["词条原文", ...], "transfer": [...], "project": [...]}},
  "not_learned_hit": {{"case": [...], "transfer": [...], "project": [...]}},
  "reason": "一句话说明判断依据；越界那件里拿不准的，在这里写清楚"
}}

两边的每一项都必须是上面清单里的**原文照抄**，不要改写、不要新增清单外的词。
没有就给空数组。"""


def task_text(task: dict, fields: tuple[str, ...] = ("title", "brief", "scenario", "problem", "why")) -> str:
    """一个任务的**学生看得到的那段字**：判越界、黑话、编造都用它。

    **`focus` 刻意不收。** 它的正文由服务端决定 —— `_normalise_agent_tasks` 里
    `item["focus"] = fallback["context"]["focus"]` 是无条件覆盖，模型写的那份**不发给学生**。
    把它扫进来等于判一段被丢弃的文字：既抓不到真实的越界（那条始终是服务端的、来自已完成
    节点的标签），又会凭空多出误判。
    """
    parts = [str(task.get(field) or "") for field in fields]
    for field in ("deliverables", "criteria", "constraints"):
        value = task.get(field)
        if isinstance(value, list):
            parts.extend(
                str(item.get("label") if isinstance(item, dict) else item)
                for item in value
            )
    return "\n".join(parts)


def _student_visible_texts(payload: dict) -> list[tuple[str, str]]:
    """学生看得到的每一段字 + 一个能写进结论的出处。

    `summary` 必须在这里 —— 它显示在任务条下面，模型也确实在写它，而原来的越界判据
    只扫任务的五个字段，**从 summary 泄漏的未完成节点标签一条判据都抓不到**。
    （`focus` 不进来，理由见 `task_text`。）
    """
    texts = []
    for item in (payload.get("tasks") or []):
        if not isinstance(item, dict):
            continue
        texts.append((str(item.get("kind") or "task"), task_text(item)))
    summary = str(payload.get("summary") or "") if isinstance(payload, dict) else ""
    if summary.strip():
        texts.append(("summary", summary))
    return texts


def check_structure(payload: dict) -> list[dict]:
    """要求 1：三个任务，kind 必须是 case / transfer / project 各一个。"""
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        return [verdict("结构完整", False, "没有 tasks 数组", GROUP_CONTRACT)]
    kinds = [item.get("kind") for item in tasks if isinstance(item, dict)]
    problems = []
    if len(tasks) != 3:
        problems.append(f"任务数 {len(tasks)} 个，要求 3 个")
    if set(kinds) != EXPECTED_KINDS:
        problems.append(f"kind 是 {kinds}，要求 case/transfer/project 各一个")
    return [verdict("结构完整", not problems, "；".join(problems) or "三个任务、kind 正确",
                    GROUP_CONTRACT)]


def check_fields(payload: dict) -> list[dict]:
    """要求 7：每个任务的十个字段都要有。空的会被兜底顶上（见 `check_substitution`）。

    `focus` 也在名单里，但它空不空**对学生没有影响** —— 服务端一律用自己那份覆盖
    （见 `task_text` 的说明）。要求它非空是在判"模型有没有照契约输出"，不是在判质量。
    """
    tasks = payload.get("tasks") if isinstance(payload, dict) else []
    missing = []
    for item in tasks if isinstance(tasks, list) else []:
        if not isinstance(item, dict):
            continue
        for field in ("kind", "title", "brief", "scenario", "problem", "why",
                      "focus", "deliverables", "criteria", "constraints"):
            value = item.get(field)
            if value is None or (isinstance(value, str) and not value.strip()) or (
                isinstance(value, list) and not value
            ):
                missing.append(f"{item.get('kind')}.{field}")
    return [verdict("字段齐全", not missing,
                    "缺：" + "、".join(missing) if missing else "十个字段都在", GROUP_CONTRACT)]


def _exact_leak(payload: dict, not_learned_tags: list[str]) -> list[str]:
    hits = []
    for where, text in _student_visible_texts(payload):
        for tag in not_learned_tags:
            if tag in text:
                hits.append(f"{where} 里出现了「{tag}」")
    return hits


def _exact_coverage(payload: dict, learned_tags: list[str]) -> list[str]:
    project = next((i for i in (payload.get("tasks") or [])
                    if isinstance(i, dict) and i.get("kind") == "project"), None)
    return [tag for tag in learned_tags if tag in task_text(project or {})]


def check_not_learned_leak(payload: dict, tag_verdict: dict | None,
                           not_learned_tags: list[str]) -> list[dict]:
    """要求 2：不要围绕尚未完成的节点出题。

    判官认改述；判官报错时退回逐字匹配，并在结论里**写明这是退回来的** ——
    退回来的那次只抓得到原词，改述一律放行，所以这个标记必须显眼。
    """
    exact = _exact_leak(payload, not_learned_tags)
    judged = (tag_verdict or {}).get("not_learned_hit")
    if judged is None:
        return [verdict("没考没学过的", not exact,
                        "（判官没给出结论，退回逐字匹配）"
                        + ("；".join(exact) if exact else "未完成节点的标签一个都没出现"))]
    hits = [f"{kind} 里用到了「{tag}」" for kind, tags in judged.items() for tag in (tags or [])]
    detail = "；".join(hits) if hits else "未完成节点的标签一个都没用到"
    if hits and not exact:
        detail += "（逐字匹配一个都没命中 —— 这是改述，不是原词）"
    return [verdict("没考没学过的", not hits, detail)]


def check_project_coverage(payload: dict, tag_verdict: dict | None,
                           learned_tags: list[str]) -> list[dict]:
    """要求 5：project 至少要串起 3 个已完成节点的知识标签。

    **那个 3 是提示词自己写的**（yaml 要求 5：`至少串起已完成节点中的 3 个知识标签`），
    不是评估自定的门槛 —— 两个学习者的已学标签都是 12 个，3 个 = 25%。要抬它得先改提示词，
    评估自己抬等于换一把尺子量同一份输出。

    同上：覆盖判定以判官为准（它认改述），逐字匹配的数字一并打出来 —— 两者不一致时
    读者要能一眼看出差在哪，而不是只拿到一个会误报的数。
    """
    project = next((i for i in (payload.get("tasks") or [])
                    if isinstance(i, dict) and i.get("kind") == "project"), None)
    if project is None:
        return [verdict("project 跨节点", False, "没有 project 任务")]
    exact = _exact_coverage(payload, learned_tags)
    judged = (tag_verdict or {}).get("learned_used")
    if judged is None:
        return [verdict("project 跨节点", len(exact) >= COVERAGE_MIN_TAGS,
                        f"（判官没给出结论，退回逐字匹配）覆盖了 {len(exact)} 个：{'、'.join(exact) or '（一个都没有）'}")]
    covered = [tag for tag in (judged.get("project") or []) if tag in learned_tags]
    detail = f"覆盖了 {len(covered)} 个已完成标签：{'、'.join(covered) or '（一个都没有）'}"
    if len(covered) != len(exact):
        detail += f"（逐字匹配只数出 {len(exact)} 个：{'、'.join(exact) or '无'}）"
    return [verdict("project 跨节点", len(covered) >= COVERAGE_MIN_TAGS, detail)]


def check_banned_words(payload: dict) -> list[dict]:
    """要求 14：说人话。禁词逐条列出原句，方便抽检是不是误伤。

    这一条覆盖**所有学生会读到的文字**，所以除了任务的五个字段和三个列表，还包括
    `summary` —— 要求 14 的禁词是**无范围限定**的（"别用这些词"），而 summary 显示在
    任务条下面。
    """
    hits = []
    for item in (payload.get("tasks") or []):
        if not isinstance(item, dict):
            continue
        for field in ("title", "brief", "scenario", "problem", "why"):
            text = str(item.get(field) or "")
            for word in BANNED_BIZ_WORDS:
                if word in text:
                    hits.append(f"{item.get('kind')}.{field} 命中「{word}」：{text[:60]}")
        for field in ("deliverables", "criteria", "constraints"):
            for entry in (item.get(field) or []):
                label = str(entry.get("label") if isinstance(entry, dict) else entry)
                for word in BANNED_BIZ_WORDS:
                    if word in label:
                        hits.append(f"{item.get('kind')}.{field} 命中「{word}」：{label[:60]}")
    summary = str(payload.get("summary") or "") if isinstance(payload, dict) else ""
    for word in BANNED_BIZ_WORDS:
        if word in summary:
            hits.append(f"summary 命中「{word}」：{summary[:60]}")
    return [verdict("没有咨询黑话", not hits, "；".join(hits) or "禁词一个都没命中",
                    GROUP_CONTRACT)]


def check_product_speak(payload: dict) -> list[dict]:
    """要求 10：别在产品里自称。只判"系统会为你…"这类句式，不判「智能体」这个名词。

    **刻意不扫 `summary`。** 要求 10 自己划了范围（"不要在标题、why 或 brief 中提及"），
    而 summary 另有要求 11 管着。扫了它就是在判提示词没要求的东西 —— 那种判据的挂与不挂
    都不说明模型有没有照契约办事。任务正文那五个字段已经是这个范围的超集（这是有意的，
    漏一个改写的说法比多扫一个字段更坏）。
    """
    hits = []
    for item in (payload.get("tasks") or []):
        if not isinstance(item, dict):
            continue
        for field in ("title", "brief", "scenario", "problem", "why"):
            text = str(item.get(field) or "")
            for pattern in PRODUCT_SPEAK_PATTERNS:
                if pattern in text:
                    hits.append(f"{item.get('kind')}.{field} 命中「{pattern}」：{text[:60]}")
    return [verdict("没有产品话术", not hits, "；".join(hits) or "没有自我中心的句式",
                    GROUP_CONTRACT)]


def check_summary_claim(payload: dict) -> list[dict]:
    """要求 11：summary 不许宣称推荐了哪一类 —— 推荐项由服务端按证据定。"""
    summary = str(payload.get("summary") or "") if isinstance(payload, dict) else ""
    hits = [word for word in RECOMMEND_CLAIM_WORDS if word in summary]
    return [verdict("summary 不宣称推荐", not hits,
                    f"命中 {hits}：{summary[:80]}" if hits else "没有宣称推荐项", GROUP_CONTRACT)]


def check_lengths(payload: dict) -> list[dict]:
    """要求 13（+ 代码里的列表项上限）：超长会被静默截断，所以按**原始输出**判。

    不含 `focus`：它不是被截断，是被服务端整份换掉（见 `task_text`），所以它的长度
    到不了学生眼前，判它只是在制造噪音。
    """
    over = []
    for item in (payload.get("tasks") or []):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        title = str(item.get("title") or "")
        if len(title) > LIMIT_TITLE:
            over.append(f"{kind}.title {len(title)} 字 > {LIMIT_TITLE}")
        for field in ("brief", "scenario", "problem", "why"):
            text = str(item.get(field) or "")
            if len(text) > LIMIT_DESC:
                over.append(f"{kind}.{field} {len(text)} 字 > {LIMIT_DESC}")
        for field in ("deliverables", "criteria", "constraints"):
            for entry in (item.get(field) or []):
                label = str(entry.get("label") if isinstance(entry, dict) else entry)
                if len(label) > LIMIT_LIST_ITEM:
                    over.append(f"{kind}.{field} 某条 {len(label)} 字 > {LIMIT_LIST_ITEM}")
    summary = str(payload.get("summary") or "") if isinstance(payload, dict) else ""
    if len(summary) > 100:
        over.append(f"summary {len(summary)} 字 > 100")
    return [verdict("没有超长字段", not over, "；".join(over) or "都在上限内", GROUP_CONTRACT)]


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_SCALE = 4


def _number_tokens(text: str) -> list[str]:
    """**看起来像事实的**数字 token（原样返回，写进结论用）：带小数点，或者三位以上。

    这一条是按真实产出定的，不是拍脑袋。把落盘那三轮的输出全抽出来分类，得到 13 个数字：

    - **12 个是输入数据**（0.67 / 67% / 0.45 / 0.45% 这些掌握度，模型两种写法都写过）；
    - **1 个**是「不超过 10 句话」—— 模型给自己出的题设的设计参数；
    - **0 个**是版本号 / 数据集规模 / 带小数的指标 —— 也就是要求 12 真正要防的那一类。

    所以两位整数不收：它们几乎全是设计参数（"分 3 组""10 句话""两天"），收了只会制造噪音，
    而"编造"要防的是 1.13.4 这种版本号、131072 这种规模数。**这一刀是有代价的**：模型真写一句
    编出来的"召回率 92%"，这条判据抓不到 —— 两位整数不在靶心里。这个盲区记在这里，
    别以后当成"这条判据很灵"。
    """
    out = []
    for match in _NUMBER_RE.finditer(str(text or "")):
        token = match.group(0)
        if "." in token or len(token) >= 3:
            out.append(token)
    return out


def _number_forms(token: str) -> set[float]:
    """同一个数的几种写法：比例、百分数、以及反过来。`0.67 ≡ 67 ≡ 6700 ≡ 0.0067`。

    归一化是这条判据的关键，两个坑都在这里解决：

    1. **`0.67` 和 `67%` 是同一个数。** 原来按 token 比字符串，模型把掌握度 0.67 如实
       写成"67%"就被判成编造 —— 落盘那次 3 轮里挂掉的那 2 轮，**全部**是因为这一个换算
       （0.67 / 0.45 两个数）。判据误报比漏报更坏：它会让人去改一份没坏的东西。
    2. 宁可宽一点。这条本来就只是"可能编造，供人抽检"，不是定罪。
    """
    value = round(float(token), _NUMBER_SCALE)
    return {value, round(value * 100, _NUMBER_SCALE), round(value / 100, _NUMBER_SCALE)}


def _number_values(text: str) -> set[float]:
    """一段文字里出现过的所有数值（已归一）。"""
    values: set[float] = set()
    for token in _number_tokens(text):
        values |= _number_forms(token)
    return values


def check_fabricated_numbers(payload: dict, context: dict) -> list[dict]:
    """要求 12：不要编造输入里没有的版本号 / 数值。

    判据是"这个**像事实的**数在输入上下文里找不到"。找不到**不等于**编造（可能是一个
    自洽的例子），所以这条只列出原句供人抽检，报告里标成"可能编造"。

    **允许集只取数据上下文，不取提示词。** 提示词里的数字全部是规则本身：
    10/11/12/13/14 是规则编号、42/140/100 是字数上限、60/80 是推荐门槛。原来
    `_numbers(prompt) | _numbers(context)` 这个允许集里 17 个 token 有 10 个来自规则文本，
    只有 7 个是真的输入数据 —— 于是"掌握度 60% 可推荐 transfer"这种照着规则写的句子
    永远判不出来。

    **靶心也收窄了**：只判带小数点或三位以上的数（版本号、数据规模、带小数的指标），
    两位整数不判。理由和代价都写在 `_number_tokens` 上面，那一刀是拿真实产出定的。

    诚实记一笔：**在落盘的全部轮次里，这条判据从来没有命中过一次真的编造** —— 它挂过两次，
    两次都是误报（`0.67` 写成 `67%`；「不超过 10 句话」）。别读成"这条很灵"。
    """
    allowed = _number_values(json.dumps(context, ensure_ascii=False))
    hits = []
    for where, text in _student_visible_texts(payload):
        for token in _number_tokens(text):
            if not (_number_forms(token) & allowed):
                hits.append(f"{where} 里的 {token}")
    hits = sorted(set(hits))
    return [verdict("没有编造数字", not hits, "；".join(hits) or "数字都能在输入里找到")]


def check_substitution(payload: dict, fallback_tasks: list[dict], normalised: list[dict]) -> list[dict]:
    """**兜底悄悄顶替**：字段与兜底一字不差 => 模型没写这一项，学生看到的是模板。

    比对用规范化之后的那一份（学生真正看到的），兜底用 `build_advanced_tasks` 那一份
    （服务端自己写的）。这不是判"不合格"，因为兜底本来就是为此准备的 —— 它判的是
    **对外报成功、实际有几个字段是模板**。所以它 `ok` 恒为 True、归在"信息项"一组，
    **不占判据表的一格**：一份 `ok` 写死的判据和真判据同列打分，等于虚报一格满分
    （模型整个崩掉、学生看到全是模板时，它也照样"3/3"）。

    **`focus` 不在比对范围里。** 它不是"被兜底顶替"，而是**永远**取服务端那份
    （`_normalise_agent_tasks` 里无条件覆盖，见 `task_text`），所以它每一轮都会跟兜底
    一字不差 —— 写进结论只会让人以为模型又漏了一个字段。模型对 focus 没有发言权这件事
    记在这里，不混进逐字段的账。
    """
    fallback_by_kind = {item.get("kind"): item for item in fallback_tasks}
    replaced = []
    for item in normalised or []:
        source = fallback_by_kind.get(item.get("kind")) or {}
        for field in ("title", "brief", "scenario", "problem", "why"):
            value = str(item.get(field) or "")
            if value and value == str(source.get(field) or ""):
                replaced.append(f"{item.get('kind')}.{field}")
        for field in ("deliverables", "criteria", "constraints"):
            got = [str(e.get("label") if isinstance(e, dict) else e) for e in (item.get(field) or [])]
            src = [str(e.get("label") if isinstance(e, dict) else e) for e in (source.get(field) or [])]
            if got and got == src:
                replaced.append(f"{item.get('kind')}.{field}")
    return [verdict("兜底顶替情况", True,
                    f"{len(replaced)} 处与兜底模板一字不差：{'、'.join(replaced)}" if replaced
                    else "没有一个字段等于兜底原文（说明这些字都是模型写的）", GROUP_INFO)]


def has_model_output(payload: dict) -> bool:
    """这一轮模型到底有没有产出。

    `source=fallback/timeout` 时 `payload` 是空 `{}`，`result["tasks"]` 是**兜底模板**。
    那时候照跑判据，判的就不是模型，而且会判出两条**假失败** —— 落盘那次 A 第 2 轮
    （120 秒超时）两条都齐了：

    - `没考没学过的` 拿到的是兜底任务，判官按"越界宁可多报"的口径在通用模板文字
      （"先查资料再回答""换个场景再用一次"）上编出了改述命中 —— 而那两个标签
      （混合检索/重排序）在兜底模板里**一次都没出现**。
    - `project 跨节点` 读的是空 payload，直接报"没有 project 任务"。

    两条都指向"提示词写得不好"，而真相是这一次**没有模型产出**。判据误报比漏报更坏：
    它会让人去改一份没坏的东西。
    """
    return bool((payload or {}).get("tasks"))


def judge_all(payload: dict, context: dict,
              fallback_tasks: list[dict], normalised: list[dict],
              tag_verdict: dict | None = None,
              learned_tags: list[str] = (), not_learned_tags: list[str] = (),
              source: str = "agent") -> list[dict]:
    """跑全部判据。`payload` 是模型的原始 JSON（判它写了什么），`normalised` 是学生看到的。

    没有模型产出时只回一行说明，**不跑任何真判据** —— 见 `has_model_output`。
    """
    verdicts = []
    if not has_model_output(payload):
        detail = "模型没有给出可解析的三个任务，这一轮不计入任何通过率"
        if source and source != "agent":
            detail = f"source={source}，" + detail
        verdicts.append(verdict("本轮没有模型产出", True, detail, GROUP_SKIPPED))
        return verdicts
    verdicts += check_structure(payload)
    verdicts += check_fields(payload)
    verdicts += check_not_learned_leak(payload, tag_verdict, list(not_learned_tags))
    verdicts += check_project_coverage(payload, tag_verdict, list(learned_tags))
    verdicts += check_banned_words(payload)
    verdicts += check_product_speak(payload)
    verdicts += check_summary_claim(payload)
    verdicts += check_lengths(payload)
    verdicts += check_fabricated_numbers(payload, context)
    verdicts += check_substitution(payload, fallback_tasks, normalised)
    return verdicts


def _is_transient_error(exc: Exception) -> bool:
    """上游抖动，值得原样重试一次；内容错（JSON 坏了）不算。

    和 `resource_graph.gen_one_sync` 里那份 token 表同义 —— 都是对着"连接被掐断 /
    读超时"这一类写的。`RemoteProtocolError` 正是落盘那次 B 第 1 轮判官的死因。
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in (
        "timeout", "timed out", "incomplete", "connecterror", "readerror", "remoteprotocolerror",
    ))


async def run_tag_judge(tasks: list[dict], learned_tags: list[str],
                        not_learned_tags: list[str]) -> dict:
    """判官：这三个任务用到了 / 碰到了清单上的哪些标签（认改述，不要求原词）。

    一个调用出两份结论，但**它们要按相反的口径判**：覆盖宁缺勿滥，越界宁可多报 ——
    见 `_TAG_JUDGE_PROMPT`。合成一个口径必然牺牲一头，而这两头的代价不对称：
    覆盖误报会让人去改一份没坏的任务，越界漏报会让学生做到没学的内容。

    **判官和被测是同一个模型**（`pool="eval"` 只是并发键），所以这里只让它做匹配、
    不让它做评价。

    **判官自己挂了就如实返回 error，不替它编结论** —— 上层会把这两条判据标成
    "判官没给出结论"（和 `claim_audit.py` 对判官报错的处置一致）。

    **传输层的临时错误重试一次**，理由是落盘那次真发生了：B 第 1 轮死在
    `RemoteProtocolError: peer closed connection without sending complete message body`，
    判官挂一次，两条标签判据就退回逐字匹配（改述一律放行），整轮的越界结论作废。
    重试**只认传输/超时**，不认内容错 —— JSON 坏了重试一次多半还是坏的，那是模型的事，
    该如实报出来而不是拿重试掩盖。token 表和 `resource_graph.gen_one_sync` 里那份同义
    （它也是对着同一类上游抖动写的）；不直接 import 它，是因为那要为一个六元组把
    langgraph 拖进评估进程。
    """
    import backend.src.ai_core.llm_config as llm_config
    from backend.src.utils.json_parser import parse_llm_json

    blocks = []
    for task in tasks or []:
        if isinstance(task, dict):
            blocks.append(f"### kind={task.get('kind')}\n{task_text(task, fields=('title', 'brief', 'scenario', 'problem', 'why'))}")
    prompt = _TAG_JUDGE_PROMPT.format(
        learned="、".join(learned_tags),
        not_learned="、".join(not_learned_tags),
        tasks="\n\n".join(blocks),
    )

    try:
        try:
            reply = await llm_config.llm.ainvoke(prompt, pool="eval", temperature=JUDGE_TEMPERATURE)
        except Exception as exc:
            if not _is_transient_error(exc):
                raise
            reply = await llm_config.llm.ainvoke(prompt, pool="eval", temperature=JUDGE_TEMPERATURE)
        parsed = parse_llm_json(str(getattr(reply, "content", "") or ""))
        if not isinstance(parsed, dict):
            raise ValueError("判官返回的不是对象")
        return {
            "learned_used": parsed.get("learned_used") or {},
            "not_learned_hit": parsed.get("not_learned_hit") or {},
            "reason": str(parsed.get("reason") or ""),
            "error": None,
            "prompt": prompt,
        }
    except Exception as exc:
        return {"learned_used": None, "not_learned_hit": None, "reason": "",
                "error": f"{type(exc).__name__}: {exc}", "prompt": prompt}


# ═══════════════════════════════════════
#  跑一次（走真链路）
# ═══════════════════════════════════════

class _LlmRecorder:
    """把真实 `llm.ainvoke` 包一层，**只观察、不改动**：留住模型吐出来的原文。

    判词要能对证。`generate_agent_task_set` 只返回规范化之后的三个任务，看不到模型
    原本写了什么 —— 而"它写了什么"正是这些判据要判的东西。所以这里记一份原文，
    调用本身照旧走生产那个对象。

    （同一个手法见 `coach_bridge._capture_stream_input`。）
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[str] = []

    async def ainvoke(self, *args, **kwargs):
        response = await self._inner.ainvoke(*args, **kwargs)
        self.calls.append(str(getattr(response, "content", "") or ""))
        return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def generate_once(learner_key: str, round_index: int) -> dict:
    """跑一轮：真实兜底 → 真实上下文 → 真实提示词 → 真模型 → 真规范化。"""
    import backend.src.ai_core.llm_config as llm_config
    from backend.src.service.advanced import service as advanced_service
    from backend.src.utils.json_parser import parse_llm_json

    learner = LEARNERS[learner_key]
    profile = json.loads(json.dumps(learner["profile"], ensure_ascii=False))
    path = json.loads(json.dumps(learner["path"], ensure_ascii=False))
    mastery = json.loads(json.dumps(learner["mastery"], ensure_ascii=False))
    learned_tags, not_learned_tags = learner_tags(path)

    fallback_tasks = advanced_service.build_advanced_tasks(profile, path, mastery)
    completed, total = advanced_service.completed_node_count(path)
    milestone = advanced_service.advanced_milestone(completed)
    context = advanced_service._agent_context(profile, path, mastery, milestone)
    prompt = advanced_service._build_agent_prompt(context)

    recorder = _LlmRecorder(llm_config.llm)
    original = llm_config.llm
    llm_config.llm = recorder
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            advanced_service.generate_agent_task_set(
                0, profile, path, mastery, milestone, fallback_tasks,
            ),
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = {"tasks": fallback_tasks, "summary": "", "source": "timeout",
                  "error": f"评估侧等了 {CALL_TIMEOUT_SECONDS} 秒没返回"}
    finally:
        llm_config.llm = original
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    raw_text = recorder.calls[-1] if recorder.calls else ""
    try:
        payload = parse_llm_json(raw_text) if raw_text else {}
        if not isinstance(payload, dict):
            payload = {}
        parse_error = ""
    except Exception as exc:  # 生产里同样会抛，然后降级兜底
        payload = {}
        parse_error = f"{type(exc).__name__}: {exc}"

    # 判官认改述（见 `_TAG_JUDGE_PROMPT` 上面那段），它的结论喂给两条标签判据。
    # **没有模型产出就不叫判官**：那一轮 `result["tasks"]` 是兜底模板，判它等于让判官在
    # 通用模板文字上按"宁可多报"编改述命中（落盘那次 A 第 2 轮就是这样），既出假结论
    # 又白花一次调用。
    if has_model_output(payload):
        tag_verdict = await run_tag_judge(result["tasks"], learned_tags, not_learned_tags)
    else:
        tag_verdict = None
    verdicts = judge_all(payload, context, fallback_tasks, result["tasks"],
                         tag_verdict, learned_tags, not_learned_tags,
                         source=str(result.get("source") or ""))

    return {
        "round": round_index,
        "learner": learner_key,
        "learner_label": learner["label"],
        "learned_tags": learned_tags,
        "not_learned_tags": not_learned_tags,
        "tag_verdict": tag_verdict,
        "elapsed_ms": elapsed_ms,
        "source": result.get("source"),
        "error": result.get("error"),
        "parse_error": parse_error,
        "completed_nodes": completed,
        "total_nodes": total,
        "milestone": milestone,
        "fallback_tasks": fallback_tasks,
        "tasks": result.get("tasks"),
        "summary": result.get("summary"),
        "raw_text": raw_text,
        "prompt": prompt,
        "context": context,
        "verdicts": verdicts,
    }


# ═══════════════════════════════════════
#  报告
# ═══════════════════════════════════════

def _mark(ok: bool) -> str:
    return "OK " if ok else "!! "


_GROUP_ORDER = tuple(GROUP_LABELS)


def _by_learner(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record.get("learner") or "?", []).append(record)
    return grouped


def _learner_labels(records: list[dict]) -> dict[str, str]:
    return {key: rows[0].get("learner_label") or key for key, rows in _by_learner(records).items()}


def summarise(records: list[dict]) -> dict:
    """`{学习者: {分组: {判据名: {passed, total, failures}}}}`。

    **分组是这份报告最重要的一件事。** 契约符合性那六条测的是"模型有没有照抄提示词里
    那张清单"，一个及格线的模型必然全过 —— 和真判据混在一张表里算总数，会把整体观感
    刷成"几乎满分"。分组的依据是每条 verdict 自带的 `group`，见文件开头那段。
    """
    summary: dict[str, dict] = {}
    for record in records:
        learner = summary.setdefault(record.get("learner") or "?", {})
        for item in record["verdicts"]:
            group = learner.setdefault(item.get("group") or GROUP_QUALITY, {})
            stats = group.setdefault(item["name"], {"passed": 0, "total": 0, "failures": []})
            stats["total"] += 1
            if item["ok"]:
                stats["passed"] += 1
            else:
                stats["failures"].append(item["detail"])
    return summary


def _verdict_table(lines: list[str], summary: dict, labels: dict[str, str], group: str) -> None:
    lines += ["| 学习者 | 判据 | 通过 | 说明 |", "|---|---|---|---|"]
    for learner_key, groups in summary.items():
        for name, stats in (groups.get(group) or {}).items():
            note = "" if stats["passed"] == stats["total"] else "；".join(stats["failures"])[:200]
            lines.append(f"| {labels.get(learner_key, learner_key)} | {name} "
                         f"| {stats['passed']}/{stats['total']} | {note} |")


_CN_NUMBERS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}


def _cn_number(value: int) -> str:
    return _CN_NUMBERS.get(value, str(value))


def _skipped_rows(summary: dict, labels: dict[str, str]) -> list[str]:
    """「没有模型产出」那一节的内容。空列表 = 这次没有跳过任何一轮，整节不印。"""
    rows: list[str] = []
    for learner_key, groups in summary.items():
        for name, stats in (groups.get(GROUP_SKIPPED) or {}).items():
            rows.append(f"- **{labels.get(learner_key, learner_key)}** {stats['total']} 轮 · {name}")
    return rows


def render_report(records: list[dict], summary: dict) -> str:
    learners = _by_learner(records)
    labels = _learner_labels(records)
    lines = ["# 进阶实践任务智能体 · 评估", ""]
    lines += [
        f"- 轮数：{len(learners)} 个学习者 × 每个 {len(next(iter(learners.values())))} 轮"
        f"（共 {len(records)} 轮）",
        "- 走的是：`build_advanced_tasks` → `generate_agent_task_set`（与后台作业同一对调用）",
        "- 学习者：",
    ]
    for key, rows in learners.items():
        lines.append(f"  - {labels.get(key, key)} —— 已完成 {rows[0]['completed_nodes']}"
                     f"/{rows[0]['total_nodes']} 个节点，里程碑 {rows[0]['milestone']}")
    lines += [
        "",
        "> **只看「真判据」那张表。** 契约符合性那六条测的是「模型有没有照着提示词里",
        "那张清单」输出 —— 预期恒过，挂了说明它没照契约，不说明质量。信息项不计分。",
        "理由见 `eval/task_eval.py` 开头。",
        ">",
        f"> 生成温度是 `llm_config._BASE_TEMPERATURE`（0.3）且无种子，所以 {len(records)} 轮",
        f"是 {len(records)} 次采样，通过率是观感，不是统计量。",
        "",
        f"## 一、{GROUP_LABELS[GROUP_QUALITY]}",
        "",
    ]
    _verdict_table(lines, summary, labels, GROUP_QUALITY)

    lines += ["", f"## 二、{GROUP_LABELS[GROUP_CONTRACT]}", ""]
    _verdict_table(lines, summary, labels, GROUP_CONTRACT)

    skipped = _skipped_rows(summary, labels)
    if skipped:
        lines += [
            "",
            f"## 三、{GROUP_LABELS[GROUP_SKIPPED]}",
            "",
            "> 这些轮次模型没有产出（`source=fallback/timeout`），学生看到的是兜底模板。",
            "> 它们**不进上面任何一张表** —— 判模板等于判一句固定文案，得出的失败会指向",
            "> 一份没坏的提示词。这一节只记「哪几轮没产出」。",
            "",
        ]
        lines += skipped
        offset = 1
    else:
        offset = 0

    lines += ["", f"## {_cn_number(3 + offset)}、{GROUP_LABELS[GROUP_INFO]}", ""]
    for learner_key, groups in summary.items():
        for name, stats in (groups.get(GROUP_INFO) or {}).items():
            for detail in ([f"{stats['passed']}/{stats['total']} 全过"] if stats["passed"] == stats["total"]
                           else stats["failures"]):
                lines.append(f"- **{labels.get(learner_key, learner_key)}** {name}：{detail}")

    lines += ["", f"## {_cn_number(4 + offset)}、每轮", ""]
    for learner_key, rows in learners.items():
        lines += [f"### {labels.get(learner_key, learner_key)}", ""]
        for record in rows:
            lines += [
                f"#### 第 {record['round']} 轮（{record['elapsed_ms']} ms，source={record['source']}）",
                "",
            ]
            if record["error"]:
                lines.append(f"- 失败原因：`{record['error']}`")
            if record["parse_error"]:
                lines.append(f"- 原始输出解析失败：`{record['parse_error']}`")
            for item in record["verdicts"]:
                lines.append(f"- {_mark(item['ok'])} [{item.get('group')}] **{item['name']}**：{item['detail']}")
            lines += ["", f"小结（summary）：{str(record.get('summary') or '')}", ""]
            for task in (record.get("tasks") or []):
                lines += [
                    f"**{task.get('kind')}** · {task.get('title')}",
                    "",
                    f"- brief：{task.get('brief')}",
                    f"- scenario：{task.get('scenario')}",
                    f"- problem：{task.get('problem')}",
                    f"- why：{task.get('why')}",
                    # focus 也打出来：它**由服务端决定、学生看得见**（TaskBar 的「重点能力」），
                    # 校对着看的时候缺了它，就没法判断"模型写的任务"和"学生看到的任务"差在哪。
                    f"- focus（服务端取的那份）：{task.get('focus')}",
                    f"- deliverables：{'；'.join(str(d.get('label')) for d in (task.get('deliverables') or []))}",
                    f"- criteria：{'；'.join(task.get('criteria') or [])}",
                    f"- constraints：{'；'.join(task.get('constraints') or [])}",
                    "",
                ]

    lines += ["## 五、模型原始输出（判词对证用）", ""]
    for learner_key, rows in learners.items():
        for record in rows:
            lines += [f"### {labels.get(learner_key, learner_key)} · 第 {record['round']} 轮",
                      "", "```json", record["raw_text"].strip() or "（空）", "```", ""]

    lines += ["## 六、送进去的提示词（判词对证用）", ""]
    for learner_key, rows in learners.items():
        for record in rows:
            lines += [f"### {labels.get(learner_key, learner_key)} · 第 {record['round']} 轮",
                      "", "```text", record["prompt"].strip(), "```", ""]
    return "\n".join(lines)


async def main_async(args) -> int:
    started = time.perf_counter()
    learner_keys = sorted(LEARNERS) if args.learner == "all" else [args.learner]
    records = []
    for learner_key in learner_keys:
        for index in range(1, args.rounds + 1):
            print(f"[{LEARNERS[learner_key]['label']}] 第 {index}/{args.rounds} 轮…", flush=True)
            record = await generate_once(learner_key, index)
            records.append(record)
            print(f"    完成 source={record['source']} 耗时={record['elapsed_ms']}ms", flush=True)
            if args.raw:
                continue
            for item in record["verdicts"]:
                print(f"    {_mark(item['ok'])} [{item.get('group')}] {item['name']}："
                      f"{item['detail'][:110]}", flush=True)

    if args.raw:
        for record in records:
            print(f"\n===== {record.get('learner_label')} · 第 {record['round']} 轮原始输出 =====")
            print(record["raw_text"])
        return 0

    summary = summarise(records)
    labels = _learner_labels(records)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"{stamp}-task-eval.json"
    md_path = RESULTS_DIR / f"{stamp}-task-eval.md"
    json_path.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_report(records, summary), encoding="utf-8")

    print("\n逐条判据通过率（按组；只看真判据那一组）：")
    for learner_key, groups in summary.items():
        print(f"  {labels.get(learner_key, learner_key)}")
        for group in _GROUP_ORDER:
            items = groups.get(group) or {}
            if not items:
                continue
            print(f"    ── {GROUP_LABELS[group]}")
            for name, stats in items.items():
                tail = ("" if stats["passed"] == stats["total"]
                        else f"   <- {'；'.join(stats['failures'])[:120]}")
                print(f"       {stats['passed']}/{stats['total']}  {name}{tail}")
    print(f"\n落盘：{md_path.relative_to(REPO_ROOT)}")
    print(f"      {json_path.relative_to(REPO_ROOT)}")
    print(f"总耗时 {int(time.perf_counter() - started)}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="进阶实践任务智能体评估")
    parser.add_argument("--rounds", type=int, default=ROUNDS, help="每个学习者跑几轮（默认 3）")
    parser.add_argument("--learner", default=DEFAULT_LEARNERS, choices=sorted(LEARNERS) + ["all"],
                        help="用哪个固定学习者（默认 all，两个都跑）")
    parser.add_argument("--raw", action="store_true", help="只打模型原文，不判分")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
