"""
知识库 — 向量数据存储于 MySQL，支持用户隔离和公开/私有权限

嵌入能力（模型加载、编码、向量缓存）已抽到 `utils/embeddings`，本文件只保留知识库
自己的业务：检索、入库、CRUD、展示分组。换模型改 `EMBEDDING_MODEL_ID` 即可，不用动这里。
"""
import os
import hashlib
import asyncio
import logging

from tortoise.expressions import Q

from backend.src.models.knowledgemodel import KnowledgeVector
from backend.src.utils.embeddings import codec, current_spec
from backend.src.utils.embeddings import encode as _encode_text

# 对外再导出：`service/video/service.py` 和 `tests/test_video_service.py` 都按
# "backend.src.utils.knowledge_base.encode_many" 这个名字路径引用它，别改名也别移走。
from backend.src.utils.embeddings import encode_many as encode_many  # noqa: F401

logger = logging.getLogger(__name__)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_RAG_SEARCH_SEM = asyncio.Semaphore(max(1, _int_env("RAG_GLOBAL_SEARCH_CONCURRENCY", 20)))


def _make_doc_id(title: str, content: str, scope: str = "") -> str:
    """
    生成资料唯一 ID。

    早期版本只取正文前 100 个字符，容易让前缀相似的资料互相撞车，
    导致“明明是新资料，却被当成重复跳过”。
    这里改为“标题 + 全文内容哈希 + 作用域”的组合。
    """
    normalized_title = (title or "").strip()
    normalized_content = " ".join((content or "").split())
    content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    raw = f"{scope}|{normalized_title}|{content_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def _encode_async(text: str):
    """编码单条文本为归一化向量。

    实现已移到 `utils/embeddings` —— 模型生命周期不该由知识库业务持有。
    保留这个名字是因为 `service/memory/embedding.py` 按它引用。
    """
    return await _encode_text(text)


_last_mismatch_signature = None


def _report_embedding_mismatch(mismatched: int, total: int, stale_models: set[str]) -> None:
    """向量与当前模型不匹配时**大声报错**，不再静默跳过。

    静默跳过的表现是「检索一直返回『暂无相关内容』」—— 看起来像"知识库是空的"，
    不像"配置错了"，排查时会往数据方向找很久。这里直接说清是什么、怎么修，
    并带上这些行自报的 `embedding_model`，省掉一次倒查。

    同一批不匹配只报一次，避免每篇 PPT 触发十几次检索把日志刷爆。
    """
    global _last_mismatch_signature
    import os

    model_id = os.getenv("EMBEDDING_MODEL_ID") or current_spec().id
    stale = "/".join(sorted(stale_models)) or "未知"
    signature = (model_id, mismatched, total, stale)
    if signature == _last_mismatch_signature:
        return
    _last_mismatch_signature = signature
    logger.error(
        "知识库 %d/%d 条向量的维度与当前嵌入模型 %s 不符，已跳过这些条目"
        "（这些行记录的生成模型是 %s）。"
        "这通常是换过模型却没重算向量 —— 请运行 "
        "`python backend/scripts/reembed_all.py --apply`，"
        "或把 EMBEDDING_MODEL_ID 改回生成这批向量的那个模型。",
        mismatched, total, model_id, stale,
    )


async def search(query: str, top_k: int = 5, user_id: int = None, category: str = None) -> str:
    async with _RAG_SEARCH_SEM:
        return await _search_inner(query, top_k=top_k, user_id=user_id, category=category)


