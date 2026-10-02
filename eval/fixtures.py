# -*- coding: utf-8 -*-
"""评估时那个**固定的世界** —— 工具背后站着的东西。

教练是**真的** agent：真 persona、真工具表（名字、描述、参数 schema 全部来自生产）、
真模型、真 agent 循环，"什么时候该调哪个工具"是它自己决定的。这里固定的只有**世界**：
工具执行时要去读的东西，返回一份写死的值。

为什么必须固定，而不是让它们真去跑：

- **有的要花钱。** `web_search` 走博查，按次计费。断一次言花一次钱，跑三轮就是三份。
- **有的要动用户的库。** `search_knowledge_base` / `read_portrait` / `search_memory` /
  `get_used_history` 都要读 MySQL，而评估不该往生产库里写测试数据。
- **不固定就不可比。** 搜索引擎每天返回的不一样，同一个场景跑两遍得到的对话不一样，
  于是"这次比上次好"这句话永远说不清是改动带来的还是世界变了。

**这些东西不参与判分。** 判据判的是教练怎么说话、怎么选工具、有没有拿工具结果当真 ——
工具背后那份数据是布景，不是被测对象。

想换成真调：把 `FIXED_WORLD` 里对应的键删掉就行 —— 删掉的那个工具会退回生产实现
（见 `coach_bridge._install_fixed_world`）。
"""

# 每条固定值有两种写法：
#   字符串 —— 不管参数是什么都返回它
#   函数   —— 收一个 kwargs 字典（模型给的工具参数），返回字符串
#
# 文本形态是照着生产里各工具的真实返回抄的（同样的抬头、同样的句式），
# 否则模型会察觉"这个工具的输出长得不对"，行为跟着变，评估就测歪了。

# 搜索引擎"认识"的官网。**查询里提到哪个，就返回哪个那一条。**
#
# 这是布景，不是被测对象：真实世界里搜索引擎当然找得到官网，而评估要测的是
# "它会不会去搜、搜完会不会把地址交给那个工具" —— 所以世界这边必须给得出官网地址，
# 否则测的就变成"它运气好不好"了。
_KNOWN_DOCS = (
    ("svelte", "Svelte", "https://svelte.dev/docs/svelte/overview"),
    ("django", "Django", "https://docs.djangoproject.com/en/stable/intro/overview/"),
    ("fastapi", "FastAPI", "https://fastapi.tiangolo.com/tutorial/"),
    ("langgraph", "LangGraph", "https://docs.langchain.com/oss/python/langgraph/overview"),
    ("langchain", "LangChain", "https://docs.langchain.com/oss/python/langchain/quickstart"),
    ("vue", "Vue", "https://vuejs.org/guide/introduction.html"),
    ("vite", "Vite", "https://vite.dev/guide/"),
)

# 没搜到时的哨兵。**用生产里那个**（`ai_core/tools/search.py`）—— 换一个自己编的，
# 模型面对的就是一个它没见过的信号，行为会跟着变。
_NO_RESULTS = "【WEB_SEARCH_NO_RESULTS】"


def _web_search(kwargs: dict) -> str:
    query = str(kwargs.get("query") or "").strip()
    lowered = query.lower()
    hits = [item for item in _KNOWN_DOCS if item[0] in lowered or item[1].lower() in lowered]
    if not hits:
        return f"{_NO_RESULTS}未找到与「{query}」相关的结果"

    lines = [f"搜索「{query}」结果："]
    for index, (_, name, url) in enumerate(hits, 1):
        lines += [
            f"{index}. {name} 官方文档",
            f"   {name} 的官方文档与入门教程。",
            f"   {url}",
            f"   来源：{name} 官方文档",
        ]
    return "\n".join(lines)


def _read_web_page(kwargs: dict) -> str:
    url = str(kwargs.get("url") or "").strip()
    return (
        f"网页正文（{url}）：\n\n"
        "# 起步\n\n"
        "建立一个应用，先把它跑起来，再往上加东西。\n\n"
        "```python\nfrom fastapi import FastAPI\n\napp = FastAPI()\n```\n\n"
        "开发时用命令行工具启动，它默认打开自动重载。"
    )


FIXED_WORLD: dict = {
    # 知识库故意是空的：**让教练练"查不到就照实说"**，而不是给它一段资料去引用。
    # 给内容的话，它会引用一段评估者编的文本，而判据无从判断那是真是假。
    "search_knowledge_base": "未在知识库中检索到与该查询相关的片段。",
    # 画像给一点点，够它知道方向，不够它拿去当论据。
    "read_portrait": "学习方向：智能体开发。目标：能独立做出一个带工具调用的问答应用。",
    "search_memory": "没有检索到相关的长期记忆。",
    "get_used_history": "当前聊天组暂无历史记录。",
    "web_search": _web_search,
    "read_web_page": _read_web_page,
}
