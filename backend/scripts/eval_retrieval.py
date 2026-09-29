"""知识库检索评测 —— 让 hit@k 变成可重复的回归，而不是一次性数字。

评测集不在仓库里（它属于提交物目录），所以路径必须由外部给出：

    python backend/scripts/eval_retrieval.py --qa-set "…/kb-qa-set.json"
    KB_EVAL_SET="…/kb-qa-set.json" python backend/scripts/eval_retrieval.py

它调用**真实的** `knowledge_base.search()`（不是另写一套打分逻辑），把返回结果里每条
切片的标题解析出来跟期望源文档比对，统计：

    hit@1 / hit@3 / hit@5   库内问题：期望源文档是否出现在前 k 条召回里
    库外拒答率              库外问题：检索层是否**没有**返回任何切片

两点别搞错：
  - 这测的是**切片级精度**，只覆盖评测集对应那 5 篇文档，**不代表整库召回**。
    对外不要说成"整库召回率"。
  - 库外问题只测"检索层有没有乱召回"，**不测**模型最终有没有拒答 ——
    那要看回答内容，不在本脚本范围内。

加 `--save 路径` 可以把逐条结果写成 JSON，便于两次改动之间做 diff。
"""
import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EMPTY_RESULT = "知识库中暂无相关内容"
# search() 的输出形如：【资料1】来源：<标题>（<分类>，score=0.123，doc_id=abcd）
# 标题里若出现全角括号会截断 —— 目前库里的标题都是文件名或「(第N部分)」，不含全角括号。
SOURCE_RE = re.compile(r"【资料\d+】来源：(?P<title>.+?)（")
SCORE_RE = re.compile(r"score=([\d.]+)")
PART_SUFFIX_RE = re.compile(r"\s*[（(]第\d+部分[）)]\s*$")


def _base_title(title: str) -> str:
    """「文档.md (第2部分)」→「文档.md」，与评测集里的 expected_source_doc 对齐。"""
    return PART_SUFFIX_RE.sub("", (title or "").strip())


def _parse_sources(result: str) -> list[str]:
    """从 search() 的文本结果里取出召回切片的标题（按返回顺序）。"""
    if not result or result.strip() == EMPTY_RESULT:
        return []
    return [_base_title(m.group("title")) for m in SOURCE_RE.finditer(result)]


def _load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text("utf-8"))
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise SystemExit(f"评测集格式不对，没找到非空的 items：{path}")
    return items


async def evaluate(qa_set: Path, top_k: int, user_id: int | None, limit: int | None) -> list[dict]:
    """跑完全部题目，返回逐条结果（统计与保存都从这里推导）。"""
    from backend.src.utils import knowledge_base
    from backend.src.utils.database import close_db, init_db
    from backend.src.utils.embeddings import get_model

    items = _load_items(qa_set)
    if limit:
        items = items[:limit]

    await init_db()
    try:
        # 先预热模型：否则第一条的延迟会包含 20s+ 的加载时间，均值没法看
        await get_model()

        details = []
        for item in items:
            question = str(item.get("text") or "")
            expected = item.get("expected_source_doc")
            t0 = time.perf_counter()
            try:
                result = await knowledge_base.search(question, top_k=top_k, user_id=user_id)
            except Exception as exc:  # 单条失败不该中断整轮评测
                result = f"检索异常：{exc}"
            elapsed_ms = (time.perf_counter() - t0) * 1000

            titles = _parse_sources(result)
            scores = [float(x) for x in SCORE_RE.findall(result)]
            is_internal = item.get("kind") == "kb_internal"
            details.append({
                "id": item.get("id"),
                "kind": item.get("kind"),
                "expected": expected,
                "rank": (titles.index(expected) + 1 if expected in titles else None) if is_internal else None,
                "returned": titles,
                "top_score": scores[0] if scores else None,
                "elapsed_ms": round(elapsed_ms),
            })
    finally:
        await close_db()
    return details


