"""抓取网页并提取正文 — 全站"把一页网文读成文字"的唯一出口。

**为什么在 `utils/` 而不在 `ai_core/tools/`**：它不该知道"智能体"这个概念。它只是
「给一个 URL，还一段能读的正文」。抓正文的调用方已经有智能体工具（联网补库）之外的
人 —— 把官网文档落进学生工作区那条路要走 service/router，而 `service/` 不许 import
`ai_core/`（依赖方向是倒的，见 AGENTS.md 的分层）。放这里两边都能用。

调用方：
    ai_core/tools/knowledge.py  联网补库，逐条抓来源正文
    ai_core/tools/search.py     read_web_page 工具（教练读官网那一页）

**安全前提：这个函数可以被模型喂任意 URL。** 所以 `check_fetchable_url` 不只看协议和
后缀，还会解析主机名、拒掉一切非公网地址，并且**逐跳检查重定向** —— 否则
`http://169.254.169.254/`（云元数据）或 `http://127.0.0.1:2221/` 会被服务端真的请求
出去，跳转一跳到内网同样要拦。这是 SSRF 的标配防线，别删。
"""

import asyncio
import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

# 单页抓取上限。8 秒 / 8MB 是按"一个文档页"定的，够用且不会让一次工具调用挂住。
FETCH_TIMEOUT = 8.0
FETCH_MAX_BYTES = 8 * 1024 * 1024
# 手工跟重定向的跳数上限。够官网用（http→https→规范化路径通常两跳）。
MAX_REDIRECTS = 5

TEXT_MAX_CHARS = 120000
# 比这还短的"正文"基本不是正文，多半是动态渲染的壳子或者跳转页。
TEXT_MIN_CHARS = 220

# 抽正文这一层的版本号。**任何会改变输出的改动都要 +1。**
#
# 为什么一个"纯函数"需要一个版本号：抽出来的正文会被下游按 URL 缓存（`reference_docs`
# 存 7 天）。缓存里躺着的是**旧代码抽出来的那串文字**，改抽取代码不会让它失效 ——
# 下一次抓同一个 URL 照样命中缓存、照样还回那份碎句。于是"修好了"和"没修"在这条链子上
# 长得一模一样，改完 bug 的人重拉一遍会以为自己没修对。（`web_search_client` 踩过同一个
# 坑，那儿叫 `_CACHE_VERSION`。）放进缓存 key，旧产物当场作废。
#
# v1 → v2：行内标签不再断行（`"\n".join` 改 `"".join`）；成对闭合的转义标记被清掉。
# v2 → v3：抓完记下落点，跳转到别的主机时在说明里说出来（见 `landing_note`）。
# v3 → v4：正文区域多认一个标记 `<main>`，切掉现代文档站压在正文前面的侧边导航。
# v4 → v5：`text/markdown`（以及 `.md` 结尾的地址）按**原样文本**走，不再当 HTML 解析 ——
#          代码缩进保留、残留标记自检跳过。
# v5 → v6：代码围栏上挂的主题元数据（`theme={...}`）去掉。
EXTRACT_VERSION = "v6"

# 这些是文件，不是网页。装不下、也不该在这里解析。
_BLOCKED_PATH_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".rar",
    ".7z", ".tar", ".gz", ".exe", ".dmg", ".iso", ".mp4", ".mp3", ".png",
    ".jpg", ".jpeg", ".gif", ".svg", ".webp",
)

# 正文区域标记。命中就把这一片切出来，避免把导航和侧栏算进正文。
# 前几条是中文博客站的（cnblogs/CSDN 那类），最后一条 `<article` 覆盖技术文档站
# 用得最多的那个语义标签 —— 框架官网基本都吃这一条。
ARTICLE_START_MARKERS = (
    'id="cnblogs_post_body"',
    "id='cnblogs_post_body'",
    'class="postBody"',
    "class='postBody'",
    'class="article-content"',
    "class='article-content'",
    'class="article_content"',
    "class='article_content'",
    'class="post-content"',
    "class='post-content'",
    'class="entry-content"',
    "class='entry-content'",
    "<article",
    # 现代文档站（Mintlify / VitePress / MkDocs 系）都把正文包在一个 `<main>` 里，
    # 而**侧边导航在它前面** —— 实测 langchain / mcp / chroma / vue 每页正文前压着
    # 34~114 行链接文字（`<main>` 之内才是正文，`<main>` 之前是那个站的目录树）。
    #
    # **放在最后一条**，所以只有现在**完全没被切过**的页才会走到它：中文博客那几条标记
    # 和 `<article` 都排在前面，先命中就先用它们 —— 这样这一条只加不减，不改已有行为。
    "<main",
)

