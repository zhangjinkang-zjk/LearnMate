# -*- coding: utf-8 -*-
"""评估产物的命名：**按内容命名**，撞名加序号（不再用时间戳）。

为什么换掉时间戳：`20261002-213348-task-eval.md` 这种名字，除了"什么时候跑的"什么
都读不出来 —— 打开之前不知道它是哪份评估、跑了几个学习者、什么主题。内容名先把
"这是什么"写在脸上。

**为什么还留一个序号**：有两组文件的内容是真的分不开 —— 同一个假学生跑第二次的
journey、同样是「ppt / 请求 1 份」的两次 resource-eval。名字里不含任何区分信息时，
序号是唯一诚实的区分方式，它也表示"同一件事的第 N 次"。

两处依赖关系跟着一起改了（换命名最容易踩的地方）：
    - `claim_audit` 找"最新那份资料生成评估"本来是 glob `*-resource-eval.json`，
      新名字不再以它结尾，已改成按前缀 glob。
    - `persona_eval` 找"上一次"本来是 `sorted(glob("*.json"))[-1]` —— 时间戳下字典序
      恰好等于时间序，换名字后不再成立（`-10` 会排在 `-2` 前面），已改成按 mtime。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "eval" / "results"

_ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')
_DASHES = re.compile(r"-{2,}")


# ── 中英对照 ──
# 文件名里往外露的那些 id（场景名、学习者 key、资源类型）都是代码里的英文标识，
# 翻译只发生在**呈现层**：这是一张纯查表，代码里的 id 一个都不动。
# 新加了场景/类型却忘了登记，就会原样落英文 —— `cn()` 故意不报错，宁可名字难看，
# 也不要在评估跑完的那一刻抛异常把结果丢掉。
TERMS = {
    # 资源类型
    "document": "文档",
    "ppt": "课件",
    "mindmap": "脑图",
    # 学习者
    "agent-dev": "智能体开发",
    "algo": "算法",
    # 假学生
    "doc-only": "只看文档",
    "shaky": "半懂",
    # 教练评估的场景
    "skip-to-stack": "跳过做什么",
    "framework-not-in-registry": "要没登记的框架",
    "doc-not-visible": "方案文件不在快照里",
}


def cn(term: str) -> str:
    """把代码里的英文 id 换成中文说法；没登记的返回原样。"""
    return TERMS.get(str(term), str(term))


def slug(text: str, fallback: str = "run", max_len: int = 60) -> str:
    """把一段描述压成能进文件名的片段（路径非法字符和空白都换成 `-`）。"""
    cleaned = _DASHES.sub("-", _ILLEGAL.sub("-", str(text or "").strip())).strip("-")
    return (cleaned or fallback)[:max_len]


def next_stem(kind: str, *parts: str) -> str:
    """`{kind}-{parts...}-{n}`，n 从 1 起；这个 stem 已被占用就取下一个。

    "被占用"不只看 `.md`/`.json` 本身，还看 `{stem}-*` 这样的派生物
    （`persona_eval` 写的是 `{stem}-对话原文.md`）—— 漏了它，第二次跑会算出同一个
    stem，把上一次的 json 覆盖掉。
    """
    base = "-".join([slug(kind)] + [slug(p) for p in parts if p])
    n = 1
    while (any((RESULTS_DIR / f"{base}-{n}{ext}").exists() for ext in (".md", ".json"))
           or next(iter(RESULTS_DIR.glob(f"{base}-{n}-*")), None) is not None):
        n += 1
    return f"{base}-{n}"


def kind_glob(kind: str, ext: str) -> str:
    """找**同一种**产物用的 glob（不含序号，交给 `sorted(key=mtime)` 去排序）。"""
    return f"{slug(kind)}-*{ext}"
