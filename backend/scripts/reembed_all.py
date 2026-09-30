"""重算全库向量 —— 换嵌入模型后的迁移脚本。

**什么时候要跑**：改了 `EMBEDDING_MODEL_ID`（或在 registry 里调了切片尺寸）之后。
向量与生成它的模型强绑定，不重算的话检索会静默失效 —— 检索层会检出维度不符并打
error 日志，但数据本身不会自愈。

脚本做四件事：
  1. 把现存切片按文档重建回全文，**剥掉历史上注入进 content 的「上文摘要：」前缀**
  2. 按当前模型登记的尺寸重新切块（`content` 存干净正文）
  3. 用当前模型重新编码（跨片上下文前缀只在编码时拼，不再入库）
  4. 把向量存储格式从 JSON 数组字符串换成 base64(float32)，见 `utils/embeddings/codec.py`

切片边界会被重划（这正是目的之一：旧边界是按上一代模型的窗口定的），
但**内容一条不丢** —— 重建用的是库里存着的全文。

用法（默认只预演，不写库）：

    python backend/scripts/reembed_all.py            # 预演
    python backend/scripts/reembed_all.py --apply    # 真正执行（CPU 上约 10~20 分钟）

**重复执行**：内容只会越拼越全，不会丢（重建用的是库里存着的全文），所以 `--apply`
可以重跑。但**切片边界不保证每次一样** —— 库里只存切片，拼回去的文本和原文件并不完全
一致（段落中间被切断处会变成新段落边界），重切就落在别的位置。想要完全一致的边界，
得保留原始文件，本脚本做不到。
"""
import argparse
import asyncio
import re
import sys
import time
from collections import defaultdict
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 历史上用上一片的尾部做前缀，实现里出现过 150 与 80 两种长度，取大者再宽放一点
OVERLAP_SEARCH_LIMIT = 230


def _base_title(title: str) -> str:
    """「文档名 (第N部分)」→ 「文档名」"""
    return re.sub(r"\s*[（(]第\d+部分[）)]\s*", "", title or "")


def _part_index(title: str) -> int:
    match = re.search(r"[（(]第(\d+)部分[）)]", title or "")
    return int(match.group(1)) if match else 1


def _strip_overlap_prefix(current: str, previous: str) -> str:
    """剥掉历史上注入进 content 的「上文摘要：<上一片尾部>」前缀。

    它写的是 `f"上文摘要：{prev_tail}\\n{current}"`，其中 prev_tail 是上一片尾部最多
    overlap 个字。这里按这个已知关系精确剥离；万一匹配不上就退化成"去掉首行"，
    宁可少剥一点，也不要把正文内容误删。
    """
    from backend.src.utils.file_processor import CONTEXT_PREFIX

    if not current.startswith(CONTEXT_PREFIX):
        return current
    body = current[len(CONTEXT_PREFIX):]

    if previous:
        window = previous[-OVERLAP_SEARCH_LIMIT:]
        for size in range(min(len(body), len(window)), 9, -1):
            candidate = body[:size].strip()
            if candidate and window.endswith(candidate):
                return body[size:].lstrip("\n")

    # 兜底：前缀与上一片对不上（历史数据或人工改过），只去掉第一行
    head, sep, rest = body.partition("\n")
    return rest if sep else body


def _collect_documents(rows: list[dict]) -> list[dict]:
    """把切片按文档族归并、剥前缀、拼回全文。"""
    families: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        families[_base_title(r["title"])].append(r)

    documents = []
    for base, parts in families.items():
        parts.sort(key=lambda r: _part_index(r["title"]))
        texts = []
        prev_raw = ""
        for part in parts:
            raw = part["content"] or ""
            # 前缀来自「未剥过的上一片原始内容」，所以这里要传 raw 而不是 texts[-1]
            texts.append(_strip_overlap_prefix(raw, prev_raw))
            prev_raw = raw
        first = parts[0]
        documents.append(
            {
                "base_title": base,
                "text": "\n\n".join(t for t in texts if t.strip()),
                "old_doc_ids": [p["doc_id"] for p in parts],
                "old_count": len(parts),
                "user_id": first["user_id"],
                "visibility": first["visibility"],
                "category": first["category"],
                "cover_url": first.get("cover_url"),
            }
        )
    # 可见性/归属不一致的文档单独告警，避免静默把别人的私有资料改成公开
    for doc in documents:
        parts = families[doc["base_title"]]
        attrs = {(p["user_id"], p["visibility"], p["category"]) for p in parts}
        if len(attrs) > 1:
            doc["mixed_attrs"] = sorted(attrs)
    return documents