ARTICLE_END_MARKERS = (
    'id="MySignature"',
    "id='MySignature'",
    'id="blog_post_info_block"',
    "id='blog_post_info_block'",
    'class="postDesc"',
    "class='postDesc'",
    'class="post-footer"',
    "class='post-footer'",
    "posted @",
    "上一篇：",
    "下一篇：",
)

# 站内导航词汇。命中整行丢掉 —— 它们在任何一页上都长一样，进正文只是噪声。
_NAV_NOISE = {
    "会员", "周边", "新闻", "博问", "闪存", "赞助商", "所有博客", "当前博客",
    "我的博客", "我的园子", "账号设置", "会员中心", "简洁模式", "退出登录",
    "注册", "登录", "刷新页面", "返回顶部", "公告",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.6",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}


class _VisibleTextParser(HTMLParser):
    """把 HTML 里**看得见的字**取出来：脚本/样式整块跳掉，块级标签当换行。

    **行内标签不许断行。** 以前 `get_text` 是把每一段文字都用 `\n` 拼起来的，于是
    `<p>你好 <b>世界</b></p>` 出来是两行 —— 抓下来的正文会被**每一个** `<span>` `<b>`
    `<code>` 切成碎句（FastAPI 那几页的正文全是这么碎的："Importing from" / 路径 /
    "as" / 包名 各占一行）。只有块级标签才该断行，行内标签接回去。
    """

    _SKIP = {"script", "style", "noscript", "svg", "canvas"}
    _BLOCK = {
        "p", "br", "div", "section", "article", "aside", "header", "footer", "main", "nav",
        "li", "ul", "ol", "tr", "td", "th", "table", "blockquote", "pre", "figure",
        "figcaption", "hr", "dt", "dd", "form",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }
    # `pre` 里的空白**是内容**（终端输出、代码缩进），压成一个空格就毁了
    _PRESERVE = {"pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._pre_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag in self._PRESERVE:
            self._pre_depth += 1
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag in self._PRESERVE and self._pre_depth:
            self._pre_depth -= 1
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        piece = str(data or "")
        if not piece:
            return
        if self._pre_depth:
            self._parts.append(piece)
            return
        # 行内空白压成**一个空格**而不是换行 —— 压成换行就是上面那个碎句问题。
        # 纯空白的那一段也留着：`<b>甲</b> <b>乙</b>` 中间那个空格就是它，丢掉会粘成"甲乙"。
        self._parts.append(re.sub(r"\s+", " ", piece))

    def get_text(self) -> str:
        return "".join(self._parts)


# 一行里出现的 HTML 标签。**保守**：属性里带 `>` 的匹配不全，但那种行本来就是整行要处理的。
_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]{0,200}>")
_TAG_NAME_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)")

# 兜底：没有闭合、但标签又多又密的那种行，也按标记处理
TAG_LINE_RATIO = 0.4
TAG_LINE_COUNT = 3


def _has_balanced_tag_pair(matches: list[re.Match]) -> bool:
    """这一行里的标签**有开有合**吗？

    **这是"这行是标记"最站得住的判据，比按比例猜强得多。** 试过好几版比例阈值，
    每一版都被真页面推翻：

    - `<b>fastapi run</b>` —— 标签只占 7/18，差 0.01 没过线，漏掉；
    - `quit<b>)</b>` —— 更糟，它**不以 `<` 开头**（被 span 边界从中间切开），
      标签又只有 2 个、占 7/28，两条比例分支都够不着。

    而"成对闭合"这条把两种情况一次收掉，同时不误伤正经内容：一句话里随手提一个
    `<div>`、泛型 `<T>`、占位符 `<name>` —— **都不会闭合**。
    """
    stack: list[str] = []
    for match in matches:
        name_match = _TAG_NAME_RE.match(match.group(0))
        if not name_match:
            continue
        name = name_match.group(1).lower()
        if match.group(0).startswith("</"):
            if name in stack:
                return True
            continue
        stack.append(name)
    return False


