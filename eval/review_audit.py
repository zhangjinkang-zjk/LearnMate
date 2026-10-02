# -*- coding: utf-8 -*-
"""**审核到底跑没跑** —— 从一轮 eval 的后端日志里数出来（能力三）。

## 为什么只能从日志里数

两条生成链都有"故障放行"：审核没跑成时，对外的结论和"审核通过"长得**一样**。

- **路径链**：`path_graph.reviewer_node` 在 `except` 里返回 `review_passed=True`，只把
  `review_source` 置成 `"error"`。正常通过是 `"llm"`，无节点可审是 `"skipped"`。
- **资源链**：逐资源类型的 reviewer 异常时返回 `{"passed": True, "score": 0, ...}`。

而 `review_source` **不落库** —— `LearningPath` / `GeneratedResource` 都没有这一列，
落库的 `review_passed` 对此是瞎的（章节级的故障放行根本不进这个聚合）。它唯一的去处是
`service/path/service.py` 那两行日志（error 走 WARNING，就是为了"在日志里一眼捞出来"）。

所以这个模块**不产生任何模型调用**：它读的是那一轮已经跑完的日志。同一个目录下几个
`_*.log` 就是历次运行的原始证据，可以随时重算 —— 这正是 `README` 说的"判词要能对证"。

## 它看不见什么（说清楚，别当成"一切都好"）

- **资源链全局 reviewer 的异常看不见。** `_push_agent_event(..., "failed", ...)` 推的是
  SSE 事件、返回值里才带 `审核异常`，既不落库也不打日志。所以那一处的故障放行**没有痕迹**，
  本模块报不出来 —— 这是覆盖缺口，不是"零故障"。
- **`source=skipped` 不等于故障**，它是"没有节点可审"（空路径）。所以三态要分开计数，
  不能把 `skipped` 并进 `error`：前者是没事可做，后者是做事失败了。
- 日志级别被调过就少一半证据。`journey.py` 的 `main()` 显式 `basicConfig(level=INFO)`；
  换成只放 WARNING 的跑法，**"审核通过"那 13 行会消失**，于是执行率会算成 0。
  所以读的时候先看日志里有没有 `路径审核结果` 这一行 —— 没有就是级别没放开，不是没审。

## 指标（只报数，不给门槛）

审核实际执行率（`source=llm` 的路径 / 生成的路径）、故障放行清单（逐条，含主体与当时结论）、
PPT 章节异常数、兜底章数。分档与"不合格"的判据见 `README` 第二节能力三。
"""
import argparse
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval" / "results"
LOG_GLOB = "eval/_*.log"

# 每条正则对着生产里那一行 `logger.*(...)` 的格式串写，不是对着样例猜的 ——
# 改了那边的格式串，这里会**匹配不到**（表现为数字变成 0），不会匹配错。
_PATH_REVIEW = re.compile(
    r"路径审核结果 subject=(?P<subject>.+?) passed=(?P<passed>\S+) "
    r"source=(?P<source>\S+) nodes=(?P<nodes>\d+) retry=(?P<retry>\S+)"
)
_PPT_SUMMARY = re.compile(
    r"\[PPT-Review\] 审核汇总 章节=(?P<sections>\d+) 送审=(?P<sent>\d+)次 "
    r"未通过=(?P<failed>\d+)次 达标=(?P<ok>\d+)章 兜底=(?P<fallback>\d+)章"
)
_PPT_PASS = re.compile(
    r"\[PPT-Review\] idx=(?P<idx>\d+) section=(?P<section>.+?) "
    r"round=(?P<round>\d+) 审核通过 score=(?P<score>\S+)"
)
_PPT_REJECT = re.compile(
    r"\[PPT-Review\] idx=(?P<idx>\d+) section=(?P<section>.+?) "
    r"round=(?P<round>\d+) 审核未通过: (?P<reason>.+)"
)
_PPT_FALLBACK = re.compile(
    r"\[PPT-Review\] idx=(?P<idx>\d+) section=(?P<section>.+?) "
    r"达最大审核次数 (?P<used>\d+)/(?P<total>\d+)，使用安全兜底版本"
)
_PPT_ERROR = re.compile(r"\[PPT-Review\] section=(?P<section>.+?) 审核异常")
_DOC_SUMMARY = re.compile(
    r"\[Doc-Review\] 质检汇总 小节=(?P<sections>\d+) 首轮达标=(?P<first_ok>\d+) "
    r"质量重写=(?P<rewrite>\d+)次 异常重写=(?P<error_rewrite>\d+)次 "
    r"兜底=(?P<fallback>\d+)节 整章重修=(?P<redo>\d+)轮"
)

# `logger.exception` 会把 traceback 接着打在后面几行，那些行不该被当成独立事件。
# 判据是行首不是 loguru/logging 的级别前缀 —— 上面每条正则都要求中文标签连着出现，
# traceback 行里不会凑巧凑齐，所以这里不做额外过滤，只把 `审核异常` 的**计数**留着。


