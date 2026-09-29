"""嵌入能力（文本 → 向量）。

对外只暴露这几样，内部实现（谁加载、缓存放哪）不外泄：

    from backend.src.utils.embeddings import encode, encode_many, dimension, chunk_sizes

换模型 = 改 `EMBEDDING_MODEL_ID` + 跑 `backend/scripts/reembed_all.py --apply`，
不需要改任何调用方代码。
"""
from backend.src.utils.embeddings import codec
from backend.src.utils.embeddings.provider import (
    chunk_sizes,
    current_spec,
    dimension,
    encode,
    encode_many,
    get_model,
    is_loaded,
    local_model_dir,
)
from backend.src.utils.embeddings.registry import (
    EmbeddingModelSpec,
    configured_model_id,
    resolve,
)

__all__ = [
    "EmbeddingModelSpec",
    "chunk_sizes",
    "codec",
    "configured_model_id",
    "current_spec",
    "dimension",
    "encode",
    "encode_many",
    "get_model",
    "is_loaded",
    "local_model_dir",
    "resolve",
]
