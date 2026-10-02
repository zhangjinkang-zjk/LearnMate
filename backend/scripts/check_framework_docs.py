"""核对框架文档登记表 —— 把里面每条 URL 真抓一遍。

**为什么要有这个脚本**：登记表的 docstring 写着「每条 URL 都是实际抓过、确认存在的」，
那是一句**人工承诺**。文档站改版、域名迁移是常态，过一阵就不成立了 —— 实测：
`docs.claude.com` 301 跳到 `platform.claude.com`，而在本机所在地区那个域名整站返回
一张「App unavailable in region」的封锁页。承诺不会自己复核，这个脚本会。

**为什么不放进 pytest**：它要联网。让单元测试依赖外网，等于让测试的绿灯取决于别人的
服务器今天开不开门。

**它查四件事**：
  1. 抓不到（超时、404、JS 空壳 —— 实测的 JS 空壳都是 **0 字**，全落到这一条）
  2. **两条不同的登记 URL 抓回一模一样的内容** —— 这是"都跳到了同一张错误页"的签名，
     也是这个脚本里最有用的一条：它不需要任何额外信息就能认出假阳性
  3. 抓取层自己报的说明（没抓干净的残留标记、**跳到了别的站上**）
  4. 正文偏短 —— 只是提醒，不是判错。Mintlify 系文档站（langchain / mcp / chroma /
     pydantic-ai / qdrant…）的介绍页本身就短：正文三百来字，前面压着四五十行侧边导航。
     这类页是真文档，别删；看到了知道"这页东西少"就够了。

用法：

    python backend/scripts/check_framework_docs.py
    python backend/scripts/check_framework_docs.py --only fastapi langgraph

**退出码**：有抓不到的、或内容重复的条目就非 0（过短和说明只算提醒）——
这样它能挂在任何"跑一遍检查"的地方。
"""
import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.utils.framework_docs import FRAMEWORKS  # noqa: E402
from backend.src.utils.web_page import fetch_readable_text  # noqa: E402

# 正文短于这个数就提醒一句。**这个数只是"看一眼"的门槛，不是判错线**：Mintlify 系
# 文档站的介绍页（mcp 3036 字、chroma 2280 字）确实四成是正文、六成是侧边导航，它们
# 是真文档。而 JS 空壳是 0 字，根本轮不到这个数起作用（被"抓不到"收走）。
THIN_PAGE_CHARS = 4000

# 并发数。别开太大：这些是别人的文档站，我们只是路过。
CONCURRENCY = 6


def _collect_sources(only: list[str]) -> list[tuple[str, dict]]:
    wanted = [item for item in FRAMEWORKS if not only or item["id"] in only]
    return [
        (item["id"], source)
        for item in wanted
        for source in item["sources"]
    ]


async def _probe(semaphore, framework_id, source):
    async with semaphore:
        text, note = await fetch_readable_text(source["url"])
    first_line = text.splitlines()[0] if text else ""
    return {
        "framework": framework_id,
        "label": source["label"],
        "url": source["url"],
        "size": len(text),
        "first_line": first_line,
        # 两条不同地址抓到同一份内容 → 同一个 (size, 首行)。见模块开头第 2 条。
        "fingerprint": (len(text), first_line) if text else None,
        "note": note,
        "ok": bool(text),
    }


def _find_duplicates(rows: list[dict]) -> set[str]:
    """哪些地址抓回了和别的地址一模一样的内容。

    **这是这个脚本里最值钱的一条。** "四个不同 URL 全落到同一张封锁页"在链路上长得和
    成功一模一样 —— 字数够、没有报错、exit code 0。只有横向比一下才看得出来。
    """
    seen: dict[tuple, list[str]] = {}
    for row in rows:
        if row["fingerprint"]:
            seen.setdefault(row["fingerprint"], []).append(row["url"])
    return {
        url
        for urls in seen.values()
        if len(urls) > 1
        for url in urls
    }


def _flags(row: dict, duplicated: set[str]) -> list[str]:
    flags = []
    if not row["ok"]:
        flags.append("抓不到")
    if row["url"] in duplicated:
        flags.append("内容重复")
    if row["ok"] and row["size"] < THIN_PAGE_CHARS:
        flags.append("过短")
    if row["note"]:
        flags.append("有说明")
    return flags


async def main() -> int:
    # Windows 控制台默认是 GBK，中文标题直接 print 会抛 UnicodeEncodeError。
    # 这一句和业务无关，但没有它这个脚本在 Windows 上根本跑不完。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="核对框架文档登记表")
    parser.add_argument("--only", nargs="*", default=[], help="只查这几个框架 id")
    args = parser.parse_args()

    sources = _collect_sources(args.only)
    if not sources:
        print("没有要查的条目 —— 检查 --only 里的名字写对没有")
        return 1

    semaphore = asyncio.Semaphore(CONCURRENCY)
    rows = await asyncio.gather(
        *(_probe(semaphore, framework_id, source) for framework_id, source in sources)
    )

    duplicated = _find_duplicates(rows)

    print("%-13s %-26s %8s  %-16s %s" % ("框架", "页", "字数", "标记", "标题"))
    print("-" * 110)
    for row in rows:
        print("%-13s %-26s %8d  %-16s %s" % (
            row["framework"],
            row["label"][:24],
            row["size"],
            "、".join(_flags(row, duplicated)) or "ok",
            row["first_line"][:40],
        ))

    print()
    for row in rows:
        if row["note"]:
            print("  说明 %s：%s" % (row["url"], row["note"]))

    broken = [row for row in rows if not row["ok"] or row["url"] in duplicated]
    print()
    print("查了 %d 条：%d 条有问题，%d 条提醒" % (
        len(rows),
        len(broken),
        len([row for row in rows if _flags(row, duplicated) and row not in broken]),
    ))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
