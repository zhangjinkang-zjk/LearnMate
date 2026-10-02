# -*- coding: utf-8 -*-
"""学习资料**内容真不真**：拿预注册的可执行底本去逐条核对生成出来的正文。

## 为什么不是"再让一个模型打一遍分"

生成资料的是模型，审核资料的也是模型，再请第三个模型来判"对不对" —— 三个同源的东西互相
点头，写进文档站不住。这里的做法是：**判据是仓库里手写的、能跑出结果的底本**
（`eval/reference/*.yaml`，每条都带一段 `probe` 和实跑得到的 `expect`，
`backend/tests/test_reference_probes.py` 保证它自洽）。

模型在这条链上只做一件机械的事：**从材料里找出它主张了什么**，然后对到某条底本上。
判决来自底本 —— 材料如果落在底本记的"常见错法"那个形状上，就是与实跑输出直接矛盾。
**它没法推翻实跑结果**，因为实跑结果是我喂给它的，不是它回忆的。

## 输入输出

    输入   eval/results/<时间戳>-resource-eval.json（`resource_eval.py` 生成，含完整正文）
    输出   eval/results/<时间戳>-claim-audit.md

判定不重新生成资料 —— 生成要花钱，判定得能反复重跑。

## 边界（写清楚，别当成"全都核过了"）

- **只核底本覆盖到的那几点**。材料里其他说法一律记 `absent`，进分母，**不假装核过**。
  所以"谬误率"的分母是"材料就底本条目作出主张的次数"，不是"材料说了多少句话"。
- 材料没说错的**不等于**材料是对的：它可能只是没提到这一点。报告里两者分开列。
- 判据的强度取决于底本。底本只覆盖 Python 参数传递这一个主题（选它是因为能机械核验），
  换成别的主题得另写底本 —— **没有底本的主题，这份审计一条都判不了**，它会如实报 0 条。
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

import yaml  # noqa: E402

from backend.src.utils.json_parser import parse_llm_json  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"
REFERENCE_DIR = REPO_ROOT / "eval" / "reference"

# 判据用温度 0：这一步要的是**可重复的匹配**，不是创作。采样会让同一份材料两轮判出
# 不同的结论，那样"这次比上次好"就说不清了。
JUDGE_TEMPERATURE = 0.0

VERDICTS = ("supports", "contradicts", "absent")


def load_reference(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {"topic": data.get("topic"), "claims": data["claims"]}


def _build_prompt(claims: list[dict], material: str, material_name: str) -> str:
    lines = [
        "你在做一次**逐条核对**，不是自由评论。",
        "",
        "下面是底本里的断言。每条都给了「正确说法」和一个「常见错法」：",
        "",
    ]
    for claim in claims:
        lines += [f"- id: {claim['id']}",
                  f"  正确说法：{claim['claim']}",
                  f"  常见错法：{claim.get('wrong', '（无）')}"]
    lines += [
        "",
        f"## 待核对的材料（{material_name}）",
        "",
        material,
        "",
        "## 你要做的",
        "逐条判断**材料里有没有就这条断言作出主张**：",
        '- 说对了 → verdict 填 "supports"，quote 抄材料原句',
        '- 说错了（落在「常见错法」那个形状上，或与「正确说法」矛盾）→ verdict 填 "contradicts"，'
        "quote 抄材料原句",
        '- 材料里根本没提这一点 → verdict 填 "absent"，quote 留空字符串',
        "",
        "规矩：",
        "- **只判材料里真的写了什么**，不要判「材料应该写什么」，也不要用你自己的知识去补"
        "材料没说的话。",
        "- quote 必须是材料里的**原句**，一个字都不要改写。找不到原句就不要填 "
        "supports / contradicts。",
        "- 材料说得含糊（既没写错也没写明）→ 记 absent。",
        "",
        "## 输出（只输出 JSON，不要解释）",
        '{"findings": [{"ref": "<id>", "verdict": "supports|contradicts|absent", "quote": "<原句或空串>"}]}',
        "每条底本断言都要有一项，顺序不限。",
    ]
    return "\n".join(lines)


def _normalise(reply: object, claims: list[dict]) -> list[dict]:
    """把模型回话整成 findings。**认不出的结论一律记 absent，不替它编。**

    返回里带 `invalid` 标记的那些是模型给了非法 verdict 的 —— 单独计数，
    因为那说明这条判据在这一次上**没测到**，而不是"材料没提"。
    """
    text = str(getattr(reply, "content", reply) or "")
    parsed = parse_llm_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        raise ValueError("判官回话里没有 findings 数组")

    by_ref: dict[str, dict] = {}
    for item in parsed["findings"]:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").strip()
        verdict = str(item.get("verdict") or "").strip().lower()
        if ref not in {claim["id"] for claim in claims}:
            continue
        if verdict not in VERDICTS:
            by_ref[ref] = {"ref": ref, "verdict": "absent", "quote": "",
                           "invalid": str(item.get("verdict"))}
            continue
        by_ref[ref] = {"ref": ref, "verdict": verdict, "quote": str(item.get("quote") or "").strip()}

    out = []
    for claim in claims:
        found = by_ref.get(claim["id"])
        # 模型漏答某一条时**不当作 absent**：absent 是"材料没提"，漏答是"这次没测到"，
        # 混起来会把判据的覆盖率吹高。
        out.append(found or {"ref": claim["id"], "verdict": "absent", "quote": "", "missing": True})
    return out


async def audit_one(claims: list[dict], resource: dict, label: str) -> dict:
    from backend.src.ai_core.llm_config import llm

    prompt = _build_prompt(claims, resource.get("content") or "", label)
    base = {"label": label, "type": resource.get("type"), "chars": resource.get("chars")}
    try:
        reply = await llm.ainvoke(prompt, pool="eval", temperature=JUDGE_TEMPERATURE)
        findings = _normalise(reply, claims)
    except Exception as exc:  # 判官自己挂了，如实记下来，不替它编结论
        return {**base, "error": f"{type(exc).__name__}: {exc}", "findings": []}
    return {**base, "findings": findings}


def summarize(audits: list[dict], claims: list[dict]) -> dict:
    counts = {verdict: 0 for verdict in VERDICTS}
    invalid = 0
    missing = 0
    errors = 0
    unquoted = 0

    for audit in audits:
        if audit.get("error"):
            errors += 1
            continue
        for finding in audit["findings"]:
            counts[finding["verdict"]] += 1
            if finding.get("invalid"):
                invalid += 1
            if finding.get("missing"):
                missing += 1
            # supports / contradicts 必须带原句，否则**这条判词没法对证**
            if finding["verdict"] in ("supports", "contradicts") and not finding.get("quote"):
                unquoted += 1

    asserted = counts["supports"] + counts["contradicts"]
    return {
        "材料数": len(audits),
        "底本断言数": len(claims),
        "支持": counts["supports"],
        "反驳": counts["contradicts"],
        "未涉及": counts["absent"],
        "谬误率": (counts["contradicts"] / asserted) if asserted else None,
        "断言触及率": (asserted / (len(audits) * len(claims))) if audits and claims else None,
        "判官报错数": errors,
        "判官给了非法结论数": invalid,
        "判官漏答数": missing,
        "有结论但没抄原句数": unquoted,
    }


def render(summary: dict, audits: list[dict], claims: list[dict], source_name: str) -> str:
    by_id = {claim["id"]: claim for claim in claims}
    lines = [
        "# 学习资料内容真实性审计",
        "",
        f"- 底本：`eval/reference/`（{summary['底本断言数']} 条预注册断言，每条带可执行探针）",
        f"- 材料：{summary['材料数']} 份，来自 `{source_name}`",
        "",
        "> 判据是仓库里手写的、能跑出结果的底本；模型只负责**从材料里找出它主张了什么**，",
        "> 判决来自探针在解释器里的真实输出。判词一律带材料原句，可以对着核。",
        "",
        "## 一、总览",
        "",
    ]
    rate = summary["谬误率"]
    lines += [f"- **谬误率 {rate:.0%}**（材料就底本条目作出主张 {summary['支持'] + summary['反驳']} 次，"
              f"其中 {summary['反驳']} 次与实跑输出矛盾）" if rate is not None
              else "- **谬误率算不出**：材料没有就任何一条底本断言作出主张", ""]
    reach = summary["断言触及率"]
    lines += [f"- 断言触及率 {reach:.0%}（{summary['材料数']} 份 × {summary['底本断言数']} 条里被触及的比例）"
              if reach is not None else "- 断言触及率算不出", ""]
    lines += ["| 结论 | 次数 |", "|---|---|",
              f"| 支持（说对了） | {summary['支持']} |",
              f"| 反驳（与实跑矛盾） | {summary['反驳']} |",
              f"| 未涉及（材料没提） | {summary['未涉及']} |", ""]

    caveats = []
    if summary["判官报错数"]:
        caveats.append(f"判官自身报错 {summary['判官报错数']} 次（那几份材料这次**没测到**）")
    if summary["判官给了非法结论数"]:
        caveats.append(f"判官给出非法结论 {summary['判官给了非法结论数']} 次（按未涉及记，不算材料没提）")
    if summary["判官漏答数"]:
        caveats.append(f"判官漏答底本条目 {summary['判官漏答数']} 次（按未涉及记，不吹高覆盖率）")
    if summary["有结论但没抄原句数"]:
        caveats.append(f"有 {summary['有结论但没抄原句数']} 条结论没抄原句（判词无法对证，已计入上表）")
    if caveats:
        lines += ["**判据自身的毛病（不是材料的毛病）：**", ""] + [f"- {item}" for item in caveats] + [""]

    lines += ["## 二、逐条反驳（要对证就从这里看）", ""]
    found = False
    for audit in audits:
        for finding in audit.get("findings", []):
            if finding["verdict"] != "contradicts":
                continue
            found = True
            claim = by_id[finding["ref"]]
            lines += [
                f"### {audit['label']} —— `{finding['ref']}`",
                "",
                f"- 材料原句：{finding.get('quote') or '**（没抄原句，这条判词没法对证）**'}",
                f"- 底本的正确说法：{claim['claim']}",
                f"- 底本记的常见错法：{claim.get('wrong', '（无）')}",
                f"- 探针实测输出：`{claim['expect']}`",
                "",
                "```python",
                claim["probe"].rstrip(),
                "```",
                "",
            ]
    if not found:
        lines += ["（没有）", ""]

    lines += ["## 三、每份材料覆盖到哪几条", ""]
    lines += ["| 材料 | 支持 | 反驳 | 未涉及 |", "|---|---|---|---|"]
    for audit in audits:
        if audit.get("error"):
            lines += [f"| {audit['label']} | — | — | — |（判官报错：{audit['error'][:60]}）"]
            continue
        counts = {verdict: 0 for verdict in VERDICTS}
        for finding in audit["findings"]:
            counts[finding["verdict"]] += 1
        lines += [f"| {audit['label']} | {counts['supports']} | {counts['contradicts']} | {counts['absent']} |"]
    lines += [""]

    lines += [
        "## 四、这份审计的边界", "",
        "- **只核底本覆盖到的点**。底本只覆盖 Python 参数传递这一个主题；材料里其他说法一律记",
        "  「未涉及」，进分母，不假装核过。所以这里的「谬误率」不是「资料整体错误率」。",
        "- **「未涉及」不等于「对」**：材料可能只是没提到这一点。",
        "- **底本的强度就是判据的强度**。换主题要另写底本；没有底本的主题，这份审计一条都判不了。",
        "- 判官是模型（温度 0），它的活是「找出材料主张了什么」这种机械匹配；判决来自探针实跑输出。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _material_label(record: dict, resource: dict) -> str:
    return f"第{record['round']}轮 `{resource['type']}`"


async def run(json_path: Path) -> tuple[list[dict], dict, list[dict]]:
    artifact = json.loads(json_path.read_text(encoding="utf-8"))
    reference = load_reference(REFERENCE_DIR / "python_function_args.yaml")
    claims = reference["claims"]

    tasks = []
    for record in artifact["records"]:
        for resource in record["resources"]:
            if not resource.get("produced"):
                continue  # 没产出正文的材料没什么可核，也不是"没说错"
            tasks.append(audit_one(claims, resource, _material_label(record, resource)))
    audits = await asyncio.gather(*tasks) if tasks else []
    return list(audits), summarize(list(audits), claims), claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习资料内容真实性审计")
    parser.add_argument("artifact", nargs="?",
                        help="resource_eval 产出的 json；不给就用 results/ 里最新那个")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    if args.artifact:
        json_path = Path(args.artifact)
    else:
        candidates = sorted(RESULTS_DIR.glob("*-resource-eval.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("没有找到 *-resource-eval.json，先跑 eval/resource_eval.py", file=sys.stderr)
            return 1
        json_path = candidates[0]

    audits, summary, claims = asyncio.run(run(json_path))
    text = render(summary, audits, claims, json_path.name)
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-claim-audit.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"写好了：{out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