def parse_log(text: str) -> dict:
    """把一段日志文本切成四类审核事实。不判分，只陈述。"""
    path_reviews: list[dict] = []
    ppt = {"summary": None, "passed": [], "rejected": [], "fallback": [], "errors": []}
    doc = {"summary": None}

    for line in text.splitlines():
        match = _PATH_REVIEW.search(line)
        if match:
            item = match.groupdict()
            path_reviews.append({
                "subject": item["subject"],
                "passed": item["passed"] == "True",
                "source": item["source"],
                "nodes": int(item["nodes"]),
                "retry": item["retry"],
            })
            continue

        match = _PPT_SUMMARY.search(line)
        if match:
            ppt["summary"] = {key: int(value) for key, value in match.groupdict().items()}
            continue

        match = _PPT_REJECT.search(line)
        if match:
            item = match.groupdict()
            ppt["rejected"].append({
                "section": item["section"], "round": int(item["round"]),
                "reason": item["reason"].strip(),
            })
            continue

        match = _PPT_FALLBACK.search(line)
        if match:
            item = match.groupdict()
            ppt["fallback"].append({
                "section": item["section"],
                "used": int(item["used"]), "total": int(item["total"]),
            })
            continue

        match = _PPT_PASS.search(line)
        if match:
            item = match.groupdict()
            ppt["passed"].append({"section": item["section"], "round": int(item["round"])})
            continue

        match = _PPT_ERROR.search(line)
        if match:
            ppt["errors"].append({"section": match.group("section")})
            continue

        match = _DOC_SUMMARY.search(line)
        if match:
            doc["summary"] = {key: int(value) for key, value in match.groupdict().items()}

    return {"path_reviews": path_reviews, "ppt": ppt, "doc": doc}


def summarize(parsed: dict) -> dict:
    """把事实折算成 README 里那三个指标名。"""
    reviews = parsed["path_reviews"]
    by_source: dict[str, int] = {}
    for item in reviews:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1

    # 分母是"生成出来的路径数"。`llm` 才算真的执行过审核；`skipped`（无节点可审）和
    # `error`（审核抛异常后放行）都不算 —— 但两者的**含义不同**，所以清单里分开列。
    total = len(reviews)
    executed = by_source.get("llm", 0)
    ppt = parsed["ppt"]
    doc = parsed["doc"]

    # 分母是**生成记录数**，不是科目数：同一轮里某个科目被重复生成（换了大纲重跑）就会
    # 出现多行。不点明的话，"5 条路径"会被读成"5 个科目各审了一遍"。
    counts: dict[str, int] = {}
    for item in reviews:
        counts[item["subject"]] = counts.get(item["subject"], 0) + 1

    return {
        "路径数": total,
        "路径审核来源分布": by_source,
        "重复生成的科目": {name: n for name, n in counts.items() if n > 1},
        "审核实际执行率": (executed / total) if total else None,
        "故障放行清单": [item for item in reviews if item["source"] == "error"],
        "未执行审核清单": [item for item in reviews if item["source"] == "skipped"],
        # 下面这些是"日志级别没放开就会是 0"的那一类，读的时候先确认不是这个原因。
        "PPT 审核汇总": ppt["summary"],
        "PPT 章节异常": ppt["errors"],
        "PPT 兜底章节": ppt["fallback"],
        "PPT 未通过次数": len(ppt["rejected"]),
        "文档质检汇总": doc["summary"],
    }


