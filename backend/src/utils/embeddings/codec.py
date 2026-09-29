"""向量在库里的存储格式。

`embedding` 列是 longtext，早期把向量存成 JSON 数组字符串。检索每次都要把全表向量
解一遍，实测这**就是**检索的主要开销（502 行 / 1024 维）：

    JSON text  json.loads + np.array   120 ms
    base64(float32)                    7 ms      ← 16.8x
    裸 float32 bytes                   0.7 ms    ← 需要 LONGBLOB，收益不足 2 倍不值得改 schema

点积本身只占 0.4 ms，所以瓶颈在解码不在扫描。选 base64：拿到绝大部分收益，
不动列类型、不引入跨进程缓存（多 worker 下没有一致性问题）。

**读取端兼容旧的 JSON 文本**（首字符是 `[` 就按 JSON 解）—— 迁移没覆盖到的行
不会变成"解析失败"被静默丢掉。
"""
from __future__ import annotations

import base64
import json

import numpy as np


def pack(vector) -> str:
    """ndarray / list[float] → 入库字符串。空向量返回空串。"""
    arr = np.asarray(vector, dtype=np.float32).ravel()
    if arr.size == 0:
        return ""
    return base64.b64encode(arr.tobytes()).decode("ascii")


def pack_many(vectors) -> list[str]:
    return [pack(v) for v in vectors]


def unpack(text: str | None) -> np.ndarray | None:
    """入库字符串 → 一维 float32 向量。

    拿不到向量时返回 None（调用方跳过该行），不抛异常：
    这条路径上任何一条坏数据都不该让整次检索失败。
    """
    if not text:
        return None
    try:
        if text[0] == "[":
            # 迁移前写入的 JSON 数组字符串
            arr = np.asarray(json.loads(text), dtype=np.float32)
        else:
            arr = np.frombuffer(base64.b64decode(text), dtype=np.float32)
    except Exception:
        return None
    if arr.size == 0:
        # 视频类资料就是空向量（见 knowledge_router 的视频上传分支）。
        # 返回空数组会让下面的维度校验把它误判成"模型不匹配"，所以这里直接当没有。
        return None
    return arr
