# -*- coding: utf-8 -*-
"""学生确认画像之后**同步等待**的那条路径，得在超时之前回来。

症状：点完"确认画像"迟迟进不去学习概览，而且超时。原因是这条路上串了 6-10 次模型调用，
每次光首字延迟就二十几到三十几秒：

    方向→科目 1 次 + Leader 1 次（实测 105-185 秒）+ Executor 每 4 个节点一组
    （原来只允许 2 组并行）+ Reviewer 1 次（把整条路径的 JSON 塞进一个 prompt）

前端那次请求的超时是 5 分钟（`learningApi.generatePathFromDirection`），正好压在这条路的
中间，所以有时进得去、有时超时。

这里钉两件止血的事：Executor 的并行度、以及入口那条路径的节点数上限。
"""

import asyncio

import pytest

from backend.src.ai_core import path_graph
from backend.src.ai_core import llm_config
from backend.src.router import path_router
from backend.src.schemas.path import GenerateFromDirectionRequest


def test_the_executor_runs_more_than_two_groups_at_a_time():
    """20 个节点分 5 组：2 路并行是 3 波，4 路是 2 波 —— 一波就是一次模型往返。"""
    assert path_graph._MAX_GROUP_CONCURRENCY == 4


def test_the_group_concurrency_fits_the_per_user_pool():
    """入口路径和后台那条「其余科目」的生成会同时跑，两边各占满一半才对得上并发池。

    超过 `_PER_USER["path"]` 之后，后到的那一边只能在信号量上排队 —— 排队的是学生正在
    等的那条路径，等于把并行度提上去又把时间还回去。
    """
    budget = llm_config._PER_USER["path"]
    assert path_graph._MAX_GROUP_CONCURRENCY * 2 <= budget, (
        f"并发度 {path_graph._MAX_GROUP_CONCURRENCY} 下，入口 + 后台会占 "
        f"{path_graph._MAX_GROUP_CONCURRENCY * 2} 路，超过每用户 path 池的 {budget}"
    )


def test_the_group_size_still_packs_four_nodes_per_call():
    """每组的节点数没变（改的是同时跑几组）—— 这条只是防止顺手改了别的东西。"""
    assert path_graph._GROUP_SIZE == 4


class _FakePathService:
    """记下每个科目的生成参数，不真的调模型。"""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def generate_path(self, subject, user_id, difficulty="medium", node_count=0, force_regenerate=False):
        self.calls.append((subject, node_count))
        return {"path_id": len(self.calls), "subject": subject, "nodes": [{}] * 3}

    async def regenerate_path(self, path_id, user_id):
        return {"path_id": path_id, "nodes": [{}] * 3, "regenerated": True}

    async def enroll_path(self, path_id, user_id):
        return {}


async def _stub_subjects(user_id, direction, goal, limit, force_regenerate=False):
    return ["第一条科目", "第二条科目", "第三条科目"]


@pytest.fixture
def entry_call(monkeypatch):
    """把这条路上的模型/数据库全部换成假的，只留下"参数怎么传"可观察。"""
    fake = _FakePathService()
    monkeypatch.setattr(path_router, "PathService", fake)
    # 函数体里 import 的，要打在它被导入的那个模块上
    from backend.src.service.curriculum import service as curriculum_service

    monkeypatch.setattr(curriculum_service, "sync_direction_subjects", _stub_subjects)
    # 后台任务不在这里跑（那会让断言顺序不确定）：只记下"有东西被丢到后台了"
    background: list = []
    monkeypatch.setattr(path_router, "_track_background_path_task", lambda user_id, task: background.append(task))

    async def call(**overrides):
        # 一次调用 = 一轮记录：同一个测试里连着调两次（比如"要 20 个"和"要 6 个"）时，
        # 每次都能从 calls[0] 看这一轮的入口那条。
        fake.calls.clear()
        payload = {"direction": "机械制图"}
        payload.update(overrides)
        data = GenerateFromDirectionRequest(**payload)
        result = await path_router.generate_paths_from_direction(data=data, user_id=1)
        # 把后台那条也跑完再断言：假 service 是瞬时的，跑完就有确定的结果。
        # 直接 cancel 掉的话，"后台科目拿到什么参数"就没人观察得到 —— 变异测试里
        # "顺手把封顶也压到后台科目上"那一处会溜过去。
        await asyncio.gather(*background, return_exceptions=True)
        return result, fake, background

    return call


