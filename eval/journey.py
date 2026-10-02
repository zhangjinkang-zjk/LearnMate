# -*- coding: utf-8 -*-
"""一次完整的入学流程：画像诊断 → 方向拆解 → 学习路径生成。

跑的是生产那条路，一段都不自己拼：

    diagnosis.service.start / answer              出题、判分、落库
    diagnosis.service._generate_paths_after_diagnosis
    curriculum.service.sync_direction_subjects    方向 → 科目
    PathService.generate_subject_paths            科目 → 路径（Leader 图）

只固定一样东西：**假学生的底子**（`STUDENT_PROFILE`）。其余全是生产实现。

## 为什么必须有一个"假学生"，而不是写死几句回答

诊断是**自适应**的 —— `prompts/diagnosis.yaml` 里写着「必须接住上一轮回答中的具体内容」
「回答正确且解释充分时提高场景复杂度；回答含糊时换一种更基础、更具体的问法」。
写死的答案接不住上一轮，问出来的会是一套没学生会遇到的对话，拿它审生成质量不作数。

## 这份记录用来**审质量**，不是回归门槛

假学生由同一个模型扮演，靠 `STUDENT_PROFILE` 把它压到"看过文档没写过"这个水平。
两处天生的短板，读的时候要记着：

- **它可能答得比真人好。** 模型本来就会 LangGraph，让它"装作没写过"，它仍可能漏出真本事
  —— 于是诊断看起来"问得挺准"，而真人初学者会在这儿卡住。所以这份记录看得出"生成得
  合不合理"，看不出"对真人准不准"。
- **每轮回答都是采样出来的**，同一天跑两次得到两套题。要可比的分数看 `persona_eval.py`。

## 产出

`eval/results/<时间戳>-journey.md`：诊断每一问（连服务端那份参考回答一起）、假学生的回答、
判分反馈、落库的画像、拆出来的科目、每条路径的每个节点。
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.models.exam_model import ExamQuestion, ExamRecord  # noqa: E402
from backend.src.models.path_model import LearningPath, PathNode  # noqa: E402
from backend.src.models.resource_model import GeneratedResource  # noqa: E402
from backend.src.service.diagnosis import service as diagnosis  # noqa: E402
from backend.src.utils.database import close_db, init_db  # noqa: E402
from eval import subject as subject_module  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"

# 这一程用的入学信息。改这里就等于换一个学生从头跑一遍。
IDENTITY = "在校大学生"
DIRECTION = "智能体开发"
GOAL = "能独立做出一个带工具调用的问答应用，并说清每个设计取舍"
MAX_STEPS = 3

# 假学生的底子。**这是整份评估唯一被固定的输入** —— 诊断问什么、路径生成什么，全看它。
STUDENT_PROFILE = """你在扮演一个正在学「智能体开发」的学生，底子是这样的：

- 会 Python，写过一些小脚本和课程作业，但没做过完整的工程项目。
- LangGraph、MCP、工具调用（function calling）这些，你**看过文档、看过教程视频，
  没亲手写过一个能跑起来的程序**。
- 你能说出这些概念大概是干什么的，也记得一些文档里的说法，但问到"具体怎么接、踩过什么坑、
  为什么这么选"你就答不上来，因为你没真做过。

回答导师提问时的规矩：
- 照这个底子答。真动手做过的事才说做过；只在文档里看过的，就说"看过文档，没实际写过"。
- 说具体一点（记得文档里哪种说法、卡在哪一步），但**不要装作比实际会得多**，
  也别故意装不会。