async def _search_inner(query: str, top_k: int = 5, user_id: int = None, category: str = None) -> str:
    """
    从知识库检索资料。
    - user_id 为空：只查公开资料
    - user_id 不为空：查公开资料 + 该用户自己的私有资料
    - category: 限定分类，如 "exercise" / "textbook"
    """
    try:
        import numpy as np
        query_vec = await _encode_async(query)
        min_score = _float_env("RAG_MIN_SCORE", 0.0)
        max_chars = _int_env("RAG_RESULT_MAX_CHARS", 1200)

        if user_id:
            qs = KnowledgeVector.filter(Q(visibility="public") | Q(user_id=user_id, visibility="private"))
        else:
            qs = KnowledgeVector.filter(visibility="public")

        if category:
            qs = qs.filter(category=category)

        records = await qs.values(
            "doc_id", "title", "content", "category", "embedding", "embedding_model"
        )

        if not records:
            return "知识库中暂无相关内容"

        # 先把全表向量解出来、滤掉维度不符的，再**一次矩阵乘**算完所有相似度。
        # 逐行 np.dot 看着自然，但这里 99% 的时间花在解码而不是点积上（实测
        # 502×1024：解码 120ms、点积 0.4ms），所以解码格式和批量化才是重点。
        query_dim = query_vec.shape[0]
        vectors, metas = [], []
        mismatched = 0
        stale_models: set[str] = set()
        for r in records:
            vec = codec.unpack(r.get("embedding"))
            if vec is None:
                continue
            if vec.shape[0] != query_dim:
                mismatched += 1
                stale_models.add(r.get("embedding_model") or "未知")
                continue
            vectors.append(vec)
            metas.append(r)

        if mismatched:
            _report_embedding_mismatch(mismatched, len(records), stale_models)

        if not vectors:
            return "知识库中暂无相关内容"

        similarities = np.vstack(vectors) @ query_vec
        scored = [
            (
                float(similarities[i]),
                metas[i].get("doc_id", ""),
                metas[i]["title"],
                metas[i]["content"],
                metas[i].get("category", ""),
            )
            for i in range(len(metas))
            if similarities[i] >= min_score
        ]

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return "知识库中暂无相关内容"

        items = [
            (
                f"【资料{i+1}】来源：{title}（{cat}，score={sim:.3f}，doc_id={doc_id}）\n"
                f"{str(content or '')[:max_chars]}\n"
            )
            for i, (sim, doc_id, title, content, cat) in enumerate(scored[:top_k])
        ]
        return "\n".join(items)

    except Exception as e:
        return f"知识库检索失败：{e}"


