# -*- coding: utf-8 -*-
"""学生工作区的写入口 —— 目前只有「把方案的一节写进文档」这一个动作。

**它和别的工具不一样：真正落盘发生在浏览器里。** 学生的项目在他自己的硬盘上，后端拿不到
那个文件夹（FSA 句柄只活在页面里）。所以这个工具在服务端执行时只是**校验参数、把内容
带回流里**：`brain.stream` 看到它被调用就多发一帧 `doc_write`，前端接住那一帧把文字写进
工作区。

这是故意的分工，不是绕路。模型产出的是结构化参数（JSON），比让它吐一段约定格式的文本、
再在流式分片里把那一段抠出来可靠得多 —— 分片会把标签切成两半，而 JSON 参数不会。

**为什么方案可以代笔、代码不行**：敲字不是学习。把已经谈定的东西落成 markdown 是体力活；
代码却是他要练的东西。所以这里只有写文档的工具，**不要**照着它加一个写代码的工具。
"""
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from backend.src.utils.framework_docs import catalogue, get_framework

# 一节标题不该长：它是 markdown 的 `##` 行，长了在文档里就是个段落
SECTION_MAX_CHARS = 60
# 太短的正文多半是模型偷懒写了个占位（"待补充"），与其写进文档不如让它重来
CONTENT_MIN_CHARS = 20
CONTENT_MAX_CHARS = 6000

DOC_PATH = "docs/方案.md"

# 工具名单独抽一个常量：`brain.stream` 要按这个名字把工具调用转成 `doc_write` 帧，
# 前后端也都按它认。写成裸字符串的话，改名时漏掉一处就是**静默失效**——
# 教练照样以为写进去了，学生左边什么都没有。
DOC_WRITE_TOOL = "write_design_doc"


@tool
async def write_design_doc(section: str, content: str):
    """把一个**已经和学生谈定**的方案小节写进他的方案文档（docs/方案.md）。

    调用时机：学生已经亲口把一个决定说全了（选了什么、为什么是它、放弃了什么），而你也
    确认过他的意思 —— 这时你就可以落笔，不用让他自己动手打字。

    **没谈定的东西不要调用它。** 你写进去的每一个字都必须是他刚才说过的话；他还没说的、
    你替他想好的、你觉得"显然该这样"的，一个字都不许写。写了，文档就从"他想清楚了"
    变成"你替他想清楚了"。

    一次写一节。同一节再调用会覆盖那一节的内容，其它节不动；标题要用稳定的小标题
    （要做什么 / 用什么做 / 怎么连起来 / 从哪儿开始写）。
    """
    title = str(section or "").strip().lstrip("#").strip()
    body = str(content or "").strip()

    if not title:
        return "这一节没有标题，没写。给一个稳定的小标题再调一次。"
    if len(title) > SECTION_MAX_CHARS:
        return (
            f"标题太长（{len(title)} 字），那在文档里就是一句话不是一个标题。"
            "压到十几个字以内再调一次。"
        )
    if len(body) < CONTENT_MIN_CHARS:
        return (
            "正文太短，像是没写完。这一节要写的是**他已经说定的内容**，"
            "把他刚才那几句整理进去再调一次；他要是什么都还没说，就先别写。"
        )
    if len(body) > CONTENT_MAX_CHARS:
        return f"这一节太长了（{len(body)} 字）。拆成两节分开写，或者只留他真正说定的部分。"

    # 落盘在前端那一帧里（见模块开头）。这里回给模型的话同时也是**给它的行为指令**：
    # 不说这一句，它很容易把刚写进文档的同一段又在聊天里贴一遍，那这一轮就白干了。
    return (
        f"已经把「{title}」这一节写进他的 {DOC_PATH}，他左边能直接看到。\n"
        "接下来在对话里只说一句「这节我写进去了，你看一眼」，再问下一个决定 —— "
        "**不要把这节内容在聊天里再贴一遍**。"
    )


# ═══════════════════════════════════════
#  官方文档：拉下来放进他的项目
# ═══════════════════════════════════════

