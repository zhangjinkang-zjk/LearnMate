# -*- coding: utf-8 -*-
"""路径视频：缓存键、失败回滚、作业注册表。

对应三个已确认的缺陷：
  - file_url 带 ?v= 版本参数时，手写的 split("/")[-1] 会把 query 当成文件名，
    拼出的路径永远不存在 → 缓存从未命中过（每次都全量重生成）
  - 生成前先删记录、失败不回滚 → 前端看到"生成完毕但没有资料"
  - 生成挂在 HTTP 请求上跑几分钟 → 前端必然超时（改为后台作业 + 状态查询）
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.src.models import resource_model
from backend.src.service.path import path_video_jobs
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


class FakeResource:
    def __init__(self, resource_id, file_url=None, content=None):
        self.id = resource_id
        self.file_url = file_url
        self.content = content
        self.deleted = False
        self.saved = False

    async def delete(self):
        self.deleted = True

    async def save(self):
        self.saved = True


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


async def _settle(predicate, attempts: int = 500) -> bool:
    """让出事件循环直到条件成立，或放弃。不依赖计时。"""
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


def _write_html(directory, name: str, version: str) -> str:
    """写一个带模板版本戳的产物文件，返回它对应的 file_url。"""
    (directory / name).write_text(
        f"<!-- template-version:{version} -->\n<html></html>",
        encoding="utf-8",
    )
    return f"/static/presentations/{name}?v={version}"


def _install_video_env(monkeypatch, tmp_path, generated_resource):
    """两处命名空间都要照顾到：

    - VIDEOS_DIR 由 video.service._presentation_file_path 读它**自己模块**的全局，
      patch path_service 上的那个绑定没用（本次已确认）。
    - _create_video_html 里有一句函数内的 `from ...resource_model import GeneratedResource`，
      函数体里那个名字在调用时才解析，所以必须打在**源模块**上；
      而 generate_path_video 用的是 path_service 顶层的绑定，一并打上。
    """
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(resource_model, "GeneratedResource", generated_resource)
    monkeypatch.setattr(path_service, "GeneratedResource", generated_resource)
    monkeypatch.setattr(path_service, "User", FakeUser)


@pytest.fixture
def ppt_record():
    return SimpleNamespace(id=5, content="")


# ── 缓存键：带 ?v= 的 file_url 必须能定位到磁盘文件 ──


def test_versioned_url_resolves_to_disk_file(monkeypatch, tmp_path):
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    url = _write_html(tmp_path, "LangChain 学习路径_3b309ffe.html", video_service.PRESENTATION_TEMPLATE_VERSION)

    assert path_service._presentation_html_path(url) == tmp_path / "LangChain 学习路径_3b309ffe.html"
    assert path_service._presentation_html_is_usable(url) is True


def test_handwritten_split_would_miss_the_file(monkeypatch, tmp_path):
    """把这个 bug 本身钉住：直接把 split("/")[-1] 拿去拼路径会带上 query。"""
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    url = _write_html(tmp_path, "x_3b309ffe.html", video_service.PRESENTATION_TEMPLATE_VERSION)

    handwritten = tmp_path / url.split("/")[-1]
    correct = tmp_path / url.split("?", 1)[0].rsplit("/", 1)[-1]

    assert not handwritten.exists(), "带 query 的路径不该存在——这正是缓存恒不命中的原因"
    assert correct.exists()


def test_missing_file_and_stale_template_are_not_usable(monkeypatch, tmp_path):
    monkeypatch.setattr(video_service, "VIDEOS_DIR", tmp_path)
    stale = _write_html(tmp_path, "stale_aaaa1111.html", "visual-v0")

    assert path_service._presentation_html_is_usable(stale) is False
    assert path_service._presentation_html_is_usable("/static/presentations/none.html?v=visual-v6") is False
    assert path_service._presentation_html_is_usable(None) is False


# ── 缓存命中：不重新生成、不删记录 ──


@pytest.mark.asyncio
async def test_cache_hit_does_not_regenerate_or_delete(monkeypatch, tmp_path, ppt_record):
    url = _write_html(tmp_path, "cached_aaaa1111.html", video_service.PRESENTATION_TEMPLATE_VERSION)
    row = FakeResource(41, file_url=url, content=json.dumps({"presentation_id": 9}))
    _install_video_env(monkeypatch, tmp_path, FakeGeneratedResource(row))

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("缓存命中时不应调用 generate")

    monkeypatch.setattr(video_service, "generate", must_not_run)

    result = await path_service._create_video_html("topic", 7, ppt_record)

    assert result == {"html_id": 41, "presentation_id": 9, "file_url": url}
    assert row.deleted is False


# ── 失败：旧记录与旧文件都要保留（"生成完毕但没有资料"的反面）──


@pytest.mark.asyncio
async def test_generation_failure_keeps_previous_record_and_file(monkeypatch, tmp_path, ppt_record):
    old_url = _write_html(tmp_path, "old_bbbb2222.html", "visual-v0")  # 旧模板 → 判为不可用
    old_name = "old_bbbb2222.html"
    row = FakeResource(42, file_url=old_url, content="{}")
    _install_video_env(monkeypatch, tmp_path, FakeGeneratedResource(row))

    async def failing_generate(*_args, **_kwargs):
        return {"error": "llm timeout"}

    monkeypatch.setattr(video_service, "generate", failing_generate)

    result = await path_service._create_video_html("topic", 7, ppt_record)

    assert result is None
    assert row.deleted is False, "生成失败不能把旧记录删掉"
    assert row.saved is False
    assert (tmp_path / old_name).exists(), "生成失败不能把旧文件删掉"


# ── 成功：复用同一行、换 file_url、清掉旧文件、不新建行 ──


@pytest.mark.asyncio
async def test_success_reuses_row_and_removes_old_file(monkeypatch, tmp_path, ppt_record):
    old_url = _write_html(tmp_path, "old_bbbb2222.html", "visual-v0")
    new_url = _write_html(tmp_path, "new_cccc3333.html", video_service.PRESENTATION_TEMPLATE_VERSION)
    row = FakeResource(43, file_url=old_url, content="{}")
    generated_resource = FakeGeneratedResource(row)
    _install_video_env(monkeypatch, tmp_path, generated_resource)

    async def ok_generate(*_args, **_kwargs):
        return {"id": 77, "file_url": new_url, "status": "ready"}

    monkeypatch.setattr(video_service, "generate", ok_generate)

    result = await path_service._create_video_html("topic", 7, ppt_record)

    assert result == {"html_id": 43, "presentation_id": 77, "file_url": new_url}
    assert generated_resource.created == [], "应该复用已有行而不是新建"
    assert row.file_url == new_url
    assert row.saved is True
    assert not (tmp_path / "old_bbbb2222.html").exists(), "旧文件应在记录指向新文件后才清理"
    assert (tmp_path / "new_cccc3333.html").exists()


# ── 作业注册表：单飞 + 失败原因可查 ──


@pytest.mark.asyncio
async def test_second_start_attaches_to_same_job():
    release = asyncio.Event()
    calls = []

    async def producer():
        calls.append(1)
        await release.wait()
        return {"path_id": 1}

    first_job, first_is_new = await path_video_jobs.ensure_path_video_job(7, 1, producer)
    second_job, second_is_new = await path_video_jobs.ensure_path_video_job(7, 1, producer)

    assert first_is_new is True
    assert second_is_new is False
    assert first_job is second_job

    release.set()
    assert await _settle(lambda: first_job.state != path_video_jobs.STATE_RUNNING)
    assert first_job.state == path_video_jobs.STATE_READY
    assert len(calls) == 1, "同一个 key 只能有一个生产者"


@pytest.mark.asyncio
async def test_failed_job_keeps_reason_queryable():
    async def producer():
        raise RuntimeError("路径 PPT 生成失败")

    job, _ = await path_video_jobs.ensure_path_video_job(8, 2, producer)

    assert await _settle(lambda: job.state != path_video_jobs.STATE_RUNNING)
    assert job.state == path_video_jobs.STATE_FAILED
    assert "路径 PPT 生成失败" in job.error
    # 终态必须还能查到：否则调用方只看到"从没生成过"，会不断重新发起。
    assert path_video_jobs.get_path_video_job(8, 2) is job


@pytest.mark.asyncio
async def test_finished_job_does_not_block_a_retry():
    async def failing():
        raise RuntimeError("先失败一次")

    first_job, _ = await path_video_jobs.ensure_path_video_job(9, 3, failing)
    assert await _settle(lambda: first_job.state == path_video_jobs.STATE_FAILED)

    async def succeeding():
        return {"path_id": 3}

    retry_job, retry_is_new = await path_video_jobs.ensure_path_video_job(9, 3, succeeding)

    assert retry_is_new is True, "已结束的作业不该挡住重试"
    assert retry_job is not first_job
    assert await _settle(lambda: retry_job.state == path_video_jobs.STATE_READY)
