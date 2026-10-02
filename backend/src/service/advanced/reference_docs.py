"""把官方文档抓下来，整理成可以直接落进学生文件夹的一组文件。

**来源有两种**：登记表里挑好的入口页（`utils/framework_docs.py`），和教练自己找到的
官方文档页地址。后者是 2026-10-02 加的 —— 起因是教练查表查不到 Vue，于是对学生说
「这个我拉不了，你去看 vuejs.org」，把学生推出了产品。表是快捷方式，不是门禁。
两种来源的区别只剩两处：**子目录怎么起名**（登记表用产品名，地址用域名）和
**要不要缓存**（见 `_fetch_one`）。

**这个模块只抓和整理，不写盘。** 写盘在**学生自己的浏览器里**（File System Access）——
后端没有、也不该有写学生本机的能力，学生项目在哪个目录只有他的浏览器知道。
所以这里产出的是一组内存里的文件，由前端拿着它去写。

**为什么不复用 `search_web_and_stage_knowledge` 那条链子**：那条是给知识库补库的
（搜索 → 暂存 → 管理员过审才生效），它对"可信"的处理是**先不信任**。而这里要的是
"学生现在就想读到的那几页"，每一页都来自登记过的官方域名。两者对信任的要求相反，
混起来只会互相拖累：要么补库那条被绕过审核，要么这里被"待审核"卡住。

**日期戳是"抓下来的那一刻"，不是"写文件的那一刻"。** 有了缓存，这两个会差好几天 ——
抬头必须写前者，否则学生以为手里是刚拉的。服务端只给 ISO 8601（带时区），**成句的
显示交给前端**：服务端拼会因时区差一天（这类坑这个仓库踩过，见 `utils/scheduler.py`
的 `_shanghai_now`），而浏览器 `new Date()` 解析出来就是学生自己的墙上时间。
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from backend.src.utils.framework_docs import (
    folder_for_url,
    get_framework,
    matches_domain,
    safe_filename,
)
from backend.src.utils.redis_client import _cache_key, _text_hash, cache_get, cache_set
from backend.src.utils.web_page import EXTRACT_VERSION, fetch_readable_text

logger = logging.getLogger(__name__)

# 一次最多抓这么多页。注册表里每个框架 3-4 页，三个框架就到这个量级；
# 再多学生也读不完，而且响应体会很大（每页正文上限 12 万字符）。
MAX_DOCS_PER_REQUEST = 12

# ═══════════════════════════════════════
#  抓取缓存
# ═══════════════════════════════════════

# 抓下来的一页存多久。文档不是天天改，7 天足够挡住"同一个框架被不同学生各抓一遍"，
# 又不至于让内容老到误导人。过时是**有界的、说得出日期**的 —— 文件抬头里写的就是
# 真正抓取的那一天，不是"写文件的那一天"。
CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_NAMESPACE = "reference_docs"


def _now_iso() -> str:
    """抓取时间，ISO 8601 UTC。

    **由服务端给时间戳、前端负责显示**，而不是服务端直接拼成一句人话 —— 服务端拼会因
    时区差一天（这个仓库踩过，见 `utils/scheduler.py` 的 `_shanghai_now`）。带 Z 的
    ISO 串交给浏览器 `new Date()` 解析，出来的就是学生自己的墙上时间。
    """
    return datetime.now(timezone.utc).isoformat()


def _entry_key(url: str) -> str:
    """一页的缓存 key。**抽正文的版本号在这个 key 里面，不能拿掉。**

    少了它，改抽取代码等于没改：缓存存的是旧代码抽出来的文字，7 天里谁重拉一次都是
    命中它。学生重拉一遍看到的一模一样，会得出"你们没修"的结论 —— 而真正的原因在
    这里。（`web_page.EXTRACT_VERSION` 的说明写了完整的前因。）

    单拎成一个函数是为了让测试也走它：测试里手拼 key 的话，key 一改测试就悄悄失准，
    变成一条永远能过的空测试。
    """
    return _cache_key(_CACHE_NAMESPACE, EXTRACT_VERSION, _text_hash(url))


async def _fetch_one(url: str, cacheable: bool = True) -> tuple[str, str, str]:
    """取一页，带缓存。返回 (正文, 说明, 抓取时间)。

    `cacheable` 由调用方定，判据是**这条地址落不落在登记域名上**（`matches_domain`）。

    登记过的站是公开文档，缓存安全。别的地址不一定是：它们可能是内网的、带 token 的、
    设了访问控制的 —— 缓存等于**绕过原站的访问控制**，只要有人再要一次同一个 URL，
    不经过原站就能拿到内容。这条规矩以前是靠"只服务注册表"守住的；现在教练也能塞任意
    地址进来，所以改由**域名**来判，而不是由"谁在调"来判。
    """
    key = _entry_key(url) if cacheable else ""

    if key:
        cached = await cache_get(key)
        if isinstance(cached, dict) and cached.get("text"):
            return (
                str(cached["text"]),
                str(cached.get("note") or ""),
                str(cached.get("fetched_at") or ""),
            )

    text, note = await fetch_readable_text(url)
    fetched_at = _now_iso()
    # 失败的页**不进缓存**：文档站改版、临时 502 都可能明天就好了，
    # 把"抓不到"缓存七天等于七天里谁都拿不到。
    if text and key:
        await cache_set(
            key,
            {"text": text, "note": note, "fetched_at": fetched_at},
            CACHE_TTL_SECONDS,
        )
    return text, note, fetched_at


# 从地址取不出域名时的兜底目录名。正常走不到（`check_fetchable_url` 会先把不成形的
# 地址拦掉），只是不让它变成 `docs/框架文档//1-x.md` 那种路径。
URL_FOLDER_FALLBACK = "网页文档"

_FILE_EXTENSION_RE = re.compile(r"\.(html?|md|txt|php|aspx?)$", re.I)


def _label_for_url(url: str) -> str:
    """拿地址最后一段当标题。`.../guide/quick-start.html` → `quick-start`。

    **不去猜页面标题。** 标题在正文第一行，这会儿还没抓（这一层只负责排队）；
    而教练挑这一页的理由就写在它给的地址上，最后一段至少是它自己写的实话。
    """
    parsed = urlparse(str(url or "").strip())
    stem = _FILE_EXTENSION_RE.sub("", parsed.path.rstrip("/").rsplit("/", 1)[-1])
    return stem or parsed.hostname or "文档"


def _plan_fetches(frameworks: list[dict], urls: list[str]) -> list[dict]:
    """排好"抓哪几页"。顺序稳定 —— 前端按它给文件编号，学生看到的编号不会乱跳。

    两个来源（注册表 / 教练给的地址）排进**同一条队列**：对下游的抓取、编号、落盘来说
    它们是一回事，差别只有子目录怎么起名、和**要不要缓存**。

    教练那批按域名分目录、在各自目录里从 1 开始编号 —— 他给三个 vuejs.org 的地址，
    学生就该看到 `vuejs.org/1-… 2-… 3-…`，而不是接着别人的序号往下排。
    """
    plan: list[dict] = []
    for framework in frameworks:
        for index, source in enumerate(framework["sources"], start=1):
            if len(plan) >= MAX_DOCS_PER_REQUEST:
                return plan
            plan.append({
                "folder": framework["name"],
                "index": index,
                "source": source,
                # 注册表里的页都来自登记过的公开文档站，缓存安全
                "cacheable": True,
            })

    per_folder: dict[str, int] = {}
    for url in urls:
        if len(plan) >= MAX_DOCS_PER_REQUEST:
            return plan
        folder = folder_for_url(url) or URL_FOLDER_FALLBACK
        per_folder[folder] = per_folder.get(folder, 0) + 1
        plan.append({
            "folder": folder,
            "index": per_folder[folder],
            "source": {"label": _label_for_url(url), "url": url},
            # 落在登记域名上才缓存 —— 教练找来的地址不一定是公开的（见 `_fetch_one`）
            "cacheable": matches_domain(url),
        })
    return plan


def _file_path(item: dict) -> str:
    """一个来源一个子目录，文件名带序号 —— 学生按文件名就能看出阅读顺序。"""
    return (
        f"{item['folder']}/"
        f"{item['index']}-{safe_filename(item['source']['label'], fallback='doc')}.md"
    )


async def collect(framework_ids: list[str], urls: list[str] | None = None) -> dict:
    """抓取指定框架的入口页，外加教练自己找的地址。

    认不出的名字进 `unknown`（前端据此提示"这几个我认不出来"），抓不到的页进 `failures`
    并带上原因 —— **少给几页这件事必须说出来**，文档站改版是常态，静默少给会让学生
    以为自己看到的就这些。
    """
    wanted: list[dict] = []
    unknown: list[str] = []
    for raw in framework_ids or []:
        framework = get_framework(raw)
        if framework is None:
            unknown.append(str(raw))
            continue
        if framework not in wanted:
            wanted.append(framework)

    pages: list[str] = []
    for raw in urls or []:
        url = str(raw or "").strip()
        if url and url not in pages:
            pages.append(url)

    plan = _plan_fetches(wanted, pages)
    if not plan:
        return {"frameworks": [], "unknown": unknown, "files": [], "failures": []}

    outcomes = await asyncio.gather(
        *(_fetch_one(item["source"]["url"], item["cacheable"]) for item in plan),
        return_exceptions=True,
    )

    files: list[dict] = []
    failures: list[dict] = []
    for item, outcome in zip(plan, outcomes):
        source = item["source"]
        if isinstance(outcome, Exception):
            # `fetch_readable_text` 自己会把异常收成说明；走到这里说明连那个都没兜住。
            text, note, fetched_at = "", f"抓取异常：{type(outcome).__name__}", _now_iso()
        else:
            text, note, fetched_at = outcome
        if not text:
            failures.append(
                {
                    "framework": item["folder"],
                    "title": source["label"],
                    "url": source["url"],
                    "reason": note or "未知原因",
                }
            )
            continue
        files.append(
            {
                "path": _file_path(item),
                "framework": item["folder"],
                "title": source["label"],
                "url": source["url"],
                # 真正抓下来的那一刻 —— 命中缓存时可能是好几天前。前端抬头里写的是它，
                # 不是"写文件的那一刻"：文件是刚生成的，内容不是。
                "fetched_at": fetched_at,
                # 抓到了但没抓干净（`web_page.residual_markup_note`）、或者跳到了别的页上
                # （`web_page.landing_note`）时的说明。一路带到文件抬头里：学生看到一屏标签
                # 或者一张错误页时，至少知道那是抓取的问题、不是文档本身长这样。
                "note": note,
                "markdown": text,
            }
        )

    if failures:
        logger.info(
            "[ReferenceDocs] 框架=%s 地址=%s 取到 %s 页，%s 页失败",
            [entry["id"] for entry in wanted], len(pages), len(files), len(failures),
        )

    return {
        "frameworks": [{"id": entry["id"], "name": entry["name"]} for entry in wanted],
        "unknown": unknown,
        "files": files,
        "failures": failures,
    }
