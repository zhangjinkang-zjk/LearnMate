"""Unified helpers for parsing JSON returned by LLMs."""

import json
import logging

logger = logging.getLogger(__name__)


def _strip_code_fence(content: str) -> str:
    content = str(content or "").strip().lstrip("\ufeff")
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_candidate(content: str) -> str:
    starts = [idx for idx in (content.find("["), content.find("{")) if idx >= 0]
    if not starts:
        return content

    start = min(starts)
    opener = content[start]
    closer = "]" if opener == "[" else "}"
    end = content.rfind(closer)
    if end > start:
        return content[start:end + 1].strip()
    return content[start:].strip()


# JSON 字符串里合法的单字符转义。**不在这张表里的反斜杠都是模型写坏的** ——
# 实测来源是中文排版习惯：写范围时会在波浪号前加一个反斜杠（`1.5\~2.18`），
# 而 `\~` 不是合法 JSON 转义。
_JSON_ESCAPES = '"\\/bfnrt'
_HEX_DIGITS = "0123456789abcdefABCDEF"


def _has_four_hex_digits(content: str, start: int) -> bool:
    digits = content[start:start + 4]
    return len(digits) == 4 and all(char in _HEX_DIGITS for char in digits)


def _repair_invalid_escapes(content: str) -> str:
    """把字符串里不合法的反斜杠转义补成合法写法（再补一个反斜杠，即按**字面量**解析）。

    补成 `\\\\~` 而不是直接删掉那个反斜杠，是因为删了会改内容：模型写 `"\\d+"`（正则）时
    那个反斜杠是有意义的，`\\~` 补成字面量顶多在正文里多出一个反斜杠，删掉却会把正则改坏。
    **只修编码这一层，不猜内容。**

    只动**字符串内部**的反斜杠，且只动不合法的那些：`\\"` `\\\\` `\\n` 原样留着，
    `\\uXXXX` 也只在四个十六进制位齐全时才认（缺位的那种同样按字面量处理）。
    """
    out: list[str] = []
    index = 0
    length = len(content)
    in_string = False
    while index < length:
        char = content[index]
        if char == '"':
            in_string = not in_string
            out.append(char)
            index += 1
        elif char != "\\" or not in_string:
            out.append(char)
            index += 1
        elif content[index + 1:index + 2] in _JSON_ESCAPES:
            # 合法转义：连它后面那个字符一起原样收下
            out.append(content[index:index + 2])
            index += 2
        elif content[index + 1:index + 2] == "u" and _has_four_hex_digits(content, index + 2):
            out.append(content[index:index + 6])
            index += 6
        else:
            out.append("\\\\")
            index += 1
    return "".join(out)


def _loads_lenient(content: str):
    try:
        return json.loads(content)
    except json.JSONDecodeError as strict_error:
        try:
            return json.loads(content, strict=False)
        except json.JSONDecodeError:
            pass
        # `strict=False` 只放过裸控制字符，救不了非法转义（那两种是**不同**的错）。
        # 少了这一层，一次 `\\~` 就让整条回复作废：路径审核和 PPT 审核都是 except 之后
        # "故障放行"，于是审核静默地一次都没跑过，而链路上只留下一行 WARNING。
        try:
            return json.loads(_repair_invalid_escapes(content), strict=False)
        except json.JSONDecodeError:
            # 抛**最初**那个错：报错位置对应模型原文，补过转义的那份对不上。
            raise strict_error


def parse_llm_json(text: str) -> dict | list:
    """Parse JSON from an LLM response.

    The parser accepts fenced markdown JSON, responses with short prose around
    the JSON payload, raw control characters inside strings, and invalid
    backslash escapes inside strings. The first case commonly appears in
    generated exercises when an explanation contains an unescaped newline;
    the second when a Chinese range like `1.5~2.18` is written as `1.5\\~2.18`.
    """
    content = _strip_code_fence(text)
    candidates = [content]
    extracted = _extract_json_candidate(content)
    if extracted and extracted != content:
        candidates.append(extracted)

    last_error = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return _loads_lenient(candidate)
        except json.JSONDecodeError as error:
            last_error = error

    logger.warning("LLM JSON 解析失败，原始响应前200字符: %s", str(text or "")[:200])
    if last_error:
        raise last_error
    raise json.JSONDecodeError("Empty JSON content", content, 0)