- 2 到 4 句，像平时说话。不要写条目，不要用"首先/其次/综上"。
"""


# ═══════════════════════════════════════
#  假学生
# ═══════════════════════════════════════

async def _student_answer(question: str, history: list[dict]) -> str:
    """让假学生回答这一问。

    把前几轮的原话一并给它 —— 诊断的下一问是接着上一轮答的，假学生要是忘了自己刚说过
    什么，就会答出前后矛盾的东西，而这种矛盾会被判分当成"理解不牢"记下来。
    """
    from backend.src.ai_core.llm_config import llm

    lines = [f"学习方向：{DIRECTION}", f"学习目标：{GOAL}", ""]
    if history:
        lines.append("你前面已经答过的：")
        for item in history:
            lines += [f"导师问：{item['content']}", f"你答：{item['answer']}", ""]
    lines += ["导师现在问你：", question, "", "用你自己的话回答（2 到 4 句）。"]

    reply = await llm.ainvoke(STUDENT_PROFILE + "\n\n" + "\n".join(lines), pool="eval")
    return str(getattr(reply, "content", reply) or "").strip()


# ═══════════════════════════════════════
#  把诊断收尾那条后台任务变成"可以等"
# ═══════════════════════════════════════

def _capture_background() -> list:
    """换掉 `_spawn_background`，把收尾的路径生成任务收进一个列表。

    生产里它是 fire-and-forget 的：诊断结果立刻返回给学生看，别让他干等十几分钟。
    评估这边必须反过来 —— 不等它，脚本会在路径还没落库的时候就退出，读出来一张空表，
    然后得出一句"没生成任何路径"的错误结论。
    """
    spawned: list = []
    diagnosis._spawn_background = spawned.append
    return spawned


# ═══════════════════════════════════════
#  跑完整一程
# ═══════════════════════════════════════

async def _question_detail(question_id: int) -> dict:
    """题目表里服务端那份 —— 参考回答和解析**不发给前端**，但审质量必须看到它们：
    判分判得对不对，只能拿学生答案和这份参考回答对着看。"""
    row = await ExamQuestion.filter(id=question_id).first()
    if row is None:
        return {}
    return {"reference_answer": row.answer, "analysis": row.analysis, "tags": _json(row.knowledge_tags)}


async def _diagnosis_turns(user_id: int) -> tuple[list[dict], dict | None]:
    session = await diagnosis.start(user_id, IDENTITY, DIRECTION, GOAL, MAX_STEPS)
    session_id = session["session_id"]
    question = session["question"]
    turns: list[dict] = []
    result = None

    for _ in range(MAX_STEPS):
        answer_text = await _student_answer(question["content"], turns)
        result = await diagnosis.answer(user_id, session_id, question["question_id"], answer_text)
        feedback = result.get("feedback") or {}
        turns.append({
            "content": question["content"],
            "difficulty": question.get("difficulty"),
            "tags": question.get("knowledge_tags") or [],
            "detail": await _question_detail(question["question_id"]),
            "answer": answer_text,
            "verdict": feedback.get("is_correct"),
            "score": feedback.get("score"),
            "feedback": result.get("reply"),
            "analysis": feedback.get("analysis"),
        })
        if result.get("finished"):
            break
        question = result["question"]
    return turns, (result or {}).get("result")


def _json(raw) -> list:
    try:
        parsed = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


async def _portrait(user_id: int) -> dict:
    from backend.src.models.usermodel import User
    from backend.src.service.portrait.service import parse_traits

    user = await User.filter(id=user_id).first()
    picture = await user.picture if user else None
    return parse_traits(picture.traits if picture else None)


async def _paths(user_id: int) -> list[dict]:
    out = []
    for path in await LearningPath.filter(user_id=user_id).order_by("id").all():
        nodes = await PathNode.filter(path_id=path.id).order_by("order_index").all()
        out.append({
            "subject": path.subject,
            "difficulty": path.difficulty,
            "node_count": path.node_count,
            "cover_tags": _json(path.cover_tags),
            "nodes": [{
                "order": node.order_index,
                "topic": node.topic,
                "tags": _json(node.knowledge_tags),
                "resource_types": _json(node.resource_types),
                "difficulty_score": node.difficulty_score,
                "prerequisites": _json(node.prerequisites),
                "has_teaching_spec": bool(node.teaching_spec),
            } for node in nodes],
        })
    return out


async def _resources(user_id: int) -> list[dict]:
    """第一节点被预热出来的资源（生产只为入口路径的第一章预生成）。"""
    rows = await GeneratedResource.filter(user_id=user_id).order_by("id").all()
    return [{
        "type": getattr(row, "resource_type", None) or getattr(row, "type", None),
        # 列名是 `topic` 不是 `title`（GeneratedResource 里没有 title）——
        # 读错列的报告会显示成一排 "None"，看的人只会以为资源没标题。
        "title": getattr(row, "topic", None),
        "passed": bool(getattr(row, "review_passed", False)),
        "chars": len(str(getattr(row, "content", "") or "")),
    } for row in rows]


async def run(stamp: str) -> dict:
    user = await subject_module.ensure_user()
    spawned = _capture_background()
    try:
        turns, result = await _diagnosis_turns(user.id)
        # 诊断答满时挂出去的那条路径生成任务（见 `_capture_background`）
        for coro in spawned:
            await coro
        exam_records = await ExamRecord.filter(user_id=user.id).count()
        artifact = {
            "identity": IDENTITY, "direction": DIRECTION, "goal": GOAL,
            "turns": turns, "result": result,
            "exam_records": exam_records,
            "portrait": await _portrait(user.id),
            "paths": await _paths(user.id),
            "resources": await _resources(user.id),
            "report": "",
        }
        # 落盘在下面那句清理**之前**（见 main 里那段注释）
        artifact["report"] = str(_write_report(artifact, stamp))
        return artifact
    finally:
        deleted = await subject_module.purge_by_id(user.id)
        print(f"[journey] 已清理合成学生的数据：{deleted}", file=sys.stderr)


# ═══════════════════════════════════════
#  写成一份能读的东西
# ═══════════════════════════════════════

def _render(artifact: dict) -> str:
    lines = [
        "# 入学一程：画像诊断 → 学习路径生成",
        "",
        f"- 身份：{artifact['identity']}",
        f"- 方向：{artifact['direction']}",
        f"- 目标：{artifact['goal']}",
        f"- 诊断落库的答题记录：{artifact['exam_records']} 条",
        "",
        "> 假学生的底子见 `eval/journey.py` 的 `STUDENT_PROFILE`：会 Python、",
        "> LangGraph 这些**看过文档没亲手写过**。回答由模型扮演，是采样出来的。",
        "",
        "## 一、诊断问答",
        "",
    ]
    for index, turn in enumerate(artifact["turns"], 1):
        detail = turn.get("detail") or {}
        lines += [
            f"### 第 {index} 问（难度 {turn.get('difficulty')}）",
            "",
            f"**导师问**：{turn['content']}",
            "",
            f"**假学生答**：{turn['answer']}",
            "",
            f"**判分**：{'答对' if turn['verdict'] else '答错'}"
            + (f"（{turn['score']}）" if turn.get("score") is not None else ""),
            "",
            f"**给学生的反馈**：{turn.get('feedback') or '（空）'}",
            "",
        ]
        if detail.get("reference_answer"):
            lines += ["<details><summary>服务端那份参考回答（不发给学生，审的时候对着看）</summary>", "",
                      f"- 参考回答：{detail['reference_answer']}",
                      f"- 解析：{detail.get('analysis') or '（无）'}",
                      f"- 知识点：{'、'.join(detail.get('tags') or []) or '（无）'}", "", "</details>", ""]

    result = artifact.get("result") or {}
    if result:
        lines += ["## 二、诊断结论", "",
                  f"- 正确率：{result.get('percentage')}",
                  f"- 结论语：{result.get('message')}", ""]

    portrait = artifact.get("portrait") or {}
    onboarding = portrait.get("onboarding") or {}
    lines += ["## 三、落库的画像", "", "```json",
              json.dumps({"onboarding": onboarding,
                          "learning_direction": portrait.get("learning_direction"),
                          "learning_direction_goal": portrait.get("learning_direction_goal"),
                          "learning_direction_subjects": portrait.get("learning_direction_subjects")},
                         ensure_ascii=False, indent=2), "```", ""]

    lines += ["## 四、生成的路径", ""]
    if not artifact["paths"]:
        lines += ["**一条都没有。** 生成失败了，去看后端日志里的「诊断后学习路径生成失败」。", ""]
    for path in artifact["paths"]:
        lines += [f"### {path['subject']}（难度 {path['difficulty']}，{path['node_count']} 个节点）", ""]
        if path["cover_tags"]:
            lines += [f"标签：{'、'.join(path['cover_tags'])}", ""]
        for node in path["nodes"]:
            spec = "，含教学规格" if node["has_teaching_spec"] else ""
            score = f"，难度系数 {node['difficulty_score']}" if node["difficulty_score"] is not None else ""
            lines += [f"{node['order']}. **{node['topic']}**{spec}{score}",
                      f"   - 知识点：{'、'.join(node['tags']) or '（无）'}",
                      f"   - 资源：{'、'.join(node['resource_types']) or '（无）'}", ""]

    lines += ["## 五、第一节点预生成的资源", ""]
    if not artifact["resources"]:
        lines += ["（没有）", ""]
    for item in artifact["resources"]:
        # 审核结果一起报：**没通过审核的资源也是给学生的资源**（走的是安全兜底版本），
        # 只报类型和字数会把"这份是兜底凑出来的"藏掉。
        verdict = "审核通过" if item.get("passed") else "**未通过审核（兜底版本）**"
        lines += [f"- `{item['type']}`「{item['title']}」（{item['chars']} 字符）—— {verdict}"]
    return "\n".join(lines) + "\n"


def _write_report(artifact: dict, stamp: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{stamp}-journey.md"
    out.write_text(_render(artifact), encoding="utf-8")
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    # 应用那层的 logger 没配 handler，只剩 lastResort 的 WARNING 能到 stderr ——
    # 于是"某一组只生成了 2/4 个节点""PPT 审核第 3 轮过了没有"这类 INFO 全丢了，
    # 而审生成质量恰恰要看这些。一轮 25 分钟、模型调用要花钱，证据必须留全。
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # **报告先落盘、再清理**（`run` 里那个 finally 负责清理）。反过来写过一次：
    # 2026-10-02 那轮走到清理之后卡在 close_db 上四分钟，报告还没写 —— 数据已经删了，
    # 整轮的生成结果只剩内存里那一份，进程要是死在那儿就全丢了。
    stamp = time.strftime("%Y%m%d-%H%M%S")

    async def _drive():
        await init_db()
        try:
            return await run(stamp)
        finally:
            await close_db()

    artifact = asyncio.run(_drive())
    print(f"写好了：{artifact['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
