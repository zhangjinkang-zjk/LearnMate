"""框架官方文档的登记表 — "要读这个框架，读哪几页"的唯一事实来源。

**它不是爬虫，是一张人工挑过的入口页清单。** 为什么是这样：

- **索引是有的；"该读哪几页"得有人挑。** 实测（2026-10-02）：9 个站里 **7 个有
  `/llms.txt`**（chroma 178 条、qdrant 684 条，另有 mcp / vue / vite / crewai /
  langchain），没有的只有 FastAPI 和 sbert。LangChain 那份指过去的是 `_llms/*.md`
  合订本（agent 那条 1479 页一份），抓下来会被上限腰斩，等于只给了开头。
  所以"有哪些页"机器能答，**"学它该读哪几页"只有人能答** —— 全站镜像给学生的不是资料，
  是导航、版本表和广告。
- **每条 source 优先写页面的 `.md` 版本**（`.../guide/intro.md`）。文档站现在普遍提供它：
  实测 38 条里 **32 条**有，没有的正好是同一批没有 `/llms.txt` 的（FastAPI、sbert）。
  markdown 原文没有侧边导航、没有壳子、代码块原样保留 —— 比抓 HTML 再抽正文干净一整档。

**不做版本。** 一个"跟版本"的表要按框架各写一套解析，而收益可以更低成本拿到：每份文档
落盘时抬头写明来源 URL 和抓取日期，教练手上又有学生项目里的依赖清单 —— 该对版本的
时候它自己会对。**不去猜一个我们验证不了的版本号。**

**每条 URL 都是实际抓过、确认存在的。** 但文档站改版是常态，所以抓不到的条目在运行时会
**如实报出来并跳过**，不会静默少给几页（见 `service/advanced/reference_docs.py`）。
想复查这张表，跑 `backend/tools/check_framework_docs.py` —— 它把每条 URL 真抓一遍，
把**落点域名对不上登记域名**的条目标出来。

**这张表是快捷方式，不是门禁。** 教练认不出的技术可以走 `fetch_framework_docs` 的
`urls` 参数直接把官方文档页拿进来 —— 表里没有不等于拿不到（见
`ai_core/tools/workspace.py` 里那个工具）。所以往这里加条目是为了**质量**（人工挑过的
入口页、统一命名、7 天缓存），不是为了放开权限。

**实测抓不动的站不进这张表**（登记了就是把垃圾发到学生手里）：Anthropic 文档在本机
所在地区整站返回封锁页；LlamaIndex / OpenAI platform 是 JS 渲染的空壳；
Streamlit / Gradio / AutoGen 的首页只有一两千字，是壳不是文档。这些站学生真要用，
走 `urls` 那条路 —— 抓不抓得开，那时候才知道。
"""

import re
from urllib.parse import urlparse

