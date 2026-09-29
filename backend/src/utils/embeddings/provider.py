"""嵌入模型提供者：加载、编码、缓存。

**这个模块对数据库和智能体都无感知** —— 它只负责"文本进来、向量出去"。谁都能依赖它，
它不依赖谁。放 `utils/` 而不是 `ai_core/`，就是为了不让 service 层反过来依赖智能体层。
"""
import asyncio
import logging
import os
from pathlib import Path

from backend.src.utils.embeddings.registry import (
    EmbeddingModelSpec,
    configured_model_id,
    model_slug,
    resolve,
)

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[3]

# 国内镜像，避免直连 HuggingFace 超时
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
if HF_ENDPOINT:
    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)

_model = None
_model_lock = asyncio.Lock()


def model_root() -> Path:
    """模型权重根目录（每个模型一个子目录）。"""
    custom = (os.getenv("EMBEDDING_MODEL_DIR") or "").strip()
    return Path(custom) if custom else _BACKEND_ROOT / "embedding_models"


def local_model_dir(spec: EmbeddingModelSpec | None = None) -> Path:
    """某个模型的本地权重目录。"""
    return model_root() / model_slug((spec or current_spec()).id)


def current_spec() -> EmbeddingModelSpec:
    """当前配置的模型规格。"""
    return resolve(configured_model_id())


def is_loaded() -> bool:
    return _model is not None


async def get_model(spec: EmbeddingModelSpec | None = None):
    """取（必要时加载）模型单例。

    本地目录已存在就用本地的，否则按模型 id 从 HF 下载并保存到本地目录 ——
    这样容器/离线环境只需预置一次，之后不再依赖网络。
    """
    global _model
    if _model is not None:
        return _model

    spec = spec or current_spec()
    async with _model_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        local_path = local_model_dir(spec)
        try:
            if local_path.exists() and any(local_path.iterdir()):
                _model = await asyncio.to_thread(SentenceTransformer, str(local_path))
            else:
                logger.info("本地无 %s 权重，开始下载（首次较慢）", spec.id)
                _model = await asyncio.to_thread(SentenceTransformer, spec.id)
                local_path.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(_model.save, str(local_path))
        except Exception as exc:
            raise RuntimeError(
                f"嵌入模型 {spec.id} 加载失败：{exc}。"
                f"请检查网络或镜像（当前 HF_ENDPOINT={HF_ENDPOINT}），"
                f"或把权重预置到 {local_path}。"
            ) from exc

        actual = _model.get_sentence_embedding_dimension()
        if actual != spec.dimension:
            raise RuntimeError(
                f"嵌入模型 {spec.id} 实际维度 {actual} 与登记值 {spec.dimension} 不符，"
                f"请修正 embeddings/registry.EMBEDDING_MODELS 里的 dimension。"
            )
        logger.info("嵌入模型就绪：%s（%d 维，窗口 %d token）", spec.id, actual, _model.max_seq_length)
        return _model


def dimension() -> int:
    """当前模型的向量维度。"""
    return current_spec().dimension


def chunk_sizes() -> tuple[int, int]:
    """当前模型对应的入库切片尺寸 (max_chars, overlap_chars)。"""
    spec = current_spec()
    return spec.chunk_max_chars, spec.chunk_overlap_chars


async def encode(text: str):
    """编码单条文本为归一化向量（Redis 缓存 + 线程池）。

    缓存键**必须带模型标识**：否则换模型后旧缓存仍会命中，返回上一代模型的向量，
    维度对不上就会被检索层当垃圾丢掉，表现为"知识库突然空了"。
    """
    import numpy as np

    cache_key = None
    if text and len(text.strip()) > 2:
        try:
            from backend.src.utils.constants import EMBED_CACHE_TTL
            from backend.src.utils.redis_client import _cache_key, _text_hash, cache_get

            cache_key = _cache_key("embed", current_spec().id, _text_hash(text.strip()))
            cached = await cache_get(cache_key)
            if cached is not None and isinstance(cached, list):
                vec = np.array(cached, dtype=np.float32)
                if vec.shape == (dimension(),):
                    return vec
                logger.warning("嵌入缓存维度不符（%s），已忽略并按当前模型重算", vec.shape)
        except Exception:
            logger.debug("嵌入缓存读取失败，按未命中处理", exc_info=True)

    model = await get_model()
    # 关掉 tqdm 进度条。这是服务端：一次检索、一条入库都会调到这里，
    # 而 sentence-transformers 在 INFO 级别下每次调用都打一条 "Batches: 100%|…| 1/1"，
    # 日志里看着像死循环（上传一份文档 = 切片数那么多条，一次检索也要一条）。
    vector = await asyncio.to_thread(
        model.encode, text, normalize_embeddings=True, show_progress_bar=False
    )

    if cache_key:
        try:
            from backend.src.utils.constants import EMBED_CACHE_TTL
            from backend.src.utils.redis_client import cache_set

            await cache_set(cache_key, vector.tolist(), EMBED_CACHE_TTL)
        except Exception:
            logger.debug("嵌入缓存写入失败", exc_info=True)

    return vector


async def encode_many(texts: list[str], show_progress: bool = False):
    """批量编码，返回已归一化的向量矩阵（点积即余弦相似度）。

    **一次调用编码一整批**，比逐条 `encode()` 快得多（逐条每次都要重新组 batch、
    跑一遍前向，CPU 上开销全摊在单条上）。上传文档、重算全库向量都该走这里。

    不走 Redis 缓存：调用方多是给一批文本即时打分，缓存命中率低，
    而且缓存键按整批算，改一条就整批失效。

    show_progress 默认关 —— 服务端不该往 stderr 刷进度条；离线长任务
    （如 `scripts/reembed_all.py`，一次几千片要跑十几分钟）想看进度就传 True。
    """
    import numpy as np

    cleaned = [str(t or "").strip() or " " for t in texts]
    if not cleaned:
        return np.zeros((0, 0), dtype=np.float32)
    model = await get_model()
    return await asyncio.to_thread(
        model.encode, cleaned, normalize_embeddings=True, show_progress_bar=show_progress
    )
