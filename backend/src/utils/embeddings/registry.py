"""嵌入模型注册表。

支持的模型在这里登记规格。切换模型只需改环境变量 `EMBEDDING_MODEL_ID`，不用动代码；
要引入一个没登记过的模型，就在这里加一条规格（必须显式给出维度和切片尺寸，
因为库里每一行向量都要靠它们判断是否匹配，猜不得）。

**切片尺寸为什么跟模型绑在一起**：它是从该模型 tokenizer 的 token/字符比例反推的。
沿用别的模型的尺寸会导致两种坏结果——超出窗口被静默截断（检索永远看不到那部分内容），
或者切得过碎丢掉上下文。所以尺寸必须随模型一起换。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """一个嵌入模型的规格。"""

    id: str
    """模型的标识，同时也是 HuggingFace 仓库名与写进数据库的 `embedding_model` 值。"""

    dimension: int
    """向量维度。库里已有向量的维度与它不符时，说明是别的模型生成的。"""

    max_tokens: int
    """模型窗口（token）。切片尺寸不能超过它。"""

    chunk_max_chars: int
    """入库切片的正文上限（字符），按本模型 tokenizer 实测反推。"""

    chunk_overlap_chars: int
    """相邻切片的上下文携带量（字符），见 file_processor.apply_context_prefix。"""

    note: str = ""


EMBEDDING_MODELS: dict[str, EmbeddingModelSpec] = {
    "BAAI/bge-m3": EmbeddingModelSpec(
        id="BAAI/bge-m3",
        dimension=1024,
        max_tokens=8192,
        chunk_max_chars=700,
        chunk_overlap_chars=80,
        note=(
            "中文/多语检索模型，窗口 8192 token。实测本库语料上 tokenizer 为 "
            "XLMRobertaTokenizer、token/字符 = 0.508；700 字 ≈ 333 token、最长实测 552，"
            "落在业界推荐的 400~512 token 带附近。重叠 80 字 ≈ 11%，也在推荐区间内。"
        ),
    ),
}

DEFAULT_MODEL_ID = "BAAI/bge-m3"


def configured_model_id() -> str:
    """当前配置的模型 id（环境变量优先，缺省用默认模型）。"""
    import os

    return (os.getenv("EMBEDDING_MODEL_ID") or "").strip() or DEFAULT_MODEL_ID


def resolve(model_id: str | None = None) -> EmbeddingModelSpec:
    """取模型规格。

    未知模型**直接报错**，不悄悄退回默认值 —— 一旦退回，库里存的就是 A 模型的向量、
    查询用的却是 B 模型，检索只会返回空，排查时极难定位。宁可起不来也要报清楚。
    """
    key = (model_id or "").strip() or configured_model_id()
    spec = EMBEDDING_MODELS.get(key)
    if spec is None:
        known = "、".join(sorted(EMBEDDING_MODELS))
        raise ValueError(
            f"未登记的嵌入模型 {key!r}。请改用已登记的模型（{known}），"
            f"或在 embeddings/registry.EMBEDDING_MODELS 里登记它的 dimension 和切片尺寸。"
        )
    return spec


def model_slug(model_id: str) -> str:
    """把模型 id 变成安全的目录名：`BAAI/bge-m3` → `BAAI__bge-m3`。

    按模型分目录是为了让多个模型的权重共存 —— 换模型不覆盖旧的，回滚时不用重新下载。
    """
    return model_id.replace("/", "__")