async def ingest(
    title: str,
    content: str,
    user_id: int = None,
    visibility: str = "private",
    category: str = "knowledge_point",
    cover_url: str | None = None,
    vector=None,
) -> str:
    """
    向知识库添加一条资料。
    - user_id=None: 系统上传（需管理员权限）
    - visibility='public': 全员可见; 'private': 仅上传者可见
    - category: 见 KB_CATEGORIES
    - cover_url: 可选封面图 URL，不传则按 category 使用默认封面
    - vector: 可选，**调用方已经算好的向量**。批量上传时应当先把整篇文档的切片
      用 `encode_many` 一次编码好再逐条入库 —— 这里每条单独编码的话，切片数就是
      模型调用次数，CPU 上慢得多（还要每条一次 Redis 往返）。不传则按 content 现算。

      注意：带跨片上下文前缀的文本只用于编码（见 `apply_context_prefix`），
      它拼出来的向量从这里传进来，`content` 本身始终按原样入库。
    """
    try:
        if len(content.strip()) < 50:
            return "内容过短（<50字），未入库"

        doc_id = _make_doc_id(title, content)
        if vector is None:
            vector = await _encode_async(content)

        existing = await KnowledgeVector.filter(doc_id=doc_id).first()
        if existing:
            same_owner = existing.user_id == user_id
            same_system_scope = existing.user_id is None and user_id is None
            globally_reusable = existing.visibility == "public" and visibility == "public"
            if not (same_owner or same_system_scope or globally_reusable):
                doc_id = _make_doc_id(title, content, scope=f"user:{user_id or 'system'}:{visibility}")
                existing = await KnowledgeVector.filter(doc_id=doc_id).first()

        if existing:
            updated = False
            was_rejected = existing.visibility == "rejected"

            if visibility == "pending" and existing.visibility in {"pending", "rejected"}:
                if existing.visibility != "pending":
                    existing.visibility = "pending"
                    updated = True
                if title and title != existing.title:
                    existing.title = title
                    updated = True
                if user_id is not None and existing.user_id != user_id:
                    existing.user_id = user_id
                    updated = True
                if category != existing.category:
                    existing.category = category
                    updated = True
                if cover_url and cover_url != existing.cover_url:
                    existing.cover_url = cover_url
                    updated = True

                old_content = existing.content or ""
                new_content = content or ""
                if new_content != old_content and len(new_content.strip()) >= len(old_content.strip()):
                    existing.content = new_content
                    existing.embedding = codec.pack(vector)
                    existing.embedding_model = current_spec().id
                    updated = True

                if updated:
                    await existing.save()
                    if was_rejected:
                        return f"「{title}」已重新提交审核（{len(content)}字，待审核，{category}）"
                    return f"「{title}」已更新待审核内容（{len(content)}字，{category}）"
                return f"「{title}」已存在，仍在待审核"

            if existing.visibility == "private" and visibility in {"public", "pending"}:
                existing.visibility = visibility
                updated = True
            if existing.user_id is None and user_id is not None and existing.visibility != "public":
                existing.user_id = user_id
                updated = True
            if category != existing.category:
                existing.category = category
                updated = True
            if updated:
                await existing.save()
                return f"「{title}」已存在，已更新权限"
            return f"「{title}」已存在，跳过"

        if not cover_url:
            category_cover_map = {
                "knowledge_point": "document",
                "exercise": "exercise",
                "textbook": "document",
                "note": "document",
                "case_study": "document",
                "reference": "document",
            }
            cover_url = f"/static/covers/default_{category_cover_map.get(category, '')}.svg"

        await KnowledgeVector.create(
            doc_id=doc_id,
            title=title,
            content=content,
            embedding=codec.pack(vector),
            embedding_model=current_spec().id,
            user_id=user_id,
            visibility=visibility,
            category=category,
            cover_url=cover_url,
        )
        label = "公开" if visibility == "public" else "待审核" if visibility == "pending" else "私有"
        return f"「{title}」已入库（{len(content)}字，{label}，{category}）"

    except Exception as e:
        return f"入库失败：{e}"


async def list_all(user_id: int = None, visibility: str = None) -> list[dict]:
    """
    列出知识库条目（原始切片）。
    - user_id: 过滤上传者（可选）
    - visibility: 过滤可见性（可选）
    """
    qs = KnowledgeVector.all()
    if user_id:
        qs = qs.filter(Q(visibility="public") | Q(user_id=user_id))
    if visibility:
        qs = qs.filter(visibility=visibility)

    records = await qs.order_by("-created_at").values(
        "doc_id", "title", "content", "category", "user_id", "visibility", "cover_url", "created_at"
    )
    return list(records)


def _merge_overlapped_chunks(chunks: list[str]) -> str:
    parts = [str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()]
    if not parts:
        return ""

    merged = parts[0]
    for chunk in parts[1:]:
        max_overlap = min(220, len(merged), len(chunk))
        overlap = 0
        for size in range(max_overlap, 39, -1):
            if merged.endswith(chunk[:size]):
                overlap = size
                break
        merged = f"{merged}{chunk[overlap:]}" if overlap else f"{merged}\n\n{chunk}"
    return merged