def render(summary: dict, source_name: str) -> str:
    lines = [
        "# 审核执行审计（能力三）",
        "",
        f"- 日志：`{source_name}`",
        f"- 生成的路径：{summary['路径数']} 条",
        "",
        "> `review_source` 不落库，只有日志里有。这份审计不产生任何模型调用，",
        "> 读的是那一轮已经跑完的日志 —— 判词可以对着原文核。",
        "",
        "## 一、路径链：审核实际执行率",
        "",
    ]

    rate = summary["审核实际执行率"]
    lines += [f"**{rate:.0%}**（`source=llm` {summary['路径审核来源分布'].get('llm', 0)} 条 / 共 {summary['路径数']} 条）"
              if rate is not None else "**算不出**：日志里没有 `路径审核结果` 这一行 —— 大概率是日志级别没放开，不是没审。", ""]

    # 分母是**生成记录数**，不是科目数：同一轮里某个科目被重复生成（换了大纲重跑）就会出现
    # 多行。不点明的话，"5 条路径"会被读成"5 个科目各审了一遍"。
    if summary["重复生成的科目"]:
        lines += ["其中被重复生成的科目："
                  + "、".join(f"{name} ×{n}" for name, n in sorted(summary["重复生成的科目"].items()))
                  + "（分母是生成记录数，不是科目数）。", ""]
    if summary["路径审核来源分布"]:
        lines += ["| source | 条数 | 含义 |", "|---|---|---|",
                  "| `llm` | {} | 真的调了审核模型 |".format(summary["路径审核来源分布"].get("llm", 0)),
                  "| `skipped` | {} | 没有节点可审（不是故障）|".format(summary["路径审核来源分布"].get("skipped", 0)),
                  "| `error` | {} | **审核抛异常后放行** |".format(summary["路径审核来源分布"].get("error", 0)),
                  ""]

    lines += ["## 二、故障放行清单（逐条，要能对证）", ""]
    if summary["故障放行清单"]:
        for item in summary["故障放行清单"]:
            lines += [f"- **{item['subject']}** —— 对外结论 `passed={item['passed']}`，"
                      f"但审核没跑成（`source=error`），路径仍被放行，{item['nodes']} 个节点，重试 {item['retry']} 次"]
    else:
        lines += ["（无）"]
    lines += [""]

    if summary["未执行审核清单"]:
        lines += ["另外 {} 条是 `skipped`（无节点可审），与上表不同：".format(len(summary["未执行审核清单"])), ""]
        for item in summary["未执行审核清单"]:
            lines += [f"- {item['subject']}（{item['nodes']} 个节点）"]
        lines += [""]

    lines += ["## 三、资源链：PPT 逐章节", ""]
    if summary["PPT 审核汇总"]:
        item = summary["PPT 审核汇总"]
        lines += [f"- 章节 {item['sections']}，送审 {item['sent']} 次，未通过 {item['failed']} 次，"
                  f"达标 {item['ok']} 章，兜底 {item['fallback']} 章", ""]
    else:
        lines += ["（这一轮没跑 PPT，或日志里没有汇总行）", ""]
    if summary["PPT 章节异常"]:
        lines += [f"**{len(summary['PPT 章节异常'])} 个章节走了异常路径**（对外用的是兜底版本）：", ""]
        for item in summary["PPT 章节异常"]:
            lines += [f"- {item['section']}"]
        lines += [""]
    if summary["PPT 兜底章节"]:
        lines += ["走到最大审核次数、用安全兜底版本的章节：", ""]
        for item in summary["PPT 兜底章节"]:
            lines += [f"- {item['section']}（审核 {item['used']}/{item['total']} 次）"]
        lines += [""]

    lines += ["## 四、资源链：文档逐小节", ""]
    if summary["文档质检汇总"]:
        item = summary["文档质检汇总"]
        lines += [f"- 小节 {item['sections']}，首轮达标 {item['first_ok']}，质量重写 {item['rewrite']} 次，"
                  f"**异常重写 {item['error_rewrite']} 次**，兜底 {item['fallback']} 节，整章重修 {item['redo']} 轮", ""]
    else:
        lines += ["（这一轮没跑文档，或日志里没有汇总行）", ""]

    lines += [
        "## 五、这份审计看不见的", "",
        "- **资源链全局 reviewer 的异常**：只进 SSE 事件和返回值，既不落库也不打日志，"
        "所以那一处的故障放行在这里是**零痕迹**。这是覆盖缺口，不是零故障。",
        "- **判据的边界**：本模块判的是「审核跑没跑」，不判「审核判得对不对」—— 后者要看 "
        "`results/*-transcripts.md` 里的理由。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 eval 的后端日志里数审核执行情况")
    parser.add_argument("logs", nargs="*", help="日志文件；不给就用 eval/_*.log 里最新那个")
    parser.add_argument("--all", action="store_true", help="把所有 eval/_*.log 一起算（合并计数）")
    parser.add_argument("--print", dest="to_stdout", action="store_true", help="只打屏，不落盘")
    args = parser.parse_args(argv)

    if args.logs:
        logs = [Path(p) for p in args.logs]
    else:
        logs = sorted(REPO_ROOT.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
        if not args.all:
            logs = logs[:1]
    logs = [p for p in logs if p.exists()]
    if not logs:
        print(f"没找到日志：{LOG_GLOB}", file=sys.stderr)
        return 1

    merged = {"path_reviews": [], "ppt": {"summary": None, "passed": [], "rejected": [], "fallback": [], "errors": []},
              "doc": {"summary": None}}
    for path in logs:
        parsed = parse_log(_read(path))
        merged["path_reviews"] += parsed["path_reviews"]
        for key in ("passed", "rejected", "fallback", "errors"):
            merged["ppt"][key] += parsed["ppt"][key]
        # 汇总行是**每份日志一行**，合并多份时取最后一份非空的即可（不叠加：它是该轮的计数）
        if parsed["ppt"]["summary"]:
            merged["ppt"]["summary"] = parsed["ppt"]["summary"]
        if parsed["doc"]["summary"]:
            merged["doc"]["summary"] = parsed["doc"]["summary"]

    summary = summarize(merged)
    text = render(summary, "、".join(p.name for p in logs))
    print(text)
    if not args.to_stdout:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-review-audit.md"
        out.write_text(text, encoding="utf-8")
        print(f"写好了：{out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
