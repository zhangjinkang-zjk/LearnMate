# -*- coding: utf-8 -*-
"""学习资料生成那几条链的评估：**产出齐不齐、审核跑没跑、协同过程长什么样。**

## 走的是生产那条路

直接迭代那张图，一行不自己拼：

    resource_graph.astream(state, stream_mode=["values", "custom"])
    state 由 service/resource/generation_context.make_generation_state(...) 造

这和 `ResourceService.generate_stream`（service.py:328）与 `_run_generation_task`
（service.py:625）**内部调的是同一个东西**。**不能用 `ainvoke`** —— 那样 `get_stream_writer()`
拿不到写入器，`safe_stream_writer()` 返回 `None`，事件被**静默丢弃**（`streaming.py:96-100`）：
协同过程全没了，而且不报任何错。这是本文件第一个坑，写在这里免得后人图省事改回去。

## 三个会让人测歪的坑（每个都已经在代码里对上过）

1. **缓存复用**。`generate_and_save` 按 `(user_id, topic, resource_type)` 复用旧资源
   （`service.py:154-178`）。所以每种类型只测一次、或者跨轮复用同一份，跑出来的"N 份"
   其实是一份。这里的对策是**不用那个入口**，直接迭代图（它没有资源级缓存），并且
   **记下每个正文的哈希**，重复了要看得见。
   注意 `LLM_CACHE_TTL`（默认 0=不缓存）可能被 `.env` 打开，那是**逐字相同**的复现，
   哈希一样时报告里要分得清是"缓存"还是"模型稳定"—— 所以哈希之外还记落库时间与事件数。

2. **兜底骨架会假装成功**。小节生成尽覆时用 `_fallback_document_section` /
   `_fallback_ppt_section`，正文是骨架，**事件照样发 `done`**；整个类型失败则直接跳过该类型
   （`gen_one_sync` 返回 `""`），`generate_and_save` 也不抛异常。所以判据不能只看
   "有没有报错"，必须看**请求的类型齐不齐**和**正文是不是骨架**。

3. **章节级审核结论没有持久化**。PPT 的逐章审核、文档的规则式质检、跨章节交叉验证，
   结果**只进 SSE 事件和日志，不进 DB**；而 `GeneratedResource.review_passed` 对
   ppt/document/case/reading **一律是 True**（`resource_graph.reviewer_node` 跳过全局审核）。
   所以"审核到底跑没跑"只能从**事件**和**日志**里数 —— 这正是本文件把事件全收下来的原因。

## 产出

`eval/results/<时间戳>-resource-eval.md`（人读）＋ `<时间戳>-resource-eval.json`（机器读，
含每份资源的**完整正文**与**全部事件**）。判定那一步（内容真不真）在 `claim_audit.py`，
它读这份 json —— 生成要花钱，判定得能反复重跑。
"""
import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.utils.database import close_db, init_db  # noqa: E402
from eval import subject as subject_module  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"

# `resource_graph` 那一条导入链要 6 秒多（LangGraph + 全部提示词）。**只在真正要跑图的时候
# 才导入**，好让 `backend/tests/test_resource_eval_metrics.py` 能便宜地测这里的纯函数 ——
# 那些函数算出来的数就是要写进文档的数，它们必须被测到。

# 固定的主题。**选这个是因为它的断言可以机械核验**（Python 语义能跑出来对错），
# 而不是因为它好写 —— 详见 `eval/reference/` 与 `claim_audit.py`。
FIXED_TOPIC = "Python 函数的参数传递与常见陷阱"

# 节点资源里**实际会出现**的类型是这几种（`teaching_context.PATH_DEFAULT_RESOURCE_TYPES`
# 是 document/ppt/mindmap；path 提示词主推 document+mindmap，ppt 视输出而定）。
# `exercise` 走的是另一条链（测验），不在这里测 —— 这是覆盖缺口，报告里要写出来。
RESOURCE_TYPES = ("document", "ppt", "mindmap")

# 每种类型跑几轮。生成是采样出来的，一轮看不出稳定性；但每一轮都是真金白银，
# 所以默认 2 轮：够看出"同一主题两次是不是同一份"，不够就别装够了。
ROUNDS = 2

# 兜底骨架的识别字样。**抄的是生成侧那两个 `_fallback_*` 的产物特征**：
# 骨架的特点是"有结构没结论"，所以认这些占位句，而不是认长度。
_FALLBACK_MARKERS = ("待补充", "依此类推", "类似可得", "不再赘述", "本节内容")


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _structure(text: str) -> dict:
    """正文的形状。用来回答"两次生成是不是同一份"和"有没有实质内容"。"""
    lines = (text or "").splitlines()
    sections = [line.strip() for line in lines if line.strip().startswith("## ")]
    return {
        "chars": len(text or ""),
        "sections": sections,
        "section_count": len(sections),
        "code_blocks": (text or "").count("```") // 2,
        "digest": _digest(text),
    }


def _looks_like_fallback(text: str) -> bool:
    """正文是不是兜底骨架。

    **只看占位句，不看长度**：骨架可以很长（它照样有标题和几句车轱辘话），
    而一份短但内容实的资源不该被误判成兜底。
    """
    return any(marker in (text or "") for marker in _FALLBACK_MARKERS)