# 文件名不写「框架文档」以外的层级 —— 挂在 docs/ 下面和学生自己的文档是邻居，
# 删起来也干净（整个子目录删掉就行）。
FRAMEWORK_DOC_DIR = "docs/框架文档"

FRAMEWORK_DOC_TOOL = "fetch_framework_docs"


# 认不出的名字**不是死路**。这句话是这次故障的正对靶心：以前回的是「只能取这几个」，
# 教练读到就是"那算了"，于是转头跟学生说「Vue 的拉不了，你去看 vuejs.org」——
# 把学生推出了产品。现在认不出来只说明"不在快捷表里"，下一步是自己去找官网。
_URLS_ROUTE = (
    "**如果它确实是他在用的技术，认不出不等于拉不到**：去搜它的官方文档页，"
    "把地址放进 urls 再调一次。"
)


def _as_list(raw: object) -> list:
    """把一个可能是列表、也可能是**列表的字符串写法**的东西摊成列表。

    两种形状都要收，因为模型两种都发：实测它把 `urls` 发成了
    `'["https://svelte.dev/...", "https://svelte.dev/kit/..."]'` 这么一整个字符串。
    以前这里把字符串当成"只有一个元素"，于是那一整串被当成一个网址，谁都取不到。
    """
    if isinstance(raw, (list, tuple)):
        return list(raw)
    text = str(raw or "").strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return [raw]      # 长得像数组但不是合法 JSON，当普通值处理，别吞掉
        if isinstance(parsed, list):
            return parsed
    return [raw]


# `fetch_framework_docs` 的参数形状，收在这里是因为**校验发生在工具函数跑起来之前**：
# 签名直接写 `list[str]` 时，模型发来那串 JSON 字符串会被 pydantic 当场拒掉，异常一路
# 穿过 AgentExecutor 把整条流打断 —— 而且模型**看不到**这个错误（它只看到流断了），
# 下一轮还会原样再发一遍。`field_validator(mode="before")` 在校验之前跑，所以两种形状
# 都收得下来；对外仍然只承诺数组（它不改 schema）—— 介绍另一种写法等于教模型偷懒。
#
# **类不要写 docstring**：pydantic 会把它整段塞进 schema 的 description，也就是发给模型。
# 上面这段话是写给维护者的，模型读到只会困惑。
class _DocSourcesArgs(BaseModel):
    frameworks: list[str] = Field(
        default_factory=list,
        description="注册表里认得的技术 id，会展开成挑好的那几页（也进缓存）。",
    )
    urls: list[str] = Field(
        default_factory=list,
        description="你自己找到的官方文档页地址，用在注册表里没有的技术上。",
    )

    @field_validator("frameworks", "urls", mode="before")
    @classmethod
    def _accept_json_string(cls, value: object) -> list:
        return _as_list(value)


def resolve_doc_sources(
    frameworks: object, urls: object
) -> tuple[list[dict], list[str], list[str]]:
    """把「框架名 ＋ 网址」解析成 (认得的框架, 认不出的名字, 可用的网址)。

    **工具的执行和帧的生成都要用它。** 两处各写一遍的话，某天注册表改了、只更新了一处，
    结果就是"工具说认出来了、帧里却是空的" —— 教练以为拉好了，学生那边什么都没发生。
    """
    known: list[dict] = []
    unknown: list[str] = []
    for item in _as_list(frameworks):
        name = str(item or "").strip()
        if not name:
            continue
        framework = get_framework(name)
        if framework is None:
            unknown.append(name)
            continue
        entry = {"id": framework["id"], "name": framework["name"]}
        if entry not in known:
            known.append(entry)

    # 网址原样收着 —— 认不认得出这个站、抓不抓得开，都不是这一层的事
    # （前者判不出来，后者由 web_page.check_fetchable_url 逐跳拦）。
    pages: list[str] = []
    for item in _as_list(urls):
        url = str(item or "").strip()
        if url and url not in pages:
            pages.append(url)
    return known, unknown, pages