async def list_grouped(user_id: int = None, visibility: str = None) -> list[dict]:
    """
    按原始文档分组展示，合并切片避免前端展示混乱。
    切片标题格式: "文档名 (第N部分)" → 按 "文档名" 合并
    """
    import re

    qs = KnowledgeVector.all()
    if user_id:
        qs = qs.filter(Q(visibility="public") | Q(user_id=user_id))
    if visibility:
        qs = qs.filter(visibility=visibility)

    records = await qs.order_by("-created_at").values(
        "doc_id", "title", "content", "category", "user_id", "visibility", "cover_url", "created_at"
    )

    def _chunk_index(title: str) -> int:
        match = re.search(r"[（(]第(\d+)部分[）)]", title or "")
        return int(match.group(1)) if match else 1

    groups: dict[str, dict] = {}
    for r in records:
        title = r["title"]
        base = re.sub(r"\s*（第\d+部分）\s*", "", title)
        base = re.sub(r"\s*\(第\d+部分\)\s*", "", base)

        if base not in groups:
            groups[base] = {
                "title": base,
                "category": r.get("category", "knowledge_point"),
                "doc_id": r["doc_id"],
                "doc_ids": [],
                "_parts": [],
                "chunks": 0,
                "total_chars": 0,
                "preview": r["content"][:200],
                "content": "",
                "visibility": r["visibility"],
                "uploader_id": r["user_id"],
                "cover_url": r.get("cover_url"),
                "created_at": str(r["created_at"]),
            }
        groups[base]["_parts"].append({
            "index": _chunk_index(title),
            "doc_id": r["doc_id"],
            "content": r["content"],
        })
        groups[base]["chunks"] += 1
        groups[base]["total_chars"] += len(r["content"])
        if str(r["created_at"]) < groups[base]["created_at"]:
            groups[base]["created_at"] = str(r["created_at"])

    result = []
    for group in groups.values():
        parts = sorted(group.pop("_parts", []), key=lambda item: item["index"])
        group["doc_ids"] = [item["doc_id"] for item in parts]
        group["content"] = _merge_overlapped_chunks([item["content"] for item in parts])
        if group["doc_ids"]:
            group["doc_id"] = group["doc_ids"][0]
        result.append(group)

    return sorted(result, key=lambda x: x["created_at"], reverse=True)


async def get_by_id(doc_id: str, user_id: int | None = None, is_admin: bool = False) -> dict | None:
    """根据 doc_id 获取单条知识库记录"""
    query = KnowledgeVector.filter(doc_id=doc_id)
    if not is_admin:
        query = query.filter(Q(visibility="public") | Q(user_id=user_id))
    record = await query.values(
        "doc_id", "title", "content", "category", "user_id", "visibility", "cover_url", "created_at"
    ).first()
    return record


async def update(
    doc_id: str,
    title: str = None,
    content: str = None,
    visibility: str = None,
    user_id: int = None,
    is_admin: bool = False,
) -> str:
    """
    更新知识库条目。
    - 仅 owner 或 admin 可操作
    - content 变更会自动重新嵌入向量
    """
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id).first()
        if not record:
            return "记录不存在"

        # ── 权限：仅 owner 或 admin ──
        if record.user_id is not None and record.user_id != user_id and not is_admin:
            return "无权修改他人私有资料"

        # ── 系统资料仅 admin ──
        if record.user_id is None and not is_admin:
            return "无权修改系统公开资料"

        if title is not None:
            record.title = title
        if visibility is not None:
            record.visibility = visibility

        # 内容变更 → 重新嵌入
        if content is not None:
            if len(content.strip()) < 50:
                return "内容过短（<50字），更新失败"
            new_doc_id = _make_doc_id(title or record.title, content, scope=f"user:{user_id or 'system'}")
            vector = await _encode_async(content)
            record.doc_id = new_doc_id
            record.content = content
            record.embedding = codec.pack(vector)
            record.embedding_model = current_spec().id

        await record.save()
        return f"「{record.title}」已更新"
    except Exception as e:
        return f"更新失败：{e}"


async def delete(doc_id: str, user_id: int = None, is_admin: bool = False) -> str:
    """
    删除知识库条目。
    - 仅 owner 或 admin 可操作
    """
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id).first()
        if not record:
            return "记录不存在"

        if record.user_id is not None and record.user_id != user_id and not is_admin:
            return "无权删除他人私有资料"
        if record.user_id is None and not is_admin:
            return "无权删除系统公开资料"

        title = record.title
        await record.delete()
        return f"「{title}」已删除"
    except Exception as e:
        return f"删除失败：{e}"