def strip_escaped_markup(line: str) -> str:
    """去掉"被转义过、又被解开"的 HTML 标签。

    有些文档为了显示**彩色终端输出**，把一段带内联样式的 HTML **转义后**放进 `<pre>`
    （FastAPI 的命令行那几页就是这样）。`HTMLParser` 会把 `&lt;span&gt;` 解成 `<span>`，
    于是标签作为"正文"留下来了 —— 学生读到的是一屏
    `<span style="background-color:#007166"><font color="#D3D7CF">`。

    **这里有个治不好的极限，得说清楚**：一段被转义、等着被 JS 渲染出来的标记，和一篇
    "讲 HTML 的教程里当例子写的标记"，**在静态 HTML 里是同一个字符串** —— 区别只在于
    原站会不会去渲染它，而判不出来。所以这一层永远会有漏网的，靠下面
    `residual_markup_note()` 的自检把它**说出来**，而不是假装干净。
    """
    matches = list(_TAG_RE.finditer(line))
    if not matches:
        return line

    if _has_balanced_tag_pair(matches):
        return _TAG_RE.sub("", line)

    markup_len = sum(match.end() - match.start() for match in matches)
    if len(matches) >= TAG_LINE_COUNT or markup_len >= len(line) * TAG_LINE_RATIO:
        return _TAG_RE.sub("", line)
    return line


# 抽完之后，正文里还剩多少标记样文本算"没抓干净"。按**每千字**算，长页面宽容一些。
RESIDUAL_TAG_RATE = 0.004


def residual_markup_note(text: str) -> str:
    """这一页抽完之后还剩多少标记？剩得多就说明**没抓干净**。

    **这是"治本"里能做的那一半。** 上面那层判据不可能做到 100%（见它的说明：被转义的
    标记和当例子写的标记是同一个字符串），所以退一步 —— **让抓不干净这件事变得可见**：
    学生和教练至少知道"这一页没读好"，而不是对着一屏 `<span style="...">` 去写代码，
    还以为那就是正文。
    """
    body = str(text or "")
    if len(body) < 200:
        return ""
    found = len(_TAG_RE.findall(body))
    if found < 3 or found / len(body) < RESIDUAL_TAG_RATE:
        return ""
    return f"正文里还剩 {found} 处没清掉的 HTML 标记，这一页可能没读干净"