@pytest.mark.asyncio
async def test_the_path_students_wait_for_is_capped(entry_call):
    """同步等的那一条按上限生成：节点少一半，Executor 少一整波。"""
    result, fake, _ = await entry_call()

    subject, node_count = fake.calls[0]
    assert subject == "第一条科目"
    assert node_count == path_router._ENTRY_PATH_NODE_CAP
    assert result["data"]["paths"][0]["subject"] == "第一条科目"


@pytest.mark.asyncio
async def test_the_cap_leaves_the_length_in_the_normal_range(entry_call):
    """封顶不能把路径切到"不像一条路径"的程度 —— 自动算出来的长度本来就是 8 到 30。"""
    await entry_call()
    assert 8 <= path_router._ENTRY_PATH_NODE_CAP <= 30


@pytest.mark.asyncio
async def test_the_other_subjects_are_not_capped(entry_call):
    """其余科目没人等（后台生成），要按各自的正常长度来 —— 别把封顶顺手用在它们身上。"""
    result, fake, background = await entry_call()

    assert result["data"]["pending_subjects"] == ["第二条科目", "第三条科目"]
    assert len(background) == 1, "其余科目没有被丢到后台"
    assert fake.calls[0] == ("第一条科目", path_router._ENTRY_PATH_NODE_CAP)
    assert fake.calls[1:] == [("第二条科目", 0), ("第三条科目", 0)], (
        "后台科目也按入口的上限被砍短了（0 表示「自动」，即按各自的正常长度算）"
    )


@pytest.mark.asyncio
async def test_an_explicit_node_count_still_wins_for_the_entry_path(entry_call):
    """调用方明确要了节点数就照他说的（只有"自动"这一档才由封顶接手）。

    这里用的是上限本身：比它大的值会被压到上限 —— 那是封顶该干的事。
    """
    _, fake, _ = await entry_call(node_count=20)
    assert fake.calls[0] == ("第一条科目", path_router._ENTRY_PATH_NODE_CAP)

    _, fake, _ = await entry_call(node_count=6)
    assert fake.calls[0] == ("第一条科目", 6), "封顶把调用方要的长度往上顶了"


class _NoUser:
    """画像里也没有存下来的方向时，`User.filter(...).first()` 走到的就是"查不到"。"""

    @classmethod
    def filter(cls, **kwargs):
        return cls()

    async def first(self):
        return None


@pytest.mark.asyncio
async def test_a_second_tail_neither_cancels_the_first_nor_goes_unreferenced():
    """连点两次、或前端超时后重试时，两条后台尾巴都要活着。

    原来是"取消上一条、然后直接 return"：旧的被取消，新的没人引着（asyncio 对任务只持弱
    引用）随时被回收 —— 两头一夹，用户的其余科目永远生成不出来，只剩同步那一条路径。
    """
    path_router._BACKGROUND_PATH_TASKS.clear()
    first = asyncio.create_task(asyncio.sleep(0))
    second = asyncio.create_task(asyncio.sleep(0))

    path_router._track_background_path_task(7, first)
    path_router._track_background_path_task(7, second)

    assert not first.cancelled(), "上一条尾巴被取消了（它已经跑了的东西全丢）"
    assert path_router._BACKGROUND_PATH_TASKS[7] == {first, second}, (
        "新的那条没有登记：没有强引用会被回收"
    )

    await asyncio.gather(first, second)
    assert 7 not in path_router._BACKGROUND_PATH_TASKS, "跑完没有清理注册表"


@pytest.mark.asyncio
async def test_an_unusable_direction_is_still_refused(entry_call, monkeypatch):
    """改参数不能把旧守卫弄丢：方向不可用、画像里也没有，就该 400 让他回去补。

    这条路上以前放行过「不知道」—— 它被当成方向收下，然后拆出一整套跟学生毫无关系的科目。
    """
    from fastapi import HTTPException

    from backend.src.models import usermodel

    monkeypatch.setattr(usermodel, "User", _NoUser)

    with pytest.raises(HTTPException) as excinfo:
        await entry_call(direction="不知道")
    assert excinfo.value.status_code == 400
