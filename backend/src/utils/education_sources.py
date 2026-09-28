"""教育来源白名单 — 检索合规来源的唯一事实来源

视频搜索和联网检索都从这里取域名清单，通过博查的 include 参数在 API 层限定范围；
标注来源时用这里的 label，取不到再回退搜索服务返回的 siteName。

tier 只描述来源性质，不代表能否嵌入播放：
    embed   — 该来源family有官方外链播放器（实际能否嵌由 BVID 能否解出决定）
    course  — 官方课程平台，只能跳转
    reading — 图文 / 代码参考，只能跳转
"""

from urllib.parse import urlparse

EDUCATION_SOURCES: list[dict] = [
    # B 站是唯一能内嵌的：player.bilibili.com/player.html?bvid=
    # b23.tv 短链解不出 BVID，会退化成只给跳转链接
    {"tier": "embed", "domains": ["bilibili.com", "b23.tv"], "label": "B站"},
    # smartedu.cn 覆盖 higher. / basic. 等子域（按域后缀匹配）
    {"tier": "course", "domains": ["smartedu.cn"], "label": "国家智慧教育平台"},
    {"tier": "course", "domains": ["nvic.com.cn"], "label": "国家职业教育智慧教育平台"},
    {"tier": "course", "domains": ["icourse163.org"], "label": "中国大学MOOC"},
    {"tier": "course", "domains": ["xuetangx.com"], "label": "学堂在线"},
    {"tier": "course", "domains": ["open.163.com"], "label": "网易公开课"},
    {"tier": "course", "domains": ["imooc.com"], "label": "慕课网"},
    {"tier": "reading", "domains": ["developer.mozilla.org"], "label": "MDN"},
    {"tier": "reading", "domains": ["runoob.com"], "label": "菜鸟教程"},
    {"tier": "reading", "domains": ["juejin.cn"], "label": "掘金"},
    {"tier": "reading", "domains": ["github.com"], "label": "GitHub"},
    {"tier": "reading", "domains": ["arxiv.org"], "label": "arXiv"},
]

# 注意：腾讯课堂（ke.qq.com）已于 2024-10-01 正式停止运营，不要加回来。


def _host_of(url: str) -> str:
    """取 URL 的主机名并去掉 www. 前缀，解析失败返回空串"""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domain: str) -> bool:
    """主机名等于该域名，或它的子域（space.bilibili.com 命中 bilibili.com）"""
    if not host or not domain:
        return False
    return host == domain or host.endswith(f".{domain}")


def _find_source(url: str) -> dict | None:
    """按域名找白名单条目，未命中返回 None"""
    host = _host_of(url)
    for source in EDUCATION_SOURCES:
        if any(_matches(host, domain) for domain in source["domains"]):
            return source
    return None


def include_domains(*tiers: str) -> str:
    """拼成博查 include 参数（逗号分隔）。共 13 个域名，远低于接口上限。

    不传 tiers 时返回全部；传了只返回匹配的档位，例如 include_domains("embed")。
    分档查询是必要的：embed 档（B 站）的真实视频页在它的结果里只占少数，
    和十几个课程站点混在一次查询里会被挤掉名额，一条都剩不下。
    """
    wanted = set(tiers)
    return ",".join(
        domain
        for source in EDUCATION_SOURCES
        if not wanted or source["tier"] in wanted
        for domain in source["domains"]
    )


def label_for(url: str) -> str:
    """按域名给出中文来源名；不属于白名单时返回空串，由调用方决定回退"""
    source = _find_source(url)
    return str(source["label"]) if source else ""


def tier_for(url: str) -> str:
    """返回 embed / course / reading；不属于白名单时返回空串"""
    source = _find_source(url)
    return str(source["tier"]) if source else ""


def is_education_source(url: str) -> bool:
    """URL 是否落在白名单内（用于过滤白名单外的结果）"""
    return bool(label_for(url))
