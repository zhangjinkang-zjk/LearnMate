# -*- coding: utf-8 -*-
"""官方文档抓取的缓存层。

缓存最坏的失败方式不是"没生效"，而是**生效了但没人知道** —— 文件抬头写着"刚抓的"，
内容是七天前的。所以这里除了"第二次不重抓"，还专门盯着日期戳有没有跟着缓存走。
"""
import pytest

from backend.src.service.advanced import reference_docs as refdocs


@pytest.fixture
def fake_cache(monkeypatch):
    """用内存字典替掉 Redis。`cache_get`/`cache_set` 本来就是异常静默降级的，
    真连 Redis 测等于把测试挂在外部服务上。"""
    store: dict = {}

    async def _get(key):
        return store.get(key)

    async def _set(key, value, ttl):
        store[key] = value

    monkeypatch.setattr(refdocs, "cache_get", _get)
    monkeypatch.setattr(refdocs, "cache_set", _set)
    return store


@pytest.fixture
def fake_fetch(monkeypatch):
    """替掉真正的抓取，记下每次都抓了哪些 URL。"""
    calls: list[str] = []

    async def _fetch(url):
        calls.append(url)
        return f"{url} 的正文", ""

    monkeypatch.setattr(refdocs, "fetch_readable_text", _fetch)
    return calls


# ═══════════════════════════════════════
#  命中与不命中
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_the_second_fetch_comes_from_the_cache(fake_cache, fake_fetch):
    first_text, _, _ = await refdocs._fetch_one("https://example.com/a")
    second_text, _, _ = await refdocs._fetch_one("https://example.com/a")

    assert first_text == second_text
    assert len(fake_fetch) == 1


@pytest.mark.asyncio
async def test_different_urls_do_not_share_a_slot(fake_cache, fake_fetch):
    await refdocs._fetch_one("https://example.com/a")
    await refdocs._fetch_one("https://example.com/b")

    assert len(fake_fetch) == 2


@pytest.mark.asyncio
async def test_the_cached_page_keeps_the_date_it_was_actually_fetched(fake_cache, fake_fetch):
    """**这条是这层缓存存在的意义里最容易做错的一处。**

    文件是"刚写的"，内容不是。抬头写"写文件那一刻"的话，学生会以为手里是刚拉的，
    而它可能是七天前的 —— 那正是"过时的 API 比没有更糟"那个坑。
    """
    _, _, first_stamp = await refdocs._fetch_one("https://example.com/a")
    _, _, second_stamp = await refdocs._fetch_one("https://example.com/a")

    assert first_stamp and second_stamp
    assert first_stamp == second_stamp, "命中缓存后时间戳被改写成了「现在」"


# ═══════════════════════════════════════
#  谁能进缓存：按域名判，不按"谁在调"判
# ═══════════════════════════════════════

def test_the_plan_only_caches_pages_on_registered_domains():
    plan = refdocs._plan_fetches([], [
        "https://vuejs.org/guide/quick-start.html",   # 登记过的域名
        "https://blog.example.com/vue-tutorial",      # 不知道是谁的站
    ])

    assert [item["cacheable"] for item in plan] == [True, False]


@pytest.mark.asyncio
async def test_a_page_on_a_registered_domain_comes_from_the_cache(fake_cache, fake_fetch):
    await refdocs._fetch_one("https://vuejs.org/guide/quick-start.html", True)
    await refdocs._fetch_one("https://vuejs.org/guide/quick-start.html", True)

    assert len(fake_fetch) == 1


@pytest.mark.asyncio
async def test_a_page_off_the_registry_is_never_cached(fake_cache, fake_fetch):
    """**这条是访问控制那条线，删了它缓存就成了越权读的口子。**

    以前这条规矩是靠"只服务注册表"守住的 —— 那时能进这个函数的 URL 只有登记过的那几条。
    现在教练也能塞任意地址进来，所以改由**域名**来判。登进缓存的页，下一个人不用经过
    原站就能拿到内容；对那些带 token、设了访问控制的地址，那等于绕过原站。
    """
    await refdocs._fetch_one("https://someone-blog.example/post?id=secret", False)
    await refdocs._fetch_one("https://someone-blog.example/post?id=secret", False)

    assert len(fake_fetch) == 2
    assert fake_cache == {}, "不该有任何东西被写进缓存"


# ═══════════════════════════════════════
#  教练自己找的那些地址
# ═══════════════════════════════════════