@tool(args_schema=_DocSourcesArgs)
async def fetch_framework_docs(frameworks: list[str], urls: list[str]):
    """（描述在下面按注册表生成 —— 别在这里写，会漂）"""
    known, unknown, pages = resolve_doc_sources(frameworks, urls)

    if not known and not pages:
        if unknown:
            # 认不出的名字要一个个说出来，不能只回一句"没有可取的"
            return f"这些名字我认不出来：{'、'.join(unknown)}。{_URLS_ROUTE}"
        return (
            "没给出要取的东西。认得的可以传 id："
            f"{'、'.join(item['id'] for item in catalogue())}；"
            f"表里没有的把官方文档页地址放进 urls。"
        )

    lines: list[str] = []
    if known:
        names = "、".join(item["name"] for item in known)
        lines.append(f"正在把 {names} 的官方文档放进他的 {FRAMEWORK_DOC_DIR}/。")
    if pages:
        lines.append(f"正在把你给的 {len(pages)} 个地址抓下来放进他的 {FRAMEWORK_DOC_DIR}/。")
    if unknown:
        # 认不出的名字要说出来，不能只处理认得的那半 —— 教练会以为全都拉到了。
        # 顺带给它下一步，否则这几个名字就这么没了。
        lines.append(f"（这几个名字我不认识，没拉：{'、'.join(unknown)}。{_URLS_ROUTE}）")
    lines.append(
        "他那边还要几秒钟才写好，**这一轮先不要让他打开那个目录** —— "
        "等他下次说话、或者你说完这段之后，再让他去左边看。"
    )
    return "\n".join(lines)


def _framework_doc_description() -> str:
    """按注册表拼工具描述。

    **不手抄框架清单**：描述里写死一份、注册表里又一份，加框架时漏改一处，教练就会拿着
    一个调不通的名字去调 —— 而它只会看到"我不认识这个名字"，无从知道自己写错了什么。
    """
    rows = "\n".join(
        f"      · {item['id']:<10} —— {item['name']}（{item['source_count']} 篇）"
        for item in catalogue()
    )
    return (
        "把官方文档抓下来放进学生的项目里（"
        f"{FRAMEWORK_DOC_DIR}/），他写代码时手边就有，不用去别处查。\n\n"
        "调用时机：他**已经谈定了**用哪个技术，或者明确说要看某份官方资料。"
        "**他还在挑的时候不要调** —— 那等于替他做了选择。\n\n"
        "两种给法，一次可以都给：\n"
        "  · frameworks —— 表里认得的，传 id，会展开成挑好的那几页（也进缓存）：\n"
        f"{rows}\n"
        "  · urls —— **表里没有的技术走这里**，你自己找到的官方文档页地址。\n\n"
        "**表里没有不等于拉不到。** 他要用的是别的技术时，去搜它的官网 / 官方仓库文档，"
        "把地址放进 urls —— 别对学生说「这个我拉不了」，那等于把他推去站外。\n\n"
        "**只传官方文档**（框架官网、官方仓库的 docs / README）。别传二手博客："
        "博客常是照着旧版本写的，读起来却和官方文档一样肯定。\n\n"
        "他手上已经有一份了就别重复拉：先看【学生工作区】里有没有那个目录，"
        "有就先让他看，缺哪个再补哪个（可以只传缺的那个）。\n\n"
        # 以前这里写着「目录名取它的域名」—— 那是**告诉它怎么算路径**，而它不需要算：
        # 目录是服务端算的、学生左边自己看得到。代价实测发生过：教练调用完报告
        # `docs/框架文档/fastapi.api.tiangolo.com/`，而走 frameworks 那条路真实目录是 `FastAPI/`
        # —— 它把 urls 那条规则套到了 frameworks 上，报了一个学生照着找不到的路径。
        "**你没收到的东西别报。** 这个工具回给你的是「正在把 … 放进他的 "
        f"{FRAMEWORK_DOC_DIR}/」—— 就到这里：具体的子目录名、有几页、里面是哪几篇，"
        "服务端算好之后学生自己会在左边看到。你没见过的路径不要写进回复里，"
        "他照着找是找不到的。"
    )


fetch_framework_docs.description = _framework_doc_description()
