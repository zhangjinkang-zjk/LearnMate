# -*- coding: utf-8 -*-
"""只重渲染升级路径：模板换代后不重跑 LLM / TTS。

起因：视频模板改一处（比如加自动跟随）就要 bump PRESENTATION_TEMPLATE_VERSION，
而 `generate()` 每次都 `Video.create()` 新建记录并把每个 slide 的 TTS 全部重做，
PPT 未命中缓存还要重跑 LLM —— 1~3 分钟/条，且每调一次模板都要再等一遍。

但 chapters_json 里已经存着 slides / audio_url / word_timestamps，盘上的音频也还在，
所以"HTML 是旧模板"这件事只需要换掉那层外壳。这里钉住的就是这条短路。
"""

import json
from types import SimpleNamespace

import pytest

from backend.src.models import resource_model
from backend.src.service.path import service as path_service
from backend.src.service.video import service as video_service


class FakeQuery:
    """只实现本链路用到的 order_by().first()。"""

    def __init__(self, value):
        self._value = value

    def order_by(self, *_args):
        return self

    async def first(self):
        return self._value


class FakeVideoRecord:
    def __init__(self, chapters=None):
        self.id = 55
        self.file_url = "/static/presentations/old_00000000.html"
        self.chapters_json = None if chapters is None else json.dumps(chapters, ensure_ascii=False)
        self.saved = False

    async def save(self):
        self.saved = True


class FakeResource:
    def __init__(self, resource_id, file_url=None, content=None):
        self.id = resource_id
        self.file_url = file_url
        self.content = content
        self.saved = False

    async def save(self):
        self.saved = True

    async def delete(self):
        raise AssertionError("这条链路不该删记录")


class FakeGeneratedResource:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []

    def filter(self, **_kwargs):
        return FakeQuery(self.existing)

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return FakeResource(99, file_url=kwargs.get("file_url"))


class FakeUser:
    @staticmethod
    def filter(**_kwargs):
        return FakeQuery(object())


def _chapters(with_audio: bool = True, chapters: int = 2, slides: int = 2) -> list[dict]:
    """构造一份形状与真实 chapters_json 一致的章节数组。"""
    out = []
    for ci in range(chapters):
        sl = []
        for si in range(slides):
            sl.append({
                "title": f"第{ci}-{si}页",
                "blocks": [{"text": "正文"}],
                "audio_url": f"/static/audio/7/{ci}{si}abcdef.mp3" if with_audio else None,
                "duration_ms": 30000,
                "word_timestamps": [{"text": "正", "offset_ms": 0, "duration_ms": 200}],
            })
        out.append({
            "type": "ppt",
            "title": f"章{ci}",
            "slides": sl,
            "total_duration_ms": 60000,
        })
    return out


def _install(monkeypatch, tmp_path, record):
    """VIDEOS_DIR 与 Video 都是 video.service 的模块级名字，patch 在它自己的命名空间上。"""
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(
        video_service, "Video",
        SimpleNamespace(filter=lambda **_kwargs: FakeQuery(record)),
    )


def _written_name(file_url: str) -> str:
    return file_url.split("?", 1)[0].rsplit("/", 1)[-1]


# ── 数据完备 → 真的重渲染出成品 ──