async def _rebuild_knowledge(documents, chunk_max, chunk_overlap, apply_changes, encoders):
    from backend.src.utils.knowledge_base import _make_doc_id
    from backend.src.utils.file_processor import apply_context_prefix, chunk_text
    from backend.src.models.knowledgemodel import KnowledgeVector

    plan = []
    for doc in documents:
        if not doc["text"].strip():
            continue
        chunks = chunk_text(doc["text"], max_chars=chunk_max, overlap_chars=chunk_overlap)
        # 前缀只进向量、不进 content —— 见 file_processor.apply_context_prefix
        plan.append((doc, chunks, apply_context_prefix(chunks, chunk_overlap)))

    total_new = sum(len(c) for _, c, _ in plan)
    old_total = sum(d["old_count"] for d, _, _ in plan)
    print(f"  文档 {len(plan)} 篇；旧切片 {old_total} 片 → 新切片 {total_new} 片")
    if not apply_changes:
        return total_new

    flat = [text for _, _, encode_texts in plan for text in encode_texts]
    print(f"  开始编码 {total_new} 片（模型 {encoders['model_id']}）…")
    t0 = time.time()
    vectors = await encoders["encode_many"](flat)
    print(f"  编码完成，用时 {time.time() - t0:.1f}s")

    cursor = 0
    created = updated = removed = 0
    for doc, chunks, _ in plan:
        multi = len(chunks) > 1
        # 先用「新增/更新新切片、再删旧切片」的顺序：中途失败也不会出现文档整体消失
        new_ids = []
        for i, chunk in enumerate(chunks):
            title = f"{doc['base_title']} (第{i+1}部分)" if multi else doc["base_title"]
            doc_id = _make_doc_id(title, chunk)
            new_ids.append(doc_id)
            payload = {
                "title": title,
                "content": chunk,
                "embedding": encoders["codec"].pack(vectors[cursor + i]),
                "embedding_model": encoders["model_id"],
                "user_id": doc["user_id"],
                "visibility": doc["visibility"],
                "category": doc["category"],
            }
            existing = await KnowledgeVector.filter(doc_id=doc_id).first()
            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
                await existing.save()
                updated += 1
            else:
                await KnowledgeVector.create(doc_id=doc_id, cover_url=doc["cover_url"], **payload)
                created += 1
        cursor += len(chunks)
        stale = [d for d in doc["old_doc_ids"] if d not in new_ids]
        if stale:
            removed += await KnowledgeVector.filter(doc_id__in=stale).delete()

    print(f"  入库：新增 {created}、更新 {updated}、清理旧切片 {removed}")
    return total_new


async def _rebuild_memory(apply_changes, encoders):
    """记忆两张向量表：内容不动，只按新模型重算向量。"""
    from backend.src.models.memory_episode_model import MemoryEpisode
    from backend.src.models.memory_message_model import MemoryMessage

    episodes = [e for e in await MemoryEpisode.all() if (e.summary or "").strip()]
    messages = [m for m in await MemoryMessage.all() if (m.content or "").strip()]
    print(f"  情景记忆 {len(episodes)} 行、原文索引 {len(messages)} 行")
    if not apply_changes or not (episodes or messages):
        return len(episodes) + len(messages)

    texts = [e.summary[:500] for e in episodes] + [m.content[:500] for m in messages]
    t0 = time.time()
    vectors = await encoders["encode_many"](texts)
    print(f"  编码完成，用时 {time.time() - t0:.1f}s")

    cursor = 0
    for e in episodes:
        e.embedding = encoders["codec"].pack(vectors[cursor])
        e.embedding_model = encoders["model_id"]
        await e.save()
        cursor += 1
    for m in messages:
        m.embedding = encoders["codec"].pack(vectors[cursor])
        m.embedding_model = encoders["model_id"]
        await m.save()
        cursor += 1
    print(f"  已回写 {cursor} 行")
    return cursor


async def migrate(apply_changes: bool) -> None:
    from backend.src.models.knowledgemodel import KnowledgeVector
    from backend.src.utils.database import close_db, init_db
    from backend.src.utils.embeddings import chunk_sizes, codec, configured_model_id, encode_many

    await init_db()
    try:
        model_id = configured_model_id()
        chunk_max, chunk_overlap = chunk_sizes()
        print(f"目标模型：{model_id}；切片尺寸：max_chars={chunk_max}, overlap={chunk_overlap}")
        print(f"模式：{'执行' if apply_changes else '预演（不写库）'}\n")

        rows = await KnowledgeVector.all().values(
            "doc_id", "title", "content", "category", "visibility", "user_id", "cover_url"
        )
        documents = _collect_documents(rows)
        mixed = [d for d in documents if d.get("mixed_attrs")]
        if mixed:
            print("⚠ 以下文档的切片属性不一致，将以首个切片为准：")
            for d in mixed[:5]:
                print(f"    {d['base_title'][:40]} -> {d['mixed_attrs']}")

        # 这是离线长任务（几千片要跑十几分钟），进度条要留着 —— 服务端才关掉
        encoders = {
            "model_id": model_id,
            "encode_many": partial(encode_many, show_progress=True),
            "codec": codec,
        }
        print("【知识库】")
        await _rebuild_knowledge(documents, chunk_max, chunk_overlap, apply_changes, encoders)
        print("\n【记忆向量】")
        await _rebuild_memory(apply_changes, encoders)

        if not apply_changes:
            print("\n[预演] 未写入任何数据。加 --apply 执行。")
        else:
            print("\n迁移完成。")
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="换嵌入模型后重算全库向量", formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="真正写库；不加则只预演")
    args = parser.parse_args()
    asyncio.run(migrate(apply_changes=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