def _report(details: list[dict], top_k: int) -> None:
    internal = [d for d in details if d["kind"] == "kb_internal"]
    external = [d for d in details if d["kind"] == "kb_external"]
    total = len(internal)

    print(f"\n库内问题 {total} 条 / 库外问题 {len(external)} 条，检索 top_k={top_k}\n")
    print("  " + "  ".join(
        f"hit@{k} = {sum(1 for d in internal if d['rank'] and d['rank'] <= k)}/{total}"
        f" ({sum(1 for d in internal if d['rank'] and d['rank'] <= k) / total * 100:.0f}%)"
        for k in (1, 3, 5) if k <= top_k
    ))
    if external:
        refused = sum(1 for d in external if not d["returned"])
        print(f"  库外拒答率 = {refused}/{len(external)} ({refused / len(external) * 100:.0f}%)"
              f"   ← 检索层没返回切片才算拒答")

    misses = [d for d in internal if not d["rank"]]
    if misses:
        print(f"\n未命中 {len(misses)} 条（看它到底召回了什么，比只看命中率有用）：")
        for d in misses[:10]:
            print(f"  {d['id']}  期望 {d['expected']}")
            print(f"        实际 {d['returned'][:3] or '（无召回）'}")

    bad_refuse = [d for d in external if d["returned"]]
    if bad_refuse:
        print(f"\n库外问题却召回了切片 {len(bad_refuse)} 条（幻觉诱饵，逐条看）：")
        for d in bad_refuse[:10]:
            print(f"  {d['id']}  召回 {d['returned'][:3]}")

    latencies = [d["elapsed_ms"] for d in details]
    if latencies:
        print(f"\n检索耗时：中位 {statistics.median(latencies):.0f} ms / "
              f"均值 {statistics.mean(latencies):.0f} ms / 最慢 {max(latencies):.0f} ms")

    # 分数尺度：换嵌入模型后，旧的绝对分数阈值（记忆检索 0.30、外部视频 0.55）到底还
    # 合不合适，看这里的两个分布 —— 库内问题应当明显高于库外问题，否则阈值就失效了。
    def _spread(name, values):
        values = [v for v in values if v is not None]
        if not values:
            return
        print(f"  {name:22s} n={len(values):3d}  中位 {statistics.median(values):.3f}  "
              f"最低 {min(values):.3f}  最高 {max(values):.3f}")

    print("\n最高相似度分布（换模型后旧阈值是否还成立，看这里）：")
    _spread("库内问题", [d["top_score"] for d in internal])
    _spread("库外问题", [d["top_score"] for d in external])


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认不是 utf-8

    parser = argparse.ArgumentParser(
        description="知识库检索 hit@k 评测", formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--qa-set", default=os.getenv("KB_EVAL_SET"),
                        help="评测集 JSON 路径；不传则读环境变量 KB_EVAL_SET")
    parser.add_argument("--top-k", type=int, default=5,
                        help="每次检索取回几条（要 ≥5 才算得出 hit@5），默认 5")
    parser.add_argument("--user-id", type=int, default=None,
                        help="以哪个用户身份检索；不传=只看公开资料，默认不传")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条，调试用")
    parser.add_argument("--save", default=None, help="把逐条结果写到这个 JSON 文件")
    args = parser.parse_args()

    if not args.qa_set:
        parser.error("必须给 --qa-set，或设置环境变量 KB_EVAL_SET")
    qa_set = Path(args.qa_set)
    if not qa_set.is_file():
        parser.error(f"评测集不存在：{qa_set}")

    details = asyncio.run(evaluate(qa_set, args.top_k, args.user_id, args.limit))
    _report(details, args.top_k)
    if args.save:
        Path(args.save).write_text(
            json.dumps({"top_k": args.top_k, "user_id": args.user_id, "items": details},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n逐条结果已写入 {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