@pytest.mark.asyncio
async def test_rerender_writes_new_html_with_current_template(monkeypatch, tmp_path):
    record = FakeVideoRecord(_chapters())
    _install(monkeypatch, tmp_path, record)

    result = await video_service.rerender_presentation_html(55, "测试主题")

    assert result is not None
    assert result["id"] == 55
    assert result["file_url"].startswith("/static/presentations/")

    written = tmp_path / _written_name(result["file_url"])
    assert written.exists(), "重渲染必须真的落盘"

    body = written.read_text(encoding="utf-8")
    # 版本戳在文件第一行，_presentation_html_is_usable 靠它判断是否过期
    assert body.startswith(f"<!-- template-version:{video_service.PRESENTATION_TEMPLATE_VERSION} -->")
    # 音频段必须带进去：少了这个渲染出来是个哑的 deck，而缓存检查看不出来
    assert "abcdef.mp3" in body
    assert "word_timestamps" in body

    # 返回形态必须与 generate() 对齐（带 ?v=），但记录里存的仍是裸路径
    assert result["file_url"].endswith(f"?v={video_service.PRESENTATION_TEMPLATE_VERSION}")

    # Video 记录要跟着指向新文件，否则 SSE / 按 id 取视频的地方还指着旧文件
    assert record.saved is True
    assert record.file_url == result["file_url"].split("?", 1)[0]

    # 跨模块往返：渲染时盖的版本戳，必须被"是否过期"的检查认可。
    # 两边一旦不一致，每次打开视频都会判定过期 → 无限重新生成。
    assert path_service._presentation_html_is_usable(result["file_url"]) is True


@pytest.mark.asyncio
async def test_rerender_uses_a_fresh_filename(monkeypatch, tmp_path):
    """必须换新文件名：旧文件要留着，等记录指向新文件之后才由调用方清理。"""
    record = FakeVideoRecord(_chapters())
    _install(monkeypatch, tmp_path, record)

    first = await video_service.rerender_presentation_html(55, "测试主题")
    second = await video_service.rerender_presentation_html(55, "测试主题")

    assert _written_name(first["file_url"]) != _written_name(second["file_url"])
    assert len(list(tmp_path.iterdir())) == 2


# ── 数据不全 → 拒绝重渲染，交回完整生成 ──


@pytest.mark.asyncio
async def test_rerender_bails_when_audio_incomplete(monkeypatch, tmp_path):
    """生成中途（音频还在后台补）重渲染会产出没有声音的 deck，必须拒绝。"""
    record = FakeVideoRecord(_chapters(with_audio=False))
    _install(monkeypatch, tmp_path, record)

    assert await video_service.rerender_presentation_html(55, "测试主题") is None
    assert list(tmp_path.iterdir()) == [], "拒绝时不该写任何文件"
    assert record.saved is False


@pytest.mark.asyncio
async def test_rerender_bails_when_only_some_slides_have_audio(monkeypatch, tmp_path):
    chapters = _chapters()
    chapters[1]["slides"][1]["audio_url"] = None      # 只差一页也不行
    record = FakeVideoRecord(chapters)
    _install(monkeypatch, tmp_path, record)

    assert await video_service.rerender_presentation_html(55, "测试主题") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [None, FakeVideoRecord(None), FakeVideoRecord([])])
async def test_rerender_returns_none_for_unusable_records(monkeypatch, tmp_path, record):
    """记录不存在 / chapters_json 为空 / 章节数组为空 —— 都只是"不能重渲染"，不是错误。"""
    _install(monkeypatch, tmp_path, record)

    assert await video_service.rerender_presentation_html(55, "测试主题") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_rerender_survives_broken_json(monkeypatch, tmp_path):
    record = FakeVideoRecord()
    record.chapters_json = "{这不是 JSON"
    _install(monkeypatch, tmp_path, record)

    assert await video_service.rerender_presentation_html(55, "测试主题") is None
    assert list(tmp_path.iterdir()) == []


# ── _create_video_html 的取舍：优先重渲染，失败才全量生成 ──


def _install_create_env(monkeypatch, tmp_path, existing_row, rerender, generate):
    """_create_video_html 里这两处都是函数内延迟导入，属性在调用时才解析，
    所以要 patch 在源模块 video.service 上；GeneratedResource 同理。"""
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(video_service, "rerender_presentation_html", rerender)
    monkeypatch.setattr(video_service, "generate", generate)
    monkeypatch.setattr(resource_model, "GeneratedResource", FakeGeneratedResource(existing_row))
    monkeypatch.setattr(path_service, "GeneratedResource", FakeGeneratedResource(existing_row))
    monkeypatch.setattr(path_service, "User", FakeUser)
    # 旧产物按"文件已不在"处理，确保走不到缓存命中分支
    monkeypatch.setattr(path_service, "_remove_presentation_file", lambda *_a, **_k: None)