def _content_of(final_resources: dict, events: list[dict], resource_type: str) -> str:
    """取这个类型的最终正文。

    优先用 `resource_complete` 事件里那份（**落库前推的那一份**，与前端看到的同源），
    没有就退回图最终状态里的。两条路都拿不到就是空串 —— 那本身就是结论，
    别用别的类型的内容糊上去。
    """
    for event in reversed(events):
        if event.get("type") == "resource_complete" and event.get("resource_type") == resource_type:
            content = event.get("content")
            if content:
                return str(content)
    value = (final_resources or {}).get(resource_type)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("content") or "")
    return ""


async def generate_once(user_id: int, topic: str, resource_types: list[str], round_index: int) -> dict:
    """跑一次生成，把**正文 + 全部事件**收下来。"""
    from backend.src.ai_core.resource_graph import resource_graph
    from backend.src.service.resource.generation_context import make_generation_state

    started = time.perf_counter()
    state = await make_generation_state(topic, user_id, list(resource_types))
    events: list[dict] = []
    final: dict = {}

    async for mode, chunk in resource_graph.astream(state, stream_mode=["values", "custom"]):
        if mode == "custom":
            if isinstance(chunk, dict):
                events.append(chunk)
        elif isinstance(chunk, dict):
            final = chunk

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    final_resources = final.get("generated_resources") or {}
    items = []
    for resource_type in resource_types:
        content = _content_of(final_resources, events, resource_type)
        shape = _structure(content)
        items.append({
            "type": resource_type,
            "produced": bool(content),
            "fallback_skeleton": _looks_like_fallback(content),
            "review_passed_aggregate": bool(final.get("review_passed")),
            "content": content,
            **shape,
        })

    return {
        "round": round_index,
        "topic": topic,
        "elapsed_ms": elapsed_ms,
        "requested_types": list(resource_types),
        "resources": items,
        # 协同过程：事件按 (角色, 阶段, 状态) 归堆。**留全量**，因为"审核跑没跑"要靠它，
        # 而且报告要能对证（判词能点开看当时到底推了什么）。
        "events": events,
        "event_roles": _role_counts(events),
    }


def _role_counts(events: list[dict]) -> dict:
    """事件按 `(agent_id, phase, status)` 计数。

    字段名是 `phase`/`status`，**没有 `role`**（前端权威副本：
    `frontend/src/entities/agent/agentWorkflowState.js:9-15`）。
    """
    counts: dict[str, int] = {}
    for event in events:
        if event.get("type") != "agent_event":
            continue
        key = f"{event.get('agent_id')}|{event.get('phase')}|{event.get('status')}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize(records: list[dict]) -> dict:
    """把几轮记录折成报告要的数。**只报数，不给门槛。**"""
    produced = 0
    requested = 0
    skeletons: list[str] = []
    digests: dict[str, list[int]] = {}
    reviewer_states: dict[str, int] = {}
    cross_validation_events = 0
    roles_seen: set[str] = set()

    for record in records:
        for item in record["resources"]:
            requested += 1
            if item["produced"]:
                produced += 1
            if item["fallback_skeleton"]:
                skeletons.append(f"第{record['round']}轮 {item['type']}")
            if item["produced"]:
                digests.setdefault(item["type"], []).append(item["digest"])
        for key, count in record["event_roles"].items():
            agent_id, phase, status = key.split("|")
            roles_seen.add(agent_id)
            if phase == "reviewer":
                reviewer_states[f"{agent_id}|{status}"] = reviewer_states.get(f"{agent_id}|{status}", 0) + count
            if "cross_validator" in agent_id:
                cross_validation_events += count

    # 同一类型在不同轮次拿到同一个正文哈希 = 两次生成是同一份内容。
    # **这是"缓存复用"的唯一可见信号**，所以重复要逐条点出来，不能只给个数。
    repeated = {rt: hashes for rt, hashes in digests.items()
                if len(hashes) > 1 and len(set(hashes)) < len(hashes)}

    return {
        "轮数": len(records),
        "类型产出率": (produced / requested) if requested else None,
        "请求数": requested,
        "产出数": produced,
        "兜底骨架清单": skeletons,
        "跨轮重复的正文": repeated,
        "审核状态分布": reviewer_states,
        "交叉验证事件数": cross_validation_events,
        "出现过的角色": sorted(roles_seen),
        "各轮耗时毫秒": [record["elapsed_ms"] for record in records],
    }


