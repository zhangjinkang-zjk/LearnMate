"""清理知识库里的非教学数据。

背景：库里混进了两类不该作为「学习资料」被检索的内容——内部开发改动日志，以及标题是
垃圾字符串的内部接口文档。reference 模式的提示词虽然写了「资料明显不相关时优先用通用
解释」，但让它们被检索命中本身仍是噪声。

**明确不删**这 5 篇评测语料：rag-tuning-manual.md、enterprise-agent-role-map.md、
agent-eval-deploy-rubric.md、agent-collab-dev-standard.md、retrieval-corpus-samples.md。
它们是刻意植入的语料，提交物的 60 条库内评测问题里有 46 条依赖它们，删掉等于把评测集打瘸。

用法（默认只预演，不删任何东西）：

    python backend/scripts/purge_noncurriculum_docs.py           # 预演
    python backend/scripts/purge_noncurriculum_docs.py --apply   # 真正删除

脚本幂等：重复执行时，已删掉的目标会显示 0 条命中。
"""
import argparse
import asyncio
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PurgeTarget(NamedTuple):
    """一个要清理的文档。base_title 是切片前的文档名。"""

    base_title: str
    reason: str


PURGE_TARGETS: tuple[PurgeTarget, ...] = (
    PurgeTarget(
        base_title="LearnMate改动清单_2026-09-03_17.md",
        reason="内部开发改动日志，不是教学资料；会被上传者自己的检索命中并注入生成内容",
    ),
    PurgeTarget(
        base_title="11",
        reason="内部接口文档，标题是垃圾字符串；pending 状态本就不参与检索，属库内卫生",
    ),
)


def _is_chunk_of(title: str, base_title: str) -> bool:
    """切片标题形如「{文档名} (第N部分)」；只有一片时就是文档名本身。

    与 knowledge_router.py 里拼标题的规则保持一致。
    """
    title = (title or "").strip()
    return title == base_title or title.startswith(f"{base_title} (第")


async def purge(apply_changes: bool) -> int:
    from backend.src.models.knowledgemodel import KnowledgeVector
    from backend.src.utils.database import close_db, init_db

    await init_db()
    try:
        rows = await KnowledgeVector.all().values("doc_id", "title", "visibility")
        doc_ids: list[str] = []

        for target in PURGE_TARGETS:
            matched = [r for r in rows if _is_chunk_of(r["title"], target.base_title)]
            print(f"\n【{target.base_title}】")
            print(f"  理由：{target.reason}")
            if not matched:
                print("  命中 0 片（已清理过，或本库没有）")
                continue
            seen = sorted({r["visibility"] for r in matched})
            print(f"  命中 {len(matched)} 片，可见性：{', '.join(seen)}")
            for r in sorted(matched, key=lambda x: x["title"])[:3]:
                print(f"    - {r['title']}")
            if len(matched) > 3:
                print(f"    … 其余 {len(matched) - 3} 片")
            doc_ids.extend(r["doc_id"] for r in matched)

        if not doc_ids:
            print("\n没有需要清理的数据。")
            return 0

        if not apply_changes:
            print(f"\n[预演] 共将删除 {len(doc_ids)} 片。加 --apply 才真正执行。")
            return len(doc_ids)

        deleted = await KnowledgeVector.filter(doc_id__in=doc_ids).delete()
        print(f"\n已删除 {deleted} 片。")
        return deleted
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="真正执行删除；不加则只预演")
    args = parser.parse_args()
    asyncio.run(purge(apply_changes=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