# 每条 source 的 url 都必须真的抓得开。加新框架时先自己访问一遍再写进来 ——
# 猜一个路径写在这里，表现会是"学生那边少了一页，而且没人知道为什么"。
#
# **优先写页面的 `.md` 版本**（`.../guide/intro.md`）。抓取那层见到 `text/markdown`、
# 或者 `.md` / `.txt` 结尾的地址，就按**原样文本**处理：直接给正文，不再当 HTML 解析
# （见 `utils/web_page.py` 的 `_is_plain_text`）。这样拿到的文档没有侧边导航、没有壳子、
# 代码块原样保留 —— 实测 38 条里 32 条有 `.md`。没有的（FastAPI、sbert）就照旧写 HTML
# 地址，那条路已经补过正文区域切片和转义标记清理。
FRAMEWORKS: list[dict] = [
    # ── 智能体：这一批是这个平台真正在教的东西，排前面 ──
    {
        "id": "langchain",
        "name": "LangChain",
        # 注意 python.langchain.com 现在 308 跳到 docs.langchain.com，两个域名都收，
        # 免得学生项目里写的旧文档地址认不出来。
        "aliases": ("langchain", "lang chain"),
        "domains": ("docs.langchain.com", "python.langchain.com"),
        "sources": (
            {"label": "快速开始：搭起第一个 agent", "url": "https://docs.langchain.com/oss/python/langchain/quickstart.md"},
            {"label": "Agents", "url": "https://docs.langchain.com/oss/python/langchain/agents.md"},
            {"label": "Tools", "url": "https://docs.langchain.com/oss/python/langchain/tools.md"},
            {"label": "Messages", "url": "https://docs.langchain.com/oss/python/langchain/messages.md"},
            {"label": "检索（RAG 取数的另一半）", "url": "https://docs.langchain.com/oss/python/langchain/retrieval.md"},
            {"label": "检索增强生成（RAG）", "url": "https://docs.langchain.com/oss/python/langchain/rag.md"},
        ),
    },
    {
        "id": "langgraph",
        "name": "LangGraph",
        # LangGraph 是独立产品，但文档和 LangChain 同一个站 —— 两条注册项共用一个域名，
        # 这是有意的：学生嘴里说的是两个名字，文件夹也该是两个。
        "aliases": ("langgraph", "lang graph"),
        "domains": ("langchain.com",),
        "sources": (
            {"label": "概览", "url": "https://docs.langchain.com/oss/python/langgraph/overview.md"},
            {"label": "Graph API", "url": "https://docs.langchain.com/oss/python/langgraph/graph-api.md"},
            {"label": "状态持久化", "url": "https://docs.langchain.com/oss/python/langgraph/persistence.md"},
            {"label": "用 Graph API 写", "url": "https://docs.langchain.com/oss/python/langgraph/use-graph-api.md"},
        ),
    },
    {
        "id": "mcp",
        "name": "MCP",
        "aliases": ("mcp", "model context protocol"),
        "domains": ("modelcontextprotocol.io",),
        "sources": (
            {"label": "MCP 是什么", "url": "https://modelcontextprotocol.io/docs/getting-started/intro.md"},
            {"label": "架构", "url": "https://modelcontextprotocol.io/docs/learn/architecture.md"},
            {"label": "写一个 MCP 服务", "url": "https://modelcontextprotocol.io/docs/develop/build-server.md"},
        ),
    },
    {
        "id": "pydantic-ai",
        "name": "Pydantic AI",
        "aliases": ("pydantic ai", "pydantic-ai", "pydanticai"),
        "domains": ("pydantic.dev",),
        # 地址是 2026-10-02 核对过的：Pydantic 那天把文档整站并到了 pydantic.dev，
        # 旧的 `ai.pydantic.dev/*` 和 `docs.pydantic.dev/*` 都 301 过去（抓取层会报
        # "跳转到了…"）。写新地址，学生那边少一跳，落点也就不用每次都解释一遍。
        "sources": (
            {"label": "起步", "url": "https://pydantic.dev/docs/ai/overview.md"},
            {"label": "Agent", "url": "https://pydantic.dev/docs/ai/core-concepts/agent.md"},
            {"label": "工具", "url": "https://pydantic.dev/docs/ai/tools-toolsets/tools.md"},
        ),
    },
    {
        "id": "crewai",
        "name": "CrewAI",
        "aliases": ("crewai", "crew ai"),
        "domains": ("crewai.com",),
        "sources": (
            {"label": "介绍", "url": "https://docs.crewai.com/introduction.md"},
            {"label": "Agents", "url": "https://docs.crewai.com/concepts/agents.md"},
        ),
    },
    # ── 检索、向量、嵌入：上头那批落地要靠它们 ──
    {
        "id": "chroma",
        "name": "Chroma",
        "aliases": ("chroma", "chromadb"),
        "domains": ("trychroma.com",),
        "sources": (
            {"label": "起步", "url": "https://docs.trychroma.com/docs/overview/getting-started.md"},
            {"label": "查询", "url": "https://docs.trychroma.com/docs/querying-collections/query-and-get.md"},
            {"label": "管理集合", "url": "https://docs.trychroma.com/docs/collections/manage-collections.md"},
        ),
    },
    {
        "id": "qdrant",
        "name": "Qdrant",
        "aliases": ("qdrant",),
        "domains": ("qdrant.tech",),
        "sources": (
            {"label": "快速开始", "url": "https://qdrant.tech/documentation/quickstart.md"},
            {"label": "集合", "url": "https://qdrant.tech/documentation/concepts/collections/index.md"},
            {"label": "五分钟搭一个语义检索", "url": "https://qdrant.tech/documentation/tutorials/search-beginners/index.md"},
        ),
    },
    {
        "id": "sbert",
        "name": "Sentence Transformers",
        "aliases": ("sentence transformers", "sentence-transformers", "sbert"),
        "domains": ("sbert.net",),
        "sources": (
            {"label": "文档首页", "url": "https://sbert.net/"},
            {"label": "快速开始", "url": "https://sbert.net/docs/quickstart.html"},
            {"label": "用法", "url": "https://sbert.net/docs/sentence_transformer/usage/usage.html"},
        ),
    },
    # ── 后端 ──
    {
        "id": "fastapi",
        "name": "FastAPI",
        "aliases": ("fastapi", "fast api"),
        "domains": ("fastapi.tiangolo.com",),
        "sources": (
            {"label": "起步：第一个应用", "url": "https://fastapi.tiangolo.com/tutorial/first-steps/"},
            {"label": "多文件项目的目录结构", "url": "https://fastapi.tiangolo.com/tutorial/bigger-applications/"},
            {"label": "命令行工具 fastapi dev", "url": "https://fastapi.tiangolo.com/fastapi-cli/"},
        ),
    },
    {
        "id": "pydantic",
        "name": "Pydantic",
        "aliases": ("pydantic",),
        "domains": ("pydantic.dev",),
        # 同上：`docs.pydantic.dev/latest/*` 现在也并进 pydantic.dev 了。
        "sources": (
            {"label": "起步", "url": "https://pydantic.dev/docs/validation/latest/get-started.md"},
            {"label": "模型", "url": "https://pydantic.dev/docs/validation/latest/concepts/models.md"},
        ),
    },
    # ── 前端 ──
    {
        "id": "vue",
        "name": "Vue",
        "aliases": ("vue", "vue.js", "vuejs"),
        "domains": ("vuejs.org",),
        "sources": (
            {"label": "介绍", "url": "https://vuejs.org/guide/introduction.md"},
            {"label": "快速开始", "url": "https://vuejs.org/guide/quick-start.md"},
            {"label": "组件基础", "url": "https://vuejs.org/guide/essentials/component-basics.md"},
        ),
    },
    {
        "id": "vite",
        "name": "Vite",
        "aliases": ("vite",),
        "domains": ("vite.dev",),
        "sources": (
            {"label": "指南", "url": "https://vite.dev/guide.md"},
            {"label": "为什么是 Vite", "url": "https://vite.dev/guide/why.md"},
            {"label": "配置", "url": "https://vite.dev/config.md"},
        ),
    },
]