def render(summary: dict, records: list[dict], source_name: str) -> str:
    lines = [
        "# 学习资料生成评估",
        "",
        f"- 主题：`{FIXED_TOPIC}`",
        f"- 类型：{'、'.join(RESOURCE_TYPES)}",
        f"- 轮数：{summary['轮数']}（每轮都是独立生成，不复用缓存）",
        f"- 记录：`{source_name}`（含每份资源的完整正文与全部事件）",
        "",
        "> 生成走的是生产的 `resource_graph.astream`（与 `generate_stream` 内部同一调用），",
        "> 事件用 `stream_mode=[\"values\",\"custom\"]` 全量收下 —— 用 `ainvoke` 会让事件**静默丢失**。",
        "",
        "## 一、产出完整性",
        "",
    ]
    rate = summary["类型产出率"]
    lines += [f"- 请求 {summary['请求数']} 份，产出 {summary['产出数']} 份"
              + (f"（{rate:.0%}）" if rate is not None else ""), ""]
    if summary["兜底骨架清单"]:
        lines += [f"- ⚠️ **{len(summary['兜底骨架清单'])} 份是兜底骨架**（事件里仍报 `done`）："
                  + "、".join(summary["兜底骨架清单"]), ""]
    else:
        lines += ["- 没有命中兜底骨架字样", ""]

    lines += ["## 二、跨轮稳定性（也是「缓存有没有偷偷生效」的探针）", ""]
    if summary["跨轮重复的正文"]:
        for resource_type, hashes in summary["跨轮重复的正文"].items():
            lines += [f"- ⚠️ `{resource_type}` 跨轮拿到相同正文：{hashes}"]
    else:
        lines += ["- 同一类型的各轮正文哈希互不相同 —— 没有复用同一份内容"]
    lines += [""]

    lines += ["## 三、审核到底跑没跑（从事件数）", ""]
    if summary["审核状态分布"]:
        lines += ["| 审核者 \\| 状态 | 事件数 |", "|---|---|"]
        for key, count in sorted(summary["审核状态分布"].items()):
            lines += [f"| {key} | {count} |"]
        lines += ["", "> `failed` 是审核调用抛异常；`retrying` 是审核没过、准备重写；"
                  "`done` 是通过或无需审核。"
                  "**只有 `failed` 才是故障放行**，`done` 里混着「跳过审核」（见第 4 节）。", ""]
    else:
        lines += ["（一个审核者事件都没有 —— 要么这一轮 `skip_review`，要么事件丢了）", ""]

    lines += ["## 四、协同过程：出现过哪些角色", ""]
    lines += ["、".join(f"`{role}`" for role in summary["出现过的角色"]) or "（无）", ""]
    lines += [f"- 交叉验证事件数：**{summary['交叉验证事件数']}**"
              "（`cross_validator` 只在**文档**那条链上推事件，PPT 没有 —— 见 `resource_document.generate_document_parallel` 里推 cross_validator 事件那几处）", ""]

    lines += ["## 五、每份资源的形状", ""]
    for record in records:
        lines += [f"### 第 {record['round']} 轮（{record['elapsed_ms']} ms）", ""]
        for item in record["resources"]:
            verdict = [] if item["produced"] else ["**没产出**"]
            if item["fallback_skeleton"]:
                verdict.append("兜底骨架")
            flag = ("　" + "，".join(verdict)) if verdict else ""
            lines += [f"- `{item['type']}`：{item['chars']} 字，{item['section_count']} 个小节，"
                      f"{item['code_blocks']} 个代码块，哈希 `{item['digest']}`{flag}"]
        lines += [""]

    lines += [
        "## 六、这份评估没覆盖的", "",
        "- **`exercise` 没测**：节点资源里它被显式排除（`service/path/service.py:1347`），"
        "走的是独立测验链。要测它得另起一条。",
        "- **`case` / `reading` / `video` / `image` 没测**：它们只在提示词碰巧输出时才出现，"
        "不是稳定可请求的类型。",
        "- **内容真不真不在这里判**：正文已落进 json，判定在 `claim_audit.py`（可以反复重跑，"
        "不用重新花钱生成）。",
        "",
    ]
    return "\n".join(lines) + "\n"


async def run(rounds: int) -> tuple[list[dict], str]:
    user = await subject_module.ensure_user()
    records: list[dict] = []
    try:
        for index in range(1, rounds + 1):
            print(f"[resource-eval] 第 {index}/{rounds} 轮…", file=sys.stderr)
            records.append(await generate_once(user.id, FIXED_TOPIC, list(RESOURCE_TYPES), index))
    finally:
        deleted = await subject_module.purge_by_id(user.id)
        print(f"[resource-eval] 已清理合成学生的数据：{deleted}", file=sys.stderr)
    return records, time.strftime("%Y%m%d-%H%M%S")


def _write(records: list[dict], stamp: str) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = summarize(records)
    json_path = RESULTS_DIR / f"{stamp}-resource-eval.json"
    md_path = RESULTS_DIR / f"{stamp}-resource-eval.md"
    # 正文和事件一起落盘：**判词要能对证**，而判定那一步要重跑时不能再花一次生成的钱。
    json_path.write_text(
        json.dumps({"topic": FIXED_TOPIC, "types": list(RESOURCE_TYPES),
                    "summary": summary, "records": records},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    md_path.write_text(render(summary, records, json_path.name), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习资料生成评估")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    async def _drive():
        await init_db()
        try:
            return await run(args.rounds)
        finally:
            await close_db()

    records, stamp = asyncio.run(_drive())
    md_path, json_path = _write(records, stamp)
    print(render(summarize(records), records, json_path.name))
    print(f"写好了：{md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