@pytest.fixture
def stale_row():
    """file_url 带 ?v= 且磁盘上没有对应文件 → _presentation_html_is_usable 判为不可用。"""
    return FakeResource(
        41,
        file_url="/static/presentations/old_00000000.html?v=visual-v6",
        content=json.dumps({"presentation_id": 55}),
    )


@pytest.fixture
def ppt_record():
    return SimpleNamespace(id=5, content="")


@pytest.mark.asyncio
async def test_create_html_prefers_rerender_over_full_generate(
    monkeypatch, tmp_path, stale_row, ppt_record
):
    calls = []

    async def fake_rerender(video_id, topic):
        calls.append(("rerender", video_id))
        return {"id": video_id, "file_url": "/static/presentations/new_11111111.html"}

    async def must_not_generate(*_args, **_kwargs):
        calls.append(("generate", None))
        raise AssertionError("模板换代时不该重跑完整生成（LLM + TTS）")

    _install_create_env(monkeypatch, tmp_path, stale_row, fake_rerender, must_not_generate)

    result = await path_service._create_video_html("测试主题", 7, ppt_record)

    assert calls == [("rerender", 55)]
    assert result == {
        "html_id": 41,
        "presentation_id": 55,
        "file_url": "/static/presentations/new_11111111.html",
    }
    # 复用同一行而不是新建，避免行堆积、也让 html_id 稳定
    assert stale_row.file_url == "/static/presentations/new_11111111.html"
    assert stale_row.saved is True


@pytest.mark.asyncio
async def test_create_html_falls_back_to_full_generate(
    monkeypatch, tmp_path, stale_row, ppt_record
):
    calls = []

    async def fake_rerender(video_id, topic):
        calls.append("rerender")
        return None      # 音频不全 / 记录坏掉

    async def fake_generate(topic, user_id, **_kwargs):
        calls.append("generate")
        return {"id": 77, "file_url": "/static/presentations/gen.html?v=visual-v7"}

    _install_create_env(monkeypatch, tmp_path, stale_row, fake_rerender, fake_generate)

    result = await path_service._create_video_html("测试主题", 7, ppt_record)

    assert calls == ["rerender", "generate"]
    assert result["presentation_id"] == 77
    assert result["file_url"] == "/static/presentations/gen.html?v=visual-v7"
    assert stale_row.saved is True


@pytest.mark.asyncio
async def test_create_html_skips_rerender_without_existing_record(
    monkeypatch, tmp_path, ppt_record
):
    """从没生成过 → 没有 presentation_id，不该去试重渲染。"""
    calls = []

    async def fake_rerender(video_id, topic):
        calls.append("rerender")
        return {"id": video_id, "file_url": "/nope"}

    async def fake_generate(topic, user_id, **_kwargs):
        calls.append("generate")
        return {"id": 88, "file_url": "/static/presentations/fresh.html?v=visual-v7"}

    _install_create_env(monkeypatch, tmp_path, None, fake_rerender, fake_generate)

    result = await path_service._create_video_html("测试主题", 7, ppt_record)

    assert calls == ["generate"]
    assert result["presentation_id"] == 88


@pytest.mark.asyncio
async def test_everything_failing_returns_none(monkeypatch, tmp_path, stale_row, ppt_record):
    """重渲染和全量生成都失败 → None，调用方保留旧记录（"生成完毕但没有资料"的反面）。"""

    async def fake_rerender(video_id, topic):
        return None

    async def failing_generate(*_args, **_kwargs):
        return {"error": "llm timeout"}

    _install_create_env(monkeypatch, tmp_path, stale_row, fake_rerender, failing_generate)

    assert await path_service._create_video_html("测试主题", 7, ppt_record) is None
    assert stale_row.saved is False, "全部失败时不能改动旧记录"