_BY_ID = {item["id"]: item for item in FRAMEWORKS}

# 落盘文件名里不能出现的字符。**Windows 比 POSIX 严**：`:` `*` `?` `"` `<` `>` `|`
# 一个都不能有，而这些恰好是文档标题里最常见的（"起步：第一个应用"）。
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_FILENAME_STEM = 60


def catalogue() -> list[dict]:
    """界面用的框架清单。只给标识，不把 URL 铺给前端。"""
    return [
        {"id": item["id"], "name": item["name"], "source_count": len(item["sources"])}
        for item in FRAMEWORKS
    ]


def get_framework(framework_id: str) -> dict | None:
    return _BY_ID.get(str(framework_id or "").strip().lower())


def match_frameworks(text: str) -> list[dict]:
    """从一段文字里认出提到了哪些框架。

    给"学生自己写的那份选型记录"用 —— 那是他说过什么算数的**证据**（在磁盘上、
    他改得动），而不是会话里的一句声称。
    """
    haystack = str(text or "").lower()
    if not haystack:
        return []
    return [
        item
        for item in FRAMEWORKS
        if any(alias in haystack for alias in item["aliases"])
    ]


def matches_domain(url: str) -> bool:
    """这个 URL 是不是某个登记框架的官方域名。抓之前用它再确认一次。"""
    host = ""
    match = re.match(r"^https?://([^/]+)", str(url or "").strip(), re.I)
    if match:
        host = match.group(1).lower().split(":")[0]
    if not host:
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for item in FRAMEWORKS
        for domain in item["domains"]
    )


def folder_for_url(url: str) -> str:
    """从一条 URL 取一个当目录名用的名字。

    **取域名，不猜产品名。** 教练给的是一串地址，我们只知道它落在哪个站上；把
    `vuejs.org/guide/quick-start.html` 写成 `Vue/` 是编的 —— 而这个文件夹学生会当成
    资料的一部分看到。域名是真话，而且每份文件抬头里本来也写着来源 URL。

    `www.` 和前导 `docs.` 去掉（`docs.trychroma.com` → `trychroma.com`）：它们是约定
    俗成、不带信息量的前缀。要求去掉之后至少还剩两段，免得把 `docs.com` 整个吃掉。
    """
    host = (urlparse(str(url or "").strip()).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("docs.") and host.count(".") >= 2:
        host = host[5:]
    return host


def safe_filename(stem: str, fallback: str = "doc") -> str:
    """把标题变成能落盘的文件名。

    空、超长、或者只剩标点的一律回退到 `fallback` —— 学生拿到一个叫 `.md` 的文件
    比拿到一个叫 `doc.md` 的更难理解。
    """
    cleaned = _UNSAFE_FILENAME_CHARS.sub(" ", str(stem or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:_MAX_FILENAME_STEM].strip()
    return cleaned or fallback
