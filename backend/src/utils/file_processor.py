"""
文档文本提取 + 智能切片
支持 .txt / .md / .csv / .json / .pdf / .docx
"""
from pathlib import Path
import re


# ── 文本提取 ──

def extract_text(file_path: str | Path) -> str:
    """根据文件后缀提取文本内容"""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".csv"}:
        return path.read_text("utf-8", errors="replace")

    elif suffix == ".json":
        return _extract_json(path)

    elif suffix == ".pdf":
        return _extract_pdf(path)

    elif suffix == ".docx":
        return _extract_docx(path)

    else:
        raise ValueError(f"不支持的文件格式: {suffix}（仅支持 .txt .md .csv .json .pdf .docx）")


def _extract_json(path: Path) -> str:
    import json

    raw = path.read_text("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    return json.dumps(data, ensure_ascii=False, indent=2)


def _extract_pdf(path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text as pdf_extract
    except ImportError:
        raise ImportError("请安装 pdfminer.six：pip install pdfminer.six")

    return pdf_extract(str(path))


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ImportError("请安装 python-docx：pip install python-docx")

    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


# ── 文本切片 ──

# 这里的默认值只是"通用兜底"，真正入库用的尺寸由嵌入模型决定 ——
# 每个模型的窗口和 tokenizer 比例不同，尺寸必须跟着模型走，具体值登记在
# `utils/embeddings/registry.py` 的 EMBEDDING_MODELS 里（含每个值的实测来源）。
# 知识库入库路径应当显式传入 provider 的尺寸，例如：
#     max_chars, overlap_chars = chunk_sizes()
#     chunks = chunk_text(raw_text, max_chars=max_chars, overlap_chars=overlap_chars)
# 本函数刻意不认识嵌入模型，保持成一个纯粹的文本工具。
KB_CHUNK_MAX_CHARS = 700
KB_CHUNK_OVERLAP_CHARS = 80

# 跨片上下文前缀的标记。**它只应该出现在送去编码的文本里**，
# 不该出现在入库的 content 里 —— 见 apply_context_prefix 的说明。
CONTEXT_PREFIX = "上文摘要："


def chunk_text(
    text: str,
    max_chars: int = KB_CHUNK_MAX_CHARS,
    overlap_chars: int = KB_CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """
    将长文本按语义段落切分成块。**返回的是干净正文**，不带跨片上下文前缀。

    策略：保留标题路径，按段落聚合，长段落按句子切分；超长段落内部按 overlap_chars
    做字符级滑动窗口（那部分是真重叠，不是前缀注入）。

    尺寸请由调用方按当前嵌入模型给出（见模块注释），不要依赖这里的默认值。

    跨片上下文请单独用 `apply_context_prefix()` 生成 —— 那个结果只用于编码。
    """
    paragraphs = _paragraphs_with_heading_path(text)
    chunks = []
    current = ""

    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for sub in _split_long_paragraph(para, max_chars, overlap_chars):
                chunks.append(sub)
            continue

        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para

    if current:
        chunks.append(current)

    return chunks or [text]


def apply_context_prefix(chunks: list[str], overlap_chars: int) -> list[str]:
    """给每片拼上「上一片尾部」作前缀 —— **仅供编码使用，不要入库**。

    跨片上下文只对向量有意义：它把相邻切片在语义空间里拉近，让它们能互相召回。
    但对读的人（知识库页面、喂给模型的提示词）是纯噪音。

    以前这个前缀是直接拼进 `content` 再入库的，后果是每段正文开头都带着
    「上文摘要：…」，页面上看得见、提示词里也带着。所以现在拆开：
    `content` 存干净正文，前缀在送编码前才拼。
    """
    if overlap_chars <= 0 or len(chunks) <= 1:
        return list(chunks)

    prefixed = [chunks[0]]
    for idx in range(1, len(chunks)):
        prev_tail = chunks[idx - 1][-overlap_chars:].strip()
        current = chunks[idx]
        if prev_tail and prev_tail not in current[: overlap_chars * 2]:
            current = f"{CONTEXT_PREFIX}{prev_tail}\n{current}"
        prefixed.append(current)
    return prefixed


def _paragraphs_with_heading_path(text: str) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", str(text or ""))
    raw_parts = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    heading_path: list[str] = []
    parts: list[str] = []

    for part in raw_parts:
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        if not lines:
            continue

        first = lines[0]
        heading = _parse_heading(first)
        if heading:
            level, title = heading
            heading_path = heading_path[: max(0, level - 1)]
            heading_path.append(title)
            body = "\n".join(lines[1:]).strip()
            if not body:
                # 只有标题行、没有正文的段落 —— 把切片拼回全文时，切片边界会变成
                # 段落边界，边界正好落在某行前面时这一行就成了"光杆标题"。
                # 不能 continue：那会把整行丢掉（实测每轮迁移丢掉 0.16% 的句子）。
                # 也不拿它当标题正文 —— 原样保留，避免和路径里的同名标题重复。
                parts.append(part)
                continue
            part = body

        if heading_path:
            parts.append(f"标题路径：{' > '.join(heading_path)}\n{part}")
        else:
            parts.append(part)

    return parts


def _parse_heading(line: str) -> tuple[int, str] | None:
    markdown = re.match(r"^(#{1,6})\s+(.+)$", line)
    if markdown:
        return len(markdown.group(1)), markdown.group(2).strip()

    chapter = re.match(r"^第[一二三四五六七八九十百千万\d]+[章节篇讲课]\s*[：:、.]?\s*(.+)$", line)
    if chapter:
        return 1, line.strip()

    numbered = re.match(r"^(\d+(?:\.\d+){0,4})[、.)．]\s*(.+)$", line)
    if numbered:
        return min(numbered.group(1).count(".") + 1, 6), line.strip()

    cn_numbered = re.match(r"^[一二三四五六七八九十]+[、.．]\s*(.+)$", line)
    if cn_numbered and len(line) <= 40:
        return 2, line.strip()

    return None


def _split_long_paragraph(text: str, max_chars: int, overlap_chars: int = 150) -> list[str]:
    """按句号、问号、叹号、分号、换行切割超长段落。

    **句子之间原样的空白要留着。** 这个函数原来是 `sent.strip()` 之后 `current += sent`：
    英文的 `"...end. Next..."` 会粘成 `"end.Next"`，段落内的单个换行也被吞掉（两行并成
    一行）。切分点用的是 lookbehind，分隔符本来就在上一句末尾 —— 别 strip 就没有这个问题。
    只在**块的边界**上去空白（那是切分产生的，不是原文里的）。

    长度按原样算（原来那个 `+1` 是给一个从来没被加进去的分隔符留的位置）。
    """
    sentences = re.split(r"(?<=[。！？!?；;\n])", text)
    chunks = []
    current = ""

    for sent in sentences:
        if not sent.strip():
            continue
        if len(current) + len(sent) <= max_chars:
            current += sent
        else:
            if current:
                chunks.append(current.strip())
            if len(sent.strip()) > max_chars:
                chunks.extend(_hard_split(sent, max_chars, overlap_chars))
                current = ""
            else:
                current = sent

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _hard_split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    step = max(1, max_chars - max(0, overlap_chars))
    return [text[start:start + max_chars].strip() for start in range(0, len(text), step) if text[start:start + max_chars].strip()]