def test_url_sources_get_their_own_folder_named_after_the_domain():
    """**目录名取域名，不猜产品名。** 我们只知道它落在哪个站上。"""
    plan = refdocs._plan_fetches([], [
        "https://vuejs.org/guide/quick-start.html",
        "https://vuejs.org/guide/introduction.html",
        "https://docs.trychroma.com/docs/collections/manage-collections",
    ])

    assert [item["folder"] for item in plan] == ["vuejs.org", "vuejs.org", "trychroma.com"]
    # 每个目录各自从 1 开始编号 —— 学生看到的是 `vuejs.org/1-… 2-…`
    assert [item["index"] for item in plan] == [1, 2, 1]


def test_a_url_gives_a_readable_file_name():
    plan = refdocs._plan_fetches([], [
        "https://vuejs.org/guide/quick-start.html",
        "https://ai.pydantic.dev/agents/",
        "https://sbert.net/",
    ])

    assert [item["source"]["label"] for item in plan] == ["quick-start", "agents", "sbert.net"]


@pytest.mark.asyncio
async def test_collect_writes_the_urls_the_coach_gave(fake_cache, fake_fetch):
    """工具那边给的地址，一路要走到文件路径上。"""
    result = await refdocs.collect([], ["https://vuejs.org/guide/quick-start.html"])

    assert [item["path"] for item in result["files"]] == ["vuejs.org/1-quick-start.md"]


@pytest.mark.asyncio
async def test_a_name_and_a_url_can_be_collected_in_one_call(fake_cache, fake_fetch):
    result = await refdocs.collect(["fastapi"], ["https://vuejs.org/guide/quick-start.html"])

    folders = {item["path"].split("/")[0] for item in result["files"]}
    assert folders == {"FastAPI", "vuejs.org"}


# ═══════════════════════════════════════
#  失败不缓存
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_a_failure_is_not_cached(monkeypatch, fake_cache):
    """抓不到**不进缓存**：文档站改版、临时 502 都可能明天就好了，
    把"抓不到"缓存七天等于七天里谁都拿不到。"""
    calls: list[str] = []

    async def _failing(url):
        calls.append(url)
        return "", "请求超时"

    monkeypatch.setattr(refdocs, "fetch_readable_text", _failing)

    text, note, _ = await refdocs._fetch_one("https://example.com/a")
    assert text == "" and note == "请求超时"

    await refdocs._fetch_one("https://example.com/a")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_cache_entry_without_text_is_ignored(fake_cache, fake_fetch):
    """脏缓存（结构对但正文空）要当成没命中，不能把空正文当结果发出去。

    key 用 `_entry_key` 拼而不是手写一份 —— 手拼的话 key 一改这条测试就永远命不中，
    变成一条只会绿的空测试。
    """
    fake_cache[refdocs._entry_key("https://example.com/a")] = {
        "text": "", "note": "", "fetched_at": "2020-01-01T00:00:00+00:00",
    }

    text, _, stamp = await refdocs._fetch_one("https://example.com/a")

    assert text and stamp != "2020-01-01T00:00:00+00:00"
    assert len(fake_fetch) == 1


# ═══════════════════════════════════════
#  抽取器换版本 → 旧产物作废
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_an_entry_written_by_an_older_extractor_is_not_reused(monkeypatch, fake_cache, fake_fetch):
    """**这条防的是"修了等于没修"。**

    缓存里的正文是**旧代码抽出来的**。改了抽取逻辑却不动 key，下一个重拉的
    学生命中同一份旧文字，看到的和修之前一模一样 —— 他会说"你们没修"，
    而真正的原因在这里。所以 `EXTRACT_VERSION` 必须在 key 里。

    断言的是"又抓了一次"（调用次数）而不是内容：内容一样才是这里要重现的现场。
    """
    await refdocs._fetch_one("https://example.com/a")
    assert len(fake_fetch) == 1

    monkeypatch.setattr(refdocs, "EXTRACT_VERSION", "v-next")

    await refdocs._fetch_one("https://example.com/a")
    assert len(fake_fetch) == 2, "抽取器换了版本，旧产物还在被当成结果发出去"


# ═══════════════════════════════════════
#  一路带到产出
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_collect_puts_the_stamp_into_every_file(fake_cache, fake_fetch):
    """`collect` 要把时间戳放进去 —— 前端抬头写的就是它。"""
    result = await refdocs.collect(["fastapi"])

    assert result["files"], "注册表里 fastapi 有好几页，不该一个都没抓到"
    for item in result["files"]:
        assert item["fetched_at"], f"{item['path']} 没有时间戳"
        assert item["url"].startswith("https://")