def _host_of(url: str) -> str:
    """地址的主机名。`www.` 不算差别（`www.x.com` 和 `x.com` 是同一个站）。"""

    host = (urlparse(str(url or "").strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def landing_note(requested: str, landed: str) -> str:
    """抓完之后**停在了别的站上**吗？停在别站就说出来。

    实测踩到的：`docs.claude.com` 301 跳到 `platform.claude.com`，而那个域名在这台机器上
    整站返回「App unavailable in region」的封锁页。四个不同 URL 全落到**同一张 4806 字**
    的错误页上，而 `fetch_readable_text` 照样报"成功" —— 链路上没有任何地方看得出来。

    **判据只认主机变没变，不看路径。** 试过把路径也算上，结果是噪音压掉了信号：文档站
    把 `/guide` 重写成 `/guide/introduction`、把 `/latest/` 换成 `/v3/` 都是日常操作，
    内容恰恰是对的。天天报的警告等于没报。而"落到另一个站上"是强信号 —— 站点搬家、
    被墙、被解析到一个停放页，都长这样。

    **这一层治不好的那两半**（都得说清楚）：
      - 同主机的路径重写，判不出来是"帮了忙"还是"你要的那页没了"；
      - 一个 200 正常返回、内容却是"本地区不可用"的页，和真文档页在链路上没有区别。
    """
    if not landed or str(landed).strip() == str(requested).strip():
        return ""
    if _host_of(requested) == _host_of(landed):
        return ""
    return f"这一页跳转到了 {landed}，内容可能已经不是你要的那一页"


def _join_notes(*notes: str) -> str:
    """把几条说明并成一句。每条都是完整的话，所以用分号连。"""
    return "；".join(note for note in notes if note)


def _ip_is_public(ip) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolves_to_public_address(host: str) -> tuple[bool, str]:
    """主机名解析出来的**每一个**地址都必须是公网地址。

    只查第一个就放行是不够的：一个域名可以同时解析到公网和内网地址（DNS rebinding
    的常见形态），而 httpx 挑哪个不由我们决定。
    """
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError:
        return False, "域名解析失败"
    addresses = {info[4][0] for info in infos if info[4]}
    if not addresses:
        return False, "域名没有解析出地址"
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False, "域名解析出了无法识别的地址"
        if not _ip_is_public(ip):
            return False, "该地址不在公网（可能是内网或本机地址）"
    return True, ""


async def check_fetchable_url(url: str) -> tuple[bool, str]:
    """这个 URL 能不能抓。返回 (可以吗, 拒绝原因)。

    **每次重定向之后都要重新走一遍这个函数**（见 `fetch_readable_text`）—— 检查一次
    首跳然后放开跟转，等于没检查。
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "不是可直接抓取的网页地址"
    if parsed.path.lower().endswith(_BLOCKED_PATH_SUFFIXES):
        return False, "这不是网页，是文件"
    host = parsed.hostname or ""
    if not host:
        return False, "地址里没有主机名"
    return await _resolves_to_public_address(host)


def extract_visible_text(markup: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(markup)
    except Exception:
        return ""
    text = html.unescape(parser.get_text())
    lines = []
    seen = set()
    for raw_line in text.splitlines():
        # 先去掉被转义又被解开的标记，**再**压空白 —— 标签去掉后会留下一串空格
        line = re.sub(r"\s+", " ", strip_escaped_markup(raw_line)).strip()
        if len(line) < 2 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines).strip()


def slice_article_markup(markup: str) -> str:
    """切出正文那一片。找不到任何标记就原样返回（宁可多带导航，也别切掉正文）。"""
    lower = markup.lower()
    start = -1
    for marker in ARTICLE_START_MARKERS:
        idx = lower.find(marker.lower())
        if idx < 0:
            continue
        tag_start = lower.rfind("<", 0, idx)
        start = tag_start if tag_start >= 0 else idx
        break

    if start < 0:
        return markup

    end_candidates = []
    for marker in ARTICLE_END_MARKERS:
        idx = lower.find(marker.lower(), start + 1)
        if idx > start:
            tag_start = lower.rfind("<", 0, idx)
            end_candidates.append(tag_start if tag_start > start else idx)
    end = min(end_candidates) if end_candidates else len(markup)
    return markup[start:end]


def clean_source_text(text: str) -> str:
    lines: list[str] = []
    seen = set()
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line in _NAV_NOISE:
            continue
        if len(line) <= 2 and re.fullmatch(r"[\W_]+", line):
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines).strip()


# 代码围栏 info 串末尾挂着的机器元数据，例如：
#     ```python Google theme={"theme":{"light":"catppuccin-latte","dark":"catppuccin-mocha"}}
# 那是主题配置，人读不到、也不属于内容。实测 langchain 那几页每页七十多处，
# 一行一百个字符全是 JSON —— 留着的话学生看到的每个代码块头上都顶一坨花括号。
_FENCE_META_RE = re.compile(r"\s+theme=\{.*\}\s*$")


def _strip_fence_metadata(line: str) -> str:
    """只在**代码围栏那一行**上动手。正文里出现 `theme={...}` 是内容，不能碰。"""
    if not line.startswith("```"):
        return line
    return _FENCE_META_RE.sub("", line)


def tidy_plain_text(text: str) -> str:
    """原样文本（markdown / 纯文本）只做最轻的整理：去行尾空白、连续空行压成一个。

    **`clean_source_text` 那套不能用在它身上。** 那一套是给"HTML 抽出来的一地碎行"
    准备的：压掉行内空白、按行去重、丢掉短行。用在代码上是在毁内容 ——
    Python 的四空格缩进被压成一格，代码就不是代码了；而两行 `return None` 是正常的，
    按行去重会删掉一行。

    这两条都是"看起来在做清理、实际在改语义"的典型，所以这里是**另开一条路**，
    不是给 `clean_source_text` 加参数。
    """
    lines = [_strip_fence_metadata(line.rstrip()) for line in str(text or "").splitlines()]
    kept: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip():
            blanks = 0
            kept.append(line)
            continue
        blanks += 1
        if blanks <= 1:
            kept.append("")
    return "\n".join(kept).strip()


def _clip_source_text(text: str, max_chars: int) -> tuple[str, bool]:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def _decode_body(raw: bytes, encoding: str | None) -> str:
    return raw.decode(encoding or "utf-8", errors="ignore")


# 文档站现在普遍提供页面的 **markdown 原文**（`.../guide/intro.md`），比渲染后的 HTML
# 干净得多：没有侧边导航、没有壳子、代码块原样保留。Vue 的正文第一行自己就在说这件事
# （"Are you an LLM? You can read better optimized documentation at .../introduction.md"）。
#
# 按内容类型**和**路径后缀一起认：有的站把 `.md` 当 `text/plain` 发，有的标 `text/markdown`，
# 也见过标错的。任何一条中了就按原文处理。
_PLAIN_TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
_PLAIN_TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".rst")


def _is_plain_text(content_type: str, url: str) -> bool:
    if any(kind in (content_type or "").lower() for kind in _PLAIN_TEXT_TYPES):
        return True
    return urlparse(str(url or "").strip()).path.lower().endswith(_PLAIN_TEXT_SUFFIXES)


def _extract_from_response(resp: httpx.Response, url: str) -> tuple[str, bool]:
    """返回 (正文, 是不是原样文本)。

    **第二项决定还要不要再做那两层 HTML 清理。** markdown 和纯文本里出现 `<div>`、
    `<img src=...>`、`export const Callout = () => <div>` 都是**内容**，不是"没清干净的
    标记" —— 拿 HTML 那套（切正文区域、剥转义标记、残留自检）去处理它，只会把正文
    咬掉一块，还会在每份文件抬头挂一条假的 ⚠️。
    """
    raw = resp.content[:FETCH_MAX_BYTES]
    content_type = resp.headers.get("content-type", "")
    if _is_plain_text(content_type, url):
        return _decode_body(raw, resp.encoding), True
    markup = _decode_body(raw, resp.encoding)
    return extract_visible_text(slice_article_markup(markup)), False


async def fetch_readable_text(url: str) -> tuple[str, str]:
    """抓一页并还它可读的正文。返回 (正文, 说明)。

    正文为空时说明非空，调用方应当**如实转述这个说明**，不要假装读到了内容 ——
    "抓不到"和"没写正文"在学生眼里是两件事，混起来他会以为那页真的没内容。

    **重定向是手工跟的**（`follow_redirects=False`）：交给 httpx 自动跟，就等于
    只在入口检查一次公网地址，一跳就能到内网。逐跳检查是这条链子安全的前提。
    """
    # 原始地址留着不动，用来和落点比（见 `landing_note`）。`current` 会被跳转改写。
    requested = str(url or "").strip()
    if not requested:
        return "", "没有给出网页地址"
    current = requested

    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=False,
            headers=_HEADERS,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                allowed, reason = await check_fetchable_url(current)
                if not allowed:
                    return "", reason

                resp = await client.get(current)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return "", "来源网页重定向但没给出目标地址"
                    # 相对跳转要补成绝对地址才能再过一遍检查。
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    return "", f"来源网页返回 HTTP {resp.status_code}"

                body, is_plain = _extract_from_response(resp, current)
                # 两条整理路：HTML 抽出来的一地碎行要走 `clean_source_text`，
                # 原样文本（markdown）只能轻整理 —— 缩进是语义（见 `tidy_plain_text`）。
                text = tidy_plain_text(body) if is_plain else clean_source_text(body)
                if len(text) < TEXT_MIN_CHARS:
                    # 落点也要说：跳到别的站之后只有一张壳子，多半是那个站根本没有这一页，
                    # 而不是"这页需要动态渲染"—— 两种情况给学生的下一步不一样。
                    return "", _join_notes(
                        landing_note(requested, current),
                        "来源网页正文过短或需要动态渲染",
                    )
                text, clipped = _clip_source_text(text, TEXT_MAX_CHARS)
                if clipped:
                    text = f"{text}\n\n[正文过长，已截取前 {TEXT_MAX_CHARS} 字]"
                # 抓到了，但可能没抓干净、或者停在别的页上。**这时候要带着说明回去**，
                # 不能返回一个空说明 —— 调用方（教练、落盘的文档）看到空说明就以为
                # 这页是干净、正确读下来的。
                #
                # 原样文本（markdown / 纯文本）跳过残留自检：那层是查"HTML 有没有剥干净"的，
                # 而 markdown 里的 `<img>`、JSX 是内容本身，查了会在每份文件抬头挂一条假警告。
                return text, _join_notes(
                    landing_note(requested, current),
                    "" if is_plain else residual_markup_note(text),
                )

            return "", f"来源网页重定向超过 {MAX_REDIRECTS} 次"
    except Exception as exc:
        return "", f"来源网页抓取失败：{type(exc).__name__}"
